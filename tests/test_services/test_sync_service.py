# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, CloudBSD
"""End-to-end sync test: SyncService wires HostService + InterfaceService + mock Provider."""

from __future__ import annotations

import pytest

from cloudflare_register.domain import HostConfig
from cloudflare_register.providers.base import DnsRecord, Provider
from cloudflare_register.services import HostService, InterfaceService, SyncService

ZONE = "abcdef0123456789abcdef0123456789"


class _CapturingProvider(Provider):
    name = "capturing"

    def __init__(self, existing: list[DnsRecord] | None = None) -> None:
        self.existing = list(existing or [])
        self.created: list[tuple[str, str, str, str, bool]] = []
        self.updated: list[tuple[str, str, str, str, str, bool]] = []
        self.deleted: list[tuple[str, str]] = []

    async def list_zones(self) -> list[dict[str, str]]:
        return []

    async def list_records(self, zone_id: str, name: str) -> list[DnsRecord]:
        return list(self.existing)

    async def create_record(self, zone_id, record_type, name, content, proxied=False, *, ttl=1):
        self.created.append((zone_id, record_type, name, content, proxied))
        return DnsRecord(
            record_id=f"new-{len(self.created)}",
            record_type=record_type,
            name=name,
            content=content,
            proxied=proxied,
            ttl=ttl,
        )

    async def update_record(
        self, zone_id, record_id, record_type, name, content, proxied=False, *, ttl=1
    ):
        self.updated.append((zone_id, record_id, record_type, name, content, proxied))
        return DnsRecord(
            record_id=record_id,
            record_type=record_type,
            name=name,
            content=content,
            proxied=proxied,
            ttl=ttl,
        )

    async def delete_record(self, zone_id, record_id):
        self.deleted.append((zone_id, record_id))

    async def close(self) -> None:
        pass


@pytest.fixture
def fixed_public_ips(monkeypatch):
    async def _v4(source_ip=None) -> str:
        return "203.0.113.10"

    async def _v6(source_ip=None) -> str | None:
        return "2001:db8::10"

    monkeypatch.setattr("cloudflare_register.services.sync_service.get_public_ipv4", _v4)
    monkeypatch.setattr("cloudflare_register.services.sync_service.get_public_ipv6", _v6)


def _seed_group(service: HostService, names: list[str], group: str | None) -> None:
    for n in names:
        service.add_host(
            HostConfig(hostname=n, zone_id=ZONE, zone_name="example.com", interface_group=group)
        )


async def test_run_once_creates_records_for_each_group(service_storage, fixed_public_ips):
    host_svc = HostService()
    _seed_group(host_svc, ["a.example.com", "b.example.com"], "home-wan")
    _seed_group(host_svc, ["c.example.com"], "vpn")

    provider = _CapturingProvider()
    sync = SyncService(
        host_service=host_svc,
        interface_service=InterfaceService(),
        provider=provider,
    )

    report = await sync.run_once()
    assert report.hosts_processed == 3
    assert report.groups_processed >= 1
    assert report.created == 6  # 3 hosts × (A + AAAA)
    assert len(provider.created) == 6


async def test_group_filter_only_processes_that_group(service_storage, fixed_public_ips):
    host_svc = HostService()
    _seed_group(host_svc, ["a.example.com"], "home-wan")
    _seed_group(host_svc, ["c.example.com"], "vpn")

    provider = _CapturingProvider()
    sync = SyncService(
        host_service=host_svc,
        interface_service=InterfaceService(),
        provider=provider,
    )

    report = await sync.run_once(group_filter="home-wan")
    assert report.hosts_processed == 1
    assert report.created == 2  # A + AAAA for the single host


async def test_run_once_with_no_hosts_returns_empty_report(service_storage):
    provider = _CapturingProvider()
    sync = SyncService(
        host_service=HostService(),
        interface_service=InterfaceService(),
        provider=provider,
    )
    report = await sync.run_once()
    assert report.hosts_processed == 0
    assert report.created == 0


async def test_run_once_with_provider_errors_captures_per_host(
    service_storage, fixed_public_ips, monkeypatch
):
    host_svc = HostService()
    _seed_group(host_svc, ["broken.example.com"], "home-wan")

    class _BoomProvider(_CapturingProvider):
        async def list_records(self, zone_id, name):
            raise RuntimeError("upstream outage")

    sync = SyncService(
        host_service=host_svc,
        interface_service=InterfaceService(),
        provider=_BoomProvider(),
    )
    report = await sync.run_once()
    assert report.hosts_processed == 1
    assert report.errors
    assert "broken.example.com" in report.errors[0]


@pytest.fixture
def service_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from cloudflare_register.config import reset_settings_cache

    reset_settings_cache()
    yield


async def test_run_once_detection_failure_deletes_nothing(service_storage, monkeypatch):
    """A transient IP-detection outage must never delete records."""
    from cloudflare_register.exceptions import IPDetectionError

    async def _fail(source_ip=None):
        raise IPDetectionError("all probes failed")

    monkeypatch.setattr("cloudflare_register.services.sync_service.get_public_ipv4", _fail)
    monkeypatch.setattr("cloudflare_register.services.sync_service.get_public_ipv6", _fail)

    host_svc = HostService()
    _seed_group(host_svc, ["a.example.com"], "home-wan")
    provider = _CapturingProvider()
    sync = SyncService(
        host_service=host_svc,
        interface_service=InterfaceService(),
        provider=provider,
    )
    report = await sync.run_once()
    assert provider.deleted == []
    assert provider.created == []
    assert report.hosts_processed == 0
    assert report.errors


async def test_run_once_no_families_at_all_deletes_nothing(service_storage, monkeypatch):
    """Both families 'absent' means the box is offline — do not wipe DNS."""

    async def _none(source_ip=None):
        return None

    monkeypatch.setattr("cloudflare_register.services.sync_service.get_public_ipv4", _none)
    monkeypatch.setattr("cloudflare_register.services.sync_service.get_public_ipv6", _none)

    host_svc = HostService()
    _seed_group(host_svc, ["a.example.com"], "home-wan")
    provider = _CapturingProvider()
    sync = SyncService(
        host_service=host_svc,
        interface_service=InterfaceService(),
        provider=provider,
    )
    report = await sync.run_once()
    assert provider.deleted == []
    assert report.hosts_processed == 0
    assert report.errors
