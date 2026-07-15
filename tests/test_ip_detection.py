"""IP detection tests using httpx's MockTransport."""

from __future__ import annotations

import httpx
import pytest

from cloudflare_register import ip_detection
from cloudflare_register.exceptions import IPDetectionError


def _handler(queue: list[tuple[int, str]]):
    def handler(request: httpx.Request) -> httpx.Response:
        if not queue:
            return httpx.Response(500, content=b"")
        status, body = queue.pop(0)
        return httpx.Response(status, content=body.encode("utf-8"))
    return handler


async def test_get_public_ipv4_returns_first_success(monkeypatch):
    ip_detection.reset_cache()
    queue = [(200, "1.2.3.4\n")] * 4
    transport = httpx.MockTransport(_handler(queue))
    monkeypatch.setattr(
        ip_detection, "_build_client", lambda: httpx.AsyncClient(transport=transport)
    )
    result = await ip_detection.get_public_ipv4()
    assert result == "1.2.3.4"


async def test_get_public_ipv4_returns_none_when_all_fail(monkeypatch):
    ip_detection.reset_cache()
    queue = [(500, "boom")] * 4
    transport = httpx.MockTransport(_handler(queue))
    monkeypatch.setattr(
        ip_detection, "_build_client", lambda: httpx.AsyncClient(transport=transport)
    )
    assert await ip_detection.get_public_ipv4() is None


async def test_get_public_ips_returns_none_pair_when_all_probes_fail(monkeypatch):
    ip_detection.reset_cache()
    transport = httpx.MockTransport(lambda request: httpx.Response(500))
    monkeypatch.setattr(
        ip_detection, "_build_client", lambda: httpx.AsyncClient(transport=transport)
    )
    ipv4, ipv6 = await ip_detection.get_public_ips()
    assert ipv4 is None and ipv6 is None
