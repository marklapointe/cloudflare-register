# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, CloudBSD
"""Network-interface detection service.

Wraps ``psutil.net_if_addrs()`` and a stdlib UDP-connect trick for default
route detection. All cross-platform quirks are isolated to this module so the
rest of the application can stay platform-agnostic.

Library choice (researched 2026-07):

* ``psutil`` 7.x — actively maintained, BSD-3, runs unprivileged on
  FreeBSD/Linux/macOS, no C-extension breakage.
* Default-route detection — stdlib UDP socket ``connect`` + ``getsockname``.
  Sends no packet; kernel selects source IP via FIB lookup. Wrappable in a
  try/except for loopback-only environments.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class InterfaceInfo:
    name: str
    ipv4: tuple[str, ...]
    ipv6: tuple[str, ...]
    is_up: bool

    @property
    def primary_ipv4(self) -> str | None:
        return self.ipv4[0] if self.ipv4 else None

    @property
    def primary_ipv6(self) -> str | None:
        return self.ipv6[0] if self.ipv6 else None


@dataclass(frozen=True)
class DefaultRoute:
    interface: str | None
    local_ipv4: str | None
    local_ipv6: str | None


def _udp_local_ip(family: int) -> str | None:
    target = ("8.8.8.8", 80) if family == socket.AF_INET else ("2001:4860:4860::8888", 80)
    sock = socket.socket(family, socket.SOCK_DGRAM)
    try:
        sock.connect(target)
    except OSError:
        sock.close()
        return None
    try:
        return str(sock.getsockname()[0])
    finally:
        sock.close()


def _find_interface_for_address(
    addresses: dict[str, Iterable[Any]], target: str | None
) -> str | None:
    """Reverse-lookup: given a local IP, return the interface name that owns it.

    ``psutil.net_if_addrs()`` keys by interface name; we need the inverse map
    because ``getsockname`` returns the chosen IP, not the interface name.
    """
    if target is None:
        return None
    for name, addrs in addresses.items():
        for addr in addrs:
            candidate = getattr(addr, "address", None)
            if candidate and candidate.split("%", 1)[0] == target:
                return name
    return None


def _split_addresses(addrs: Iterable[Any]) -> tuple[list[str], list[str]]:
    """Separate v4/v6 addresses, excluding loopback and link-local.

    psutil may report IPv6 addresses with a ``%scope`` suffix; that suffix is
    stripped so the values compare equal to what ``getsockname`` returns.
    """
    v4: list[str] = []
    v6: list[str] = []
    for addr in addrs:
        raw = getattr(addr, "address", None)
        if not raw:
            continue
        bare = raw.split("%", 1)[0]
        try:
            parsed = ipaddress.ip_address(bare)
        except ValueError:
            continue
        if addr.family == socket.AF_INET and not parsed.is_loopback:
            v4.append(bare)
        elif addr.family == socket.AF_INET6 and not (parsed.is_loopback or parsed.is_link_local):
            v6.append(bare)
    return v4, v6


class InterfaceService:
    """Enumerates local interfaces and the OS default-route interface.

    All methods are best-effort and may return ``None`` values when the host
    has no routable interfaces (e.g. a brand-new jail or a container with
    only loopback attached).
    """

    def list_interfaces(self) -> list[InterfaceInfo]:
        import psutil

        stats_by_name = psutil.net_if_stats() if hasattr(psutil, "net_if_stats") else {}
        interfaces: list[InterfaceInfo] = []
        for name, addrs in psutil.net_if_addrs().items():
            v4, v6 = _split_addresses(addrs)
            stats = stats_by_name.get(name)
            is_up = bool(stats.isup) if stats is not None else True
            interfaces.append(InterfaceInfo(name=name, ipv4=tuple(v4), ipv6=tuple(v6), is_up=is_up))
        interfaces.sort(key=lambda i: (not i.is_up, i.name))
        return interfaces

    def get_interface(self, name: str) -> InterfaceInfo | None:
        return next((i for i in self.list_interfaces() if i.name == name), None)

    def resolve_interface(self, name: str | None) -> InterfaceInfo | None:
        """``None`` ⇒ default route interface; a string ⇒ that interface.

        Returns ``None`` when the OS has no routable interface (loopback only,
        no default route, all addresses disabled).
        """
        if name:
            return self.get_interface(name)
        return self.default_route_interface()

    def default_route_interface(self) -> InterfaceInfo | None:
        """Interface that owns the OS default route.

        Determined by opening a UDP socket (no packet sent) and asking the
        kernel which local address it would use to reach a public IP. If that
        local address is found in the psutil address map, the owning
        interface is returned.
        """
        try:
            import psutil
        except ImportError:  # pragma: no cover
            return None

        v4_local = _udp_local_ip(socket.AF_INET)
        v6_local = _udp_local_ip(socket.AF_INET6)
        if not v4_local and not v6_local:
            return None

        addresses = psutil.net_if_addrs()
        owning = _find_interface_for_address(addresses, v4_local) or _find_interface_for_address(
            addresses, v6_local
        )
        if owning is None:
            return None

        v4, v6 = _split_addresses(addresses[owning])
        stats = psutil.net_if_stats().get(owning) if hasattr(psutil, "net_if_stats") else None
        is_up = bool(stats.isup) if stats is not None else True
        return InterfaceInfo(name=owning, ipv4=tuple(v4), ipv6=tuple(v6), is_up=is_up)

    def summary_lines(self) -> list[str]:
        rows = self.list_interfaces()
        if not rows:
            return ["no non-loopback interfaces detected"]
        lines = [f"{'NAME':<20} {'IPv4':<16} {'IPv6':<40} UP"]
        for r in rows:
            v4 = ", ".join(r.ipv4) or "-"
            v6 = ", ".join(r.ipv6) or "-"
            lines.append(f"{r.name:<20} {v4:<16} {v6:<40} {'yes' if r.is_up else 'no'}")
        default = self.default_route_interface()
        if default:
            lines.append(f"default route: {default.name}")
        else:
            lines.append("default route: <none>")
        return lines
