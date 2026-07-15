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


def _mock_client(monkeypatch, queue: list[tuple[int, str]]) -> None:
    transport = httpx.MockTransport(_handler(queue))
    monkeypatch.setattr(
        ip_detection,
        "_build_client",
        lambda local_address=None: httpx.AsyncClient(transport=transport),
    )


async def test_get_public_ipv4_returns_first_success(monkeypatch):
    ip_detection.reset_cache()
    _mock_client(monkeypatch, [(200, "1.2.3.4\n")] * 4)
    result = await ip_detection.get_public_ipv4()
    assert result == "1.2.3.4"


async def test_get_public_ipv4_absent_when_probes_fail_and_no_route(monkeypatch):
    ip_detection.reset_cache()
    _mock_client(monkeypatch, [(500, "boom")] * 4)
    monkeypatch.setattr(ip_detection, "_family_routable", lambda version: False)
    assert await ip_detection.get_public_ipv4() is None


async def test_get_public_ipv4_raises_when_probes_fail_but_route_exists(monkeypatch):
    """Transient probe failure must NOT be reported as 'family absent' —
    that distinction is what stops the sync engine from deleting records
    during an outage."""
    ip_detection.reset_cache()
    _mock_client(monkeypatch, [(500, "boom")] * 4)
    monkeypatch.setattr(ip_detection, "_family_routable", lambda version: True)
    with pytest.raises(IPDetectionError):
        await ip_detection.get_public_ipv4()


async def test_probe_rejects_wrong_family(monkeypatch):
    """A dual-stack endpoint answering a v6 lookup with the v4 address is rejected."""
    ip_detection.reset_cache()
    _mock_client(monkeypatch, [(200, "1.2.3.4")] * 4)
    monkeypatch.setattr(ip_detection, "_family_routable", lambda version: False)
    assert await ip_detection.get_public_ipv6() is None


async def test_probe_rejects_garbage_body(monkeypatch):
    """Captive-portal HTML must never become record content."""
    ip_detection.reset_cache()
    _mock_client(monkeypatch, [(200, "<html>login required</html>")] * 4)
    monkeypatch.setattr(ip_detection, "_family_routable", lambda version: False)
    assert await ip_detection.get_public_ipv4() is None


async def test_ipv6_result_is_normalized(monkeypatch):
    ip_detection.reset_cache()
    _mock_client(monkeypatch, [(200, "2001:DB8:0:0:0:0:0:1")] * 4)
    result = await ip_detection.get_public_ipv6()
    assert result == "2001:db8::1"


async def test_result_is_cached(monkeypatch):
    ip_detection.reset_cache()
    _mock_client(monkeypatch, [(200, "1.2.3.4")] * 4)
    first = await ip_detection.get_public_ipv4()
    # queue now empty: further probes would 500, so a second call must hit the cache
    second = await ip_detection.get_public_ipv4()
    assert first == second == "1.2.3.4"


async def test_source_bound_failure_raises(monkeypatch):
    """With an explicit source address, probe failure is always an error —
    the caller knows the interface has this family."""
    ip_detection.reset_cache()
    _mock_client(monkeypatch, [(500, "")] * 4)
    monkeypatch.setattr(ip_detection, "_family_routable", lambda version: False)
    with pytest.raises(IPDetectionError):
        await ip_detection.get_public_ipv4(source_ip="192.0.2.10")


async def test_get_public_ips_absent_pair(monkeypatch):
    ip_detection.reset_cache()
    _mock_client(monkeypatch, [])
    monkeypatch.setattr(ip_detection, "_family_routable", lambda version: False)
    ipv4, ipv6 = await ip_detection.get_public_ips()
    assert ipv4 is None and ipv6 is None
