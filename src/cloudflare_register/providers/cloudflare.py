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

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{_BASE_URL}{path}"
        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._client.request(method, url, **kwargs)
            except httpx.HTTPError as exc:
                last_error = exc
                await asyncio.sleep(_RETRY_BACKOFF * (2**attempt))
                continue
            if response.status_code in (429, 500, 502, 503, 504):
                last_error = ProviderRateLimitError(f"{response.status_code} from {url}")
                retry_after = float(response.headers.get("Retry-After", "0") or 0)
                delay = retry_after or (_RETRY_BACKOFF * (2**attempt))
                await asyncio.sleep(delay)
                continue
            return self._decode(response)
        if last_error is not None:
            raise ProviderError(f"request failed after {_MAX_RETRIES} attempts: {last_error}")
        raise ProviderError("request failed without exception")

    def _decode(self, response: httpx.Response) -> Any:
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
        return payload.get("result")

    async def list_zones(self) -> list[dict[str, str]]:
        result = await self._request("GET", "/zones?per_page=50")
        return [{"id": z["id"], "name": z["name"]} for z in result]

    async def list_records(self, zone_id: str, name: str) -> list[DnsRecord]:
        result = await self._request(
            "GET",
            f"/zones/{zone_id}/dns_records?name={name}&per_page=100",
        )
        return [DnsRecord.from_cloudflare(r) for r in result]

    async def create_record(
        self, zone_id: str, record_type: str, name: str, content: str, proxied: bool = False
    ) -> DnsRecord:
        result = await self._request(
            "POST",
            f"/zones/{zone_id}/dns_records",
            json={
                "type": record_type,
                "name": name,
                "content": content,
                "proxied": proxied,
                "ttl": 1,
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
    ) -> DnsRecord:
        result = await self._request(
            "PUT",
            f"/zones/{zone_id}/dns_records/{record_id}",
            json={
                "type": record_type,
                "name": name,
                "content": content,
                "proxied": proxied,
                "ttl": 1,
            },
        )
        return DnsRecord.from_cloudflare(result)

    async def delete_record(self, zone_id: str, record_id: str) -> None:
        try:
            await self._request("DELETE", f"/zones/{zone_id}/dns_records/{record_id}")
        except ProviderNotFoundError:
            _LOGGER.debug("delete_record: id=%s already absent", record_id)
