# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, CloudBSD
"""Tests for HostService (CRUD, bulk, grouping, interface-group registry)."""

from __future__ import annotations

import pytest

from cloudflare_register.exceptions import PersistenceError
from cloudflare_register.services import HostService
from cloudflare_register.domain import HostConfig, InterfaceGroup

ZONE = "abcdef0123456789abcdef0123456789"


def _host(name: str, *, group: str | None = None, proxied: bool = False) -> HostConfig:
    return HostConfig(
        hostname=name,
        zone_id=ZONE,
        zone_name="example.com",
        proxied=proxied,
        interface_group=group,
    )


def test_add_and_list_roundtrip(service_storage):
    svc = HostService()
    svc.add_host(_host("a.example.com", group="home-wan"))
    svc.add_host(_host("b.example.com", group="home-wan"))
    svc.add_host(_host("c.example.com"))
    hosts = svc.list_hosts()
    assert {h.hostname for h in hosts} == {"a.example.com", "b.example.com", "c.example.com"}


def test_duplicate_add_rejected(service_storage):
    svc = HostService()
    svc.add_host(_host("dup.example.com"))
    with pytest.raises(PersistenceError):
        svc.add_host(_host("dup.example.com"))


def test_bulk_add_with_group(service_storage):
    svc = HostService()
    rows = [
        ("one.example.com", ZONE, "example.com", False),
        ("two.example.com", ZONE, "example.com", False),
        ("three.example.com", ZONE, "example.com", True),
    ]
    result = svc.add_hosts_bulk(rows, interface_group="vpn-tunnel")
    assert len(result.added) == 3
    assert result.skipped == []
    in_group = svc.hosts_in_group("vpn-tunnel")
    assert {h.hostname for h in in_group} == {"one.example.com", "two.example.com", "three.example.com"}


def test_bulk_add_skips_duplicates(service_storage):
    svc = HostService()
    svc.add_host(_host("pre.example.com"))
    rows = [
        ("pre.example.com", ZONE, "example.com", False),
        ("fresh.example.com", ZONE, "example.com", False),
    ]
    result = svc.add_hosts_bulk(rows)
    assert len(result.added) == 1
    assert result.added[0].hostname == "fresh.example.com"
    assert result.skipped[0][0] == "pre.example.com"


def test_remove_host(service_storage):
    svc = HostService()
    svc.add_host(_host("bye.example.com"))
    assert svc.remove_host("bye.example.com") is True
    assert svc.remove_host("never-existed.example.com") is False
    assert svc.list_hosts() == []


def test_reassign_group(service_storage):
    svc = HostService()
    svc.add_host(_host("x.example.com", group="home-wan"))
    svc.add_host(_host("y.example.com", group="home-wan"))
    svc.add_host(_host("z.example.com", group="vpn"))
    moved = svc.reassign_group("home-wan", None)
    assert moved == 2
    assert svc.hosts_in_group("home-wan") == []
    assert svc.hosts_in_group("vpn")[0].hostname == "z.example.com"


def test_register_interface_group_persists(service_storage):
    svc = HostService()
    svc.register_interface_group("home-wan", interface_name="eth0", description="WAN uplink")
    svc.register_interface_group("vpn", interface_name="wg0")
    groups = {g.name: g for g in svc.load_interface_groups()}
    assert groups["home-wan"].interface_name == "eth0"
    assert groups["vpn"].description == ""


def test_get_host_normalizes_case_and_dot(service_storage):
    svc = HostService()
    svc.add_host(_host("Foo.Example.com."))
    assert svc.get_host("foo.example.com") is not None


def test_list_groups_sorts(service_storage):
    svc = HostService()
    svc.add_host(_host("a.example.com", group="z"))
    svc.add_host(_host("b.example.com", group="a"))
    assert svc.list_groups() == ["a", "z"]


@pytest.fixture
def service_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from cloudflare_register.config import reset_settings_cache
    reset_settings_cache()
    yield
