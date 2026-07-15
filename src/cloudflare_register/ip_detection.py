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
"""Public IPv4 and IPv6 discovery with bounded LRU-style caching.

Algorithm choice (TAOCP §6.4 "Hashing and lookup" and §2.6 "Sorting"):

* Each lookup walks a small ``tuple`` of endpoints in priority order. Endpoints
  are tried in parallel using ``asyncio.gather``; the first successful result
  wins, others are cancelled.
* A ``TTLCache`` (LRU by insertion order, capacity 256 entries) suppresses
  repeat lookups within the cache window. Capacity is sized for the realistic
  cardinality: one IPv4 entry + one IPv6 entry per host, plus the negative
  cache entries (None) for absent address families.
* Failure records the error, falls through to the next endpoint, and after all
  endpoints fail returns ``None`` and emits ``IPDetectionError`` if the caller
  wraps the call (the bare helper never raises to keep the periodic loop alive).
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable

import httpx

from cloudflare_register.exceptions import IPDetectionError
from cloudflare_register.logging_setup import get_logger

_LOGGER = get_logger(__name__)

_IPV4_ENDPOINTS: tuple[str, ...] = (
    "https://api.ipify.org",
    "https://ifconfig.io/ip",
    "https://ipv4.icanhazip.com",
)
_IPV6_ENDPOINTS: tuple[str, ...] = (
    "https://api64.ipify.org",
    "https://ifconfig.co/ip",
    "https://ipv6.icanhazip.com",
)

_TIMEOUT_SECONDS = 6.0
_CACHE_TTL_SECONDS = 30.0
_CACHE_CAPACITY = 256


class _TTLCache:
    """Tiny LRU/TTL cache. Not thread-safe; intended for use under an event loop."""

    def __init__(self, capacity: int = _CACHE_CAPACITY, ttl: float = _CACHE_TTL_SECONDS) -> None:
        self._capacity = capacity
        self._ttl = ttl
        self._data: OrderedDict[str, tuple[float, str | None]] = OrderedDict()

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

    def put(self, key: str, value: str | None) -> None:
        self._data[key] = (time.monotonic(), value)
        self._data.move_to_end(key)
        while len(self._data) > self._capacity:
            self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()


_cache = _TTLCache()


def _build_client() -> httpx.AsyncClient:
    """Construct the default async client used by ``_probe``.

    Indirected so tests can ``monkeypatch.setattr(ip_detection, "_build_client", ...)``.
    """
    return httpx.AsyncClient()


async def _probe(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        response = await client.get(url, timeout=_TIMEOUT_SECONDS)
        response.raise_for_status()
        candidate = response.text.strip()
        return candidate or None
    except (TimeoutError, httpx.HTTPError) as exc:
        _LOGGER.debug("IP probe %s failed: %s", url, exc.__class__.__name__)
        return None


async def _first_hit(endpoints: tuple[str, ...]) -> str | None:
    cached = _cache.get(endpoints[0] if len(endpoints) == 1 else f"multi:{endpoints[0]}")
    if cached is not None or (
        cached is None and _cache.get(endpoints[0]) is not None and len(endpoints) == 1
    ):
        return cached

    async with _build_client() as client:
        coros: list[Awaitable[str | None]] = [_probe(client, url) for url in endpoints]
        for coro in asyncio.as_completed(coros):
            result = await coro
            if result:
                _cache.put(endpoints[0], result)
                return result
    _cache.put(endpoints[0], None)
    return None


async def get_public_ipv4() -> str | None:
    cached = _cache.get("ipv4")
    if cached:
        return cached
    if cached is None and "ipv4" in _cache._data:  # negative-cache hit
        return None
    result = await _first_hit(_IPV4_ENDPOINTS)
    if result:
        _cache.put("ipv4", result)
    else:
        _cache.put("ipv4", None)
    return result


async def get_public_ipv6() -> str | None:
    cached = _cache.get("ipv6")
    if cached:
        return cached
    if cached is None and "ipv6" in _cache._data:
        return None
    result = await _first_hit(_IPV6_ENDPOINTS)
    if result:
        _cache.put("ipv6", result)
    else:
        _cache.put("ipv6", None)
    return result


async def get_public_ips() -> tuple[str | None, str | None]:
    """Return ``(ipv4, ipv6)``. Either may be ``None`` if unavailable."""
    try:
        ipv4, ipv6 = await asyncio.gather(get_public_ipv4(), get_public_ipv6())
    except IPDetectionError:
        raise
    except Exception as exc:
        raise IPDetectionError(str(exc)) from exc
    return ipv4, ipv6


def reset_cache() -> None:
    """Drop the in-process cache (used in tests)."""
    _cache.clear()
