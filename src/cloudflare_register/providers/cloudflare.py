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
"""Cloudflare v4 API implementation of the :class:`Provider` strategy.

Uses the ``httpx`` async client so a single connection pool services the
background sync loop and the web-UI wizard; ``python-cloudflare`` is still a
declared dependency for users who want ad-hoc CLI scripting, but business
code talks to ``Provider`` exclusively.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from cloudflare_register.exceptions import (
    ProviderAuthError,
    ProviderError,
    ProviderNotFoundError,
    ProviderRateLimitError,
)
from cloudflare_register.logging_setup import get_logger
from cloudflare_register.providers.base import DnsRecord, Provider

_LOGGER = get_logger(__name__)

_BASE_URL = "https://api.cloudflare.com/client/v4"
_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
_MAX_RETRIES = 3
_RETRY_BACKOFF = 1.5
_MAX_RETRY_AFTER = 30.0  # cap server-suggested delays so one bad header can't stall the loop
_ZONES_PER_PAGE = 50


class CloudflareProvider(Provider):
    """Async Cloudflare DNS provider using the public REST API."""

    name = "cloudflare"

    def __init__(self, token: str, *, client: httpx.AsyncClient | None = None) -> None:
        if not token or token.startswith("replace_me"):
            raise ProviderAuthError("Cloudflare API token missing or unset")
        self._token = token
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=_TIMEOUT,
            headers={"Authorization": f"Bearer {self._token}"},
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @staticmethod
    def _retry_delay(response: httpx.Response, attempt: int) -> float:
        raw: str = response.headers.get("Retry-After", "")
        retry_after: float
        try:
            retry_after = float(raw)
        except ValueError:
            retry_after = 0.0  # HTTP-date form or garbage: use exponential backoff
        if retry_after > 0:
            return min(retry_after, _MAX_RETRY_AFTER)
        return _RETRY_BACKOFF * (2.0**attempt)

    async def _request(self, method: str, path: str, *, full: bool = False, **kwargs: Any) -> Any:
        """Issue one API request with bounded retries.

        Raises the *typed* error from the final attempt
        (:class:`ProviderRateLimitError` for 429, :class:`ProviderError`
        for 5xx/transport failures) so callers can back off appropriately.
        """
        url = f"{_BASE_URL}{path}"
        for attempt in range(_MAX_RETRIES):
            last_attempt = attempt == _MAX_RETRIES - 1
            try:
                response = await self._client.request(method, url, **kwargs)
            except httpx.HTTPError as exc:
                # Only retry a non-idempotent method when the request never
                # reached the server; retrying a timed-out POST can create
                # duplicate records.
                idempotent = method.upper() in {"GET", "PUT", "DELETE"}
                retriable = idempotent or isinstance(exc, httpx.ConnectError)
                if not retriable or last_attempt:
                    raise ProviderError(f"transport failure for {url}: {exc}") from exc
                await asyncio.sleep(_RETRY_BACKOFF * (2**attempt))
                continue
            if response.status_code == 429 or response.status_code in (500, 502, 503, 504):
                if response.status_code == 429:
                    error: ProviderError = ProviderRateLimitError(f"429 rate limited from {url}")
                else:
                    error = ProviderError(f"{response.status_code} server error from {url}")
                if last_attempt:
                    raise error
                await asyncio.sleep(self._retry_delay(response, attempt))
                continue
            return self._decode(response, full=full)
        raise ProviderError("request failed without exception")  # pragma: no cover

    def _decode(self, response: httpx.Response, *, full: bool = False) -> Any:
        if response.status_code in (401, 403):
            raise ProviderAuthError(f"{response.status_code} {response.text[:200]}")
        if response.status_code == 404:
            raise ProviderNotFoundError(f"{response.status_code} {response.text[:200]}")
        if not response.is_success:
            raise ProviderError(f"{response.status_code} {response.text[:200]}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError(f"non-JSON response: {exc}") from exc
        if not payload.get("success", False):
            errors = payload.get("errors") or []
            message = "; ".join(str(e.get("message", e)) for e in errors) or "unspecified failure"
            raise ProviderError(message)
        return payload if full else payload.get("result")

    async def list_zones(self) -> list[dict[str, str]]:
        zones: list[dict[str, str]] = []
        page = 1
        while True:
            payload = await self._request(
                "GET",
                "/zones",
                full=True,
                params={"per_page": _ZONES_PER_PAGE, "page": page},
            )
            zones.extend({"id": z["id"], "name": z["name"]} for z in payload.get("result") or [])
            info = payload.get("result_info") or {}
            total_pages = int(info.get("total_pages") or 1)
            if page >= total_pages:
                return zones
            page += 1

    async def list_records(self, zone_id: str, name: str) -> list[DnsRecord]:
        result = await self._request(
            "GET",
            f"/zones/{zone_id}/dns_records",
            params={"name": name, "per_page": 100},
        )
        return [DnsRecord.from_cloudflare(r) for r in result]

    async def create_record(
        self,
        zone_id: str,
        record_type: str,
        name: str,
        content: str,
        proxied: bool = False,
        *,
        ttl: int = 1,
    ) -> DnsRecord:
        result = await self._request(
            "POST",
            f"/zones/{zone_id}/dns_records",
            json={
                "type": record_type,
                "name": name,
                "content": content,
                "proxied": proxied,
                "ttl": ttl,
            },
        )
        return DnsRecord.from_cloudflare(result)

    async def update_record(
        self,
        zone_id: str,
        record_id: str,
        record_type: str,
        name: str,
        content: str,
        proxied: bool = False,
        *,
        ttl: int = 1,
    ) -> DnsRecord:
        result = await self._request(
            "PUT",
            f"/zones/{zone_id}/dns_records/{record_id}",
            json={
                "type": record_type,
                "name": name,
                "content": content,
                "proxied": proxied,
                "ttl": ttl,
            },
        )
        return DnsRecord.from_cloudflare(result)

    async def delete_record(self, zone_id: str, record_id: str) -> None:
        try:
            await self._request("DELETE", f"/zones/{zone_id}/dns_records/{record_id}")
        except ProviderNotFoundError:
            _LOGGER.debug("delete_record: id=%s already absent", record_id)
