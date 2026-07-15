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
"""CloudflareProvider tests using a fake async client (no real HTTP calls)."""

from __future__ import annotations

from typing import Any

import pytest

from cloudflare_register.exceptions import (
    ProviderAuthError,
    ProviderNotFoundError,
)
from cloudflare_register.providers.base import DnsRecord
from cloudflare_register.providers.cloudflare import CloudflareProvider


class _FakeResponse:
    def __init__(
        self, status_code: int, body: dict[str, Any] | None = None, text: str = ""
    ) -> None:
        self.status_code = status_code
        self._body = body or {}
        self.text = text
        self.headers: dict[str, str] = {}

    def json(self) -> dict[str, Any]:
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300


class _FakeAsyncClient:
    def __init__(self, scripted: list[_FakeResponse]) -> None:
        self._scripted = list(scripted)
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    async def request(self, method: str, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append((method, url, kwargs))
        if not self._scripted:
            raise AssertionError("unexpected call")
        return self._scripted.pop(0)

    async def aclose(self) -> None:
        pass


async def test_list_zones_parses_response() -> None:
    body = {"success": True, "result": [{"id": "z1", "name": "example.com"}]}
    fake = _FakeAsyncClient([_FakeResponse(200, body)])
    provider = CloudflareProvider("good-token", client=fake)  # type: ignore[arg-type]
    try:
        zones = await provider.list_zones()
    finally:
        await provider.close()
    assert zones == [{"id": "z1", "name": "example.com"}]


async def test_create_record_returns_record() -> None:
    body = {
        "success": True,
        "result": {
            "id": "rec1",
            "type": "A",
            "name": "box.example.com",
            "content": "1.1.1.1",
            "ttl": 1,
            "proxied": False,
        },
    }
    fake = _FakeAsyncClient([_FakeResponse(200, body)])
    provider = CloudflareProvider("good-token", client=fake)  # type: ignore[arg-type]
    try:
        record = await provider.create_record("zoneid", "A", "box.example.com", "1.1.1.1")
    finally:
        await provider.close()
    assert record.record_id == "rec1"
    assert record.content == "1.1.1.1"
    assert record.record_type == "A"


async def test_auth_error_raises_typed_exception() -> None:
    body = {"success": False, "errors": [{"message": "bad token"}]}
    fake = _FakeAsyncClient([_FakeResponse(401, body, "Unauthorized")])
    provider = CloudflareProvider("good-token", client=fake)  # type: ignore[arg-type]
    with pytest.raises(ProviderAuthError):
        await provider.list_zones()
    await provider.close()


async def test_404_raises_not_found() -> None:
    fake = _FakeAsyncClient(
        [_FakeResponse(404, {"success": False, "errors": [{"message": "missing"}]}, "not found")]
    )
    provider = CloudflareProvider("good-token", client=fake)  # type: ignore[arg-type]
    with pytest.raises(ProviderNotFoundError):
        await provider.list_zones()
    await provider.close()


async def test_missing_token_rejected() -> None:
    with pytest.raises(ProviderAuthError):
        CloudflareProvider("")


async def test_delete_missing_record_is_silent() -> None:
    fake = _FakeAsyncClient(
        [_FakeResponse(404, {"success": False, "errors": [{"message": "gone"}]}, "missing")]
    )
    provider = CloudflareProvider("good-token", client=fake)  # type: ignore[arg-type]
    try:
        await provider.delete_record("z", "rec")  # must not raise
    finally:
        await provider.close()


def test_dns_record_from_cloudflare() -> None:
    raw = {
        "id": "x",
        "type": "AAAA",
        "name": "box.example.com",
        "content": "::1",
        "ttl": 300,
        "proxied": True,
        "zone_id": "zzz",
    }
    record = DnsRecord.from_cloudflare(raw)
    assert record.record_type == "AAAA"
    assert record.proxied is True
    assert record.extra == {"zone_id": "zzz"}
