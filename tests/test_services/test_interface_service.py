# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, CloudBSD
"""Tests for InterfaceService (psutil + UDP-connect default route)."""

from __future__ import annotations

import socket

import pytest

from cloudflare_register.services import InterfaceService


def test_list_interfaces_filters_loopback_and_link_local():
    svc = InterfaceService()
    interfaces = svc.list_interfaces()
    assert isinstance(interfaces, list)
    for iface in interfaces:
        for ip in iface.ipv4:
            assert not ip.startswith("127.")
        for ip in iface.ipv6:
            assert not ip.startswith("::1")
            assert not ip.startswith("fe80")


def test_get_interface_returns_none_for_unknown():
    svc = InterfaceService()
    assert svc.get_interface("does-not-exist-xyzzy") is None


def test_summary_lines_is_human_readable():
    svc = InterfaceService()
    lines = svc.summary_lines()
    assert isinstance(lines, list)
    assert len(lines) >= 1
    assert any("default route" in line for line in lines) or any("NAME" in line for line in lines)


def test_default_route_interface_in_known_set(monkeypatch):
    """When a UDP-connect default-route lookup succeeds, the returned interface
    must be one of the interfaces that psutil reports."""
    svc = InterfaceService()
    default = svc.default_route_interface()
    if default is None:
        pytest.skip("environment has no default route (e.g. offline CI)")
    names = {iface.name for iface in svc.list_interfaces()}
    assert default.name in names


def test_resolve_interface_passes_through(monkeypatch):
    svc = InterfaceService()
    svc.list_interfaces()  # warm psutil cache
    real_default = svc.default_route_interface()
    if real_default is None:
        pytest.skip("no default route")
    resolved = svc.resolve_interface(None)
    assert resolved is not None and resolved.name == real_default.name


def test_find_interface_for_address_handles_none():
    from cloudflare_register.services.interface_service import _find_interface_for_address

    assert _find_interface_for_address({}, None) is None
    assert _find_interface_for_address({}, "192.0.2.1") is None


def test_find_interface_for_address_returns_owner():
    from cloudflare_register.services.interface_service import _find_interface_for_address

    class _Addr:
        def __init__(self, address, family):
            self.address = address
            self.family = family

    mapping = {"eth0": [_Addr("10.0.0.1", socket.AF_INET)]}
    assert _find_interface_for_address(mapping, "10.0.0.1") == "eth0"
