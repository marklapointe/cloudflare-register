# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, CloudBSD
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice,
#    this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# 3. Neither the name of the copyright holder nor the names of its
#    contributors may be used to endorse or promote products derived from
#    this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
"""Public IPv4 and IPv6 discovery with a small TTL cache.

Semantics matter here because the sync engine deletes DNS records for an
address family it believes is *absent*:

* An endpoint response is accepted only if it parses as an IP address of
  the requested family (dual-stack echo services otherwise return the
  IPv4 address to v6 lookups, and captive portals return HTML).
* ``None`` means the address family is **absent**: every probe failed *and*
  the kernel has no route for that family (checked with a connectionless
  UDP ``connect``, no packet sent).
* :class:`IPDetectionError` is raised when probes failed although the
  family appears routable — a transient outage. Callers must leave DNS
  records untouched in that case rather than deleting them.

An optional ``source_ip`` binds the probes to a specific local address so
interface groups publish the IP of *their* uplink, not the default route's.
Results are cached per ``(family, source)`` for a short TTL.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
from collections import OrderedDict

import httpx

from cloudflare_register.exceptions import IPDetectionError
from cloudflare_register.logging_setup import get_logger

_LOGGER = get_logger(__name__)

# Family-specific hostnames only: a dual-stack endpoint answers v6 lookups
# with the v4 address when the host has no IPv6 connectivity.
_IPV4_ENDPOINTS: tuple[str, ...] = (
    "https://api.ipify.org",
    "https://ipv4.icanhazip.com",
    "https://v4.ident.me",
)
_IPV6_ENDPOINTS: tuple[str, ...] = (
    "https://api6.ipify.org",
    "https://ipv6.icanhazip.com",
    "https://v6.ident.me",
)

_TIMEOUT_SECONDS = 6.0
_CACHE_TTL_SECONDS = 30.0
_CACHE_CAPACITY = 32  # a handful of (family, source) pairs
_ABSENT = "<absent>"


class _TTLCache:
    """Tiny LRU/TTL cache. Not thread-safe; intended for use under an event loop."""

    def __init__(self, capacity: int = _CACHE_CAPACITY, ttl: float = _CACHE_TTL_SECONDS) -> None:
        self._capacity = capacity
        self._ttl = ttl
        self._data: OrderedDict[str, tuple[float, str]] = OrderedDict()

    def get(self, key: str) -> str | None:
        hit = self._data.get(key)
        if hit is None:
            return None
        stored_at, value = hit
        if (time.monotonic() - stored_at) > self._ttl:
            self._data.pop(key, None)
            return None
        self._data.move_to_end(key)
        return value

    def put(self, key: str, value: str) -> None:
        self._data[key] = (time.monotonic(), value)
        self._data.move_to_end(key)
        while len(self._data) > self._capacity:
            self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()


_cache = _TTLCache()


def _build_client(local_address: str | None = None) -> httpx.AsyncClient:
    """Construct the async client used by ``_probe``.

    Indirected so tests can ``monkeypatch.setattr(ip_detection, "_build_client", ...)``.
    """
    if local_address:
        transport = httpx.AsyncHTTPTransport(local_address=local_address)
        return httpx.AsyncClient(transport=transport)
    return httpx.AsyncClient()


def _family_routable(version: int) -> bool:
    """Best-effort: does the kernel have a route for this address family?

    A connectionless UDP ``connect`` asks the routing table without sending
    a packet. Indirected for tests.
    """
    family = socket.AF_INET if version == 4 else socket.AF_INET6
    target = ("8.8.8.8", 53) if version == 4 else ("2001:4860:4860::8888", 53)
    try:
        with socket.socket(family, socket.SOCK_DGRAM) as sock:
            sock.connect(target)
            return True
    except OSError:
        return False


async def _probe(client: httpx.AsyncClient, url: str, version: int) -> str | None:
    try:
        response = await client.get(url, timeout=_TIMEOUT_SECONDS)
        response.raise_for_status()
        candidate = response.text.strip()
    except (TimeoutError, httpx.HTTPError) as exc:
        _LOGGER.debug("IP probe %s failed: %s", url, exc.__class__.__name__)
        return None
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        _LOGGER.debug("IP probe %s returned a non-address: %.80r", url, candidate)
        return None
    if address.version != version:
        _LOGGER.debug("IP probe %s returned IPv%d, wanted IPv%d", url, address.version, version)
        return None
    return str(address)  # normalized (e.g. compressed IPv6) for stable comparisons


async def _first_hit(
    endpoints: tuple[str, ...], version: int, source_ip: str | None = None
) -> str | None:
    """Probe all endpoints concurrently; first valid answer wins.

    Losing probes are cancelled and awaited before the client closes.
    """
    async with _build_client(source_ip) as client:
        tasks = [asyncio.create_task(_probe(client, url, version)) for url in endpoints]
        try:
            for future in asyncio.as_completed(tasks):
                result = await future
                if result:
                    return result
            return None
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


async def _get_public_ip(
    version: int, endpoints: tuple[str, ...], source_ip: str | None
) -> str | None:
    key = f"ipv{version}:{source_ip or 'default'}"
    cached = _cache.get(key)
    if cached == _ABSENT:
        return None
    if cached is not None:
        return cached
    result = await _first_hit(endpoints, version, source_ip)
    if result:
        _cache.put(key, result)
        return result
    # All probes failed. Only report "family absent" when the kernel agrees
    # there is no route; otherwise this is a transient failure and deleting
    # DNS records over it would be data loss.
    if source_ip is not None or _family_routable(version):
        raise IPDetectionError(
            f"all IPv{version} probe endpoints failed although IPv{version} appears routable"
        )
    _cache.put(key, _ABSENT)
    return None


async def get_public_ipv4(source_ip: str | None = None) -> str | None:
    """Public IPv4, ``None`` if the family is absent. Raises on transient failure."""
    return await _get_public_ip(4, _IPV4_ENDPOINTS, source_ip)


async def get_public_ipv6(source_ip: str | None = None) -> str | None:
    """Public IPv6, ``None`` if the family is absent. Raises on transient failure."""
    return await _get_public_ip(6, _IPV6_ENDPOINTS, source_ip)


async def get_public_ips(
    source_ipv4: str | None = None, source_ipv6: str | None = None
) -> tuple[str | None, str | None]:
    """Return ``(ipv4, ipv6)``; either may be ``None`` when that family is absent.

    Raises :class:`IPDetectionError` if either family's detection fails
    transiently — callers must not treat that as "no address".
    """
    ipv4, ipv6 = await asyncio.gather(get_public_ipv4(source_ipv4), get_public_ipv6(source_ipv6))
    return ipv4, ipv6


def reset_cache() -> None:
    """Drop the in-process cache (used in tests)."""
    _cache.clear()
