"""Synchronization application service.

Two layers:

1. The pure ``reconcile_host`` function — given a provider, a host, and the
   target IPv4/IPv6, return the list of taken actions. Idempotent, no I/O
   state of its own, easy to unit-test.
2. The ``SyncService`` class — wires :class:`HostService`, the public IP
   endpoints, the registered interface groups, and a ``Provider`` strategy
   into a single cycle (or a forever-loop). This is what CLI/TUI/web
   controllers call.

Failure semantics: ``None`` for a family means *asserted absent* — records
of that type are deleted. When IP detection fails transiently the family is
:data:`UNKNOWN_ADDRESS` instead, and its records are left untouched.
"""

from __future__ import annotations

import asyncio
import ipaddress
from collections.abc import Awaitable, Callable
from typing import Any

from cloudflare_register.config import Settings, get_settings
from cloudflare_register.domain import HostConfig, SyncReport
from cloudflare_register.exceptions import CloudflareRegisterError, IPDetectionError
from cloudflare_register.ip_detection import get_public_ipv4, get_public_ipv6
from cloudflare_register.logging_setup import get_logger
from cloudflare_register.providers.base import DnsRecord, Provider
from cloudflare_register.services.host_service import HostService
from cloudflare_register.services.interface_service import InterfaceService

_LOGGER = get_logger(__name__)

UNBOUNDED = object()


class _UnknownAddress:
    """Sentinel: detection failed transiently; leave this family's records alone."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<unknown address>"


UNKNOWN_ADDRESS = _UnknownAddress()


def _same_address(left: str, right: str) -> bool:
    """Compare two textual IPs semantically (``2001:DB8::1`` == ``2001:db8:0:0:0:0:0:1``)."""
    try:
        return ipaddress.ip_address(left) == ipaddress.ip_address(right)
    except ValueError:
        return left == right


async def reconcile_host(
    provider: Provider,
    host: HostConfig,
    ipv4: str | None | _UnknownAddress,
    ipv6: str | None | _UnknownAddress,
) -> list[str]:
    """Apply the desired state for a single host. See module docstring."""
    actions: list[str] = []
    by_type: dict[str, list[DnsRecord]] = {}
    for existing_record in await provider.list_records(host.zone_id, host.hostname):
        by_type.setdefault(existing_record.record_type, []).append(existing_record)

    for record_type, content in (("A", ipv4), ("AAAA", ipv6)):
        if isinstance(content, _UnknownAddress):
            continue
        matching = by_type.get(record_type, [])
        record: DnsRecord | None = matching[0] if matching else None
        # A crashed run or an external actor can leave duplicates; keep the
        # first record as the managed one and delete the rest, otherwise a
        # stale duplicate keeps answering with the old address.
        for extra in matching[1:]:
            await provider.delete_record(host.zone_id, extra.record_id)
            actions.append(f"deleted duplicate {record_type} {host.hostname} ({extra.content})")
        if content is None:
            if record is not None:
                await provider.delete_record(host.zone_id, record.record_id)
                actions.append(f"deleted {record_type} {host.hostname} (no {record_type} address)")
            continue
        # Cloudflare forces TTL to "auto" (1) on proxied records.
        desired_ttl = 1 if host.proxied else host.ttl
        if record is None:
            await provider.create_record(
                host.zone_id, record_type, host.hostname, content, host.proxied, ttl=desired_ttl
            )
            actions.append(f"created {record_type} {host.hostname} -> {content}")
        elif (
            not _same_address(record.content, content)
            or record.proxied != host.proxied
            or (not host.proxied and record.ttl != desired_ttl)
        ):
            await provider.update_record(
                host.zone_id,
                record.record_id,
                record_type,
                host.hostname,
                content,
                host.proxied,
                ttl=desired_ttl,
            )
            actions.append(f"updated {record_type} {host.hostname}: {record.content} -> {content}")
    return actions


class SyncService:
    """Orchestrates a sync cycle (or a forever-loop).

    Composition:

    * :class:`HostService` for the host list and group resolution.
    * :class:`InterfaceService` for interface detection / default-route
      binding.
    * :class:`Provider` strategy for the actual Cloudflare REST calls.

    Groups bound to a specific interface publish the public IP seen from
    *that* interface (probes are source-bound to its address); unbound
    groups and the default group publish the default route's public IPs.
    """

    def __init__(
        self,
        *,
        host_service: HostService,
        interface_service: InterfaceService,
        provider: Provider,
        settings: Settings | None = None,
    ) -> None:
        self._hosts = host_service
        self._interfaces = interface_service
        self._provider = provider
        self._settings = settings or get_settings()

    async def _detect_family(
        self,
        getter: Callable[[str | None], Awaitable[str | None]],
        source_ip: str | None,
        *,
        bound: bool,
        family_label: str,
        group_label: str,
        report: SyncReport,
    ) -> str | None | _UnknownAddress:
        """Detect one family's public IP for a group.

        Returns the address, ``None`` (family asserted absent), or
        :data:`UNKNOWN_ADDRESS` (detection failed; leave records alone).
        """
        if bound and source_ip is None:
            # The bound interface has no address of this family at all.
            return None
        try:
            return await getter(source_ip)
        except IPDetectionError as exc:
            report.errors.append(
                f"group {group_label or '(default)'}: {family_label} detection failed "
                f"({exc}); leaving {family_label} records untouched"
            )
            return UNKNOWN_ADDRESS

    async def run_once(
        self,
        *,
        group_filter: str | None = None,
    ) -> SyncReport:
        report = SyncReport()
        hosts = self._hosts.list_hosts()
        if group_filter is not None:
            target = group_filter.lower()
            hosts = [h for h in hosts if (h.interface_group or "") == target]

        if not hosts:
            _LOGGER.info("sync: nothing to do (no hosts after filter)")
            return report

        groups_table = {g.name: g for g in self._hosts.load_interface_groups()}
        groups = _group_by_label(hosts)
        for group_label, members in groups.items():
            group_cfg = groups_table.get(group_label)
            iface_name = group_cfg.interface_name if group_cfg else None

            source_v4: str | None = None
            source_v6: str | None = None
            bound = bool(iface_name)
            if bound:
                resolved = self._interfaces.resolve_interface(iface_name)
                if resolved is None or not resolved.is_up:
                    report.errors.append(
                        f"group {group_label}: interface {iface_name!r} missing or down"
                    )
                    continue
                source_v4 = resolved.primary_ipv4
                source_v6 = resolved.primary_ipv6

            ipv4 = await self._detect_family(
                get_public_ipv4,
                source_v4,
                bound=bound,
                family_label="IPv4",
                group_label=group_label,
                report=report,
            )
            ipv6 = await self._detect_family(
                get_public_ipv6,
                source_v6,
                bound=bound,
                family_label="IPv6",
                group_label=group_label,
                report=report,
            )
            _LOGGER.info(
                "group %s: public ips ipv4=%s ipv6=%s",
                group_label or "(default)",
                ipv4,
                ipv6,
            )
            if isinstance(ipv4, _UnknownAddress) and isinstance(ipv6, _UnknownAddress):
                continue  # nothing actionable this cycle; errors already recorded
            if ipv4 is None and ipv6 is None:
                # No address family at all: the host is offline, not "both
                # families legitimately gone". Deleting every record here
                # would take the names out of DNS over a local outage.
                report.errors.append(
                    f"group {group_label or '(default)'}: no public address in either "
                    "family; leaving records untouched"
                )
                continue

            report.groups_processed += 1
            for host in members:
                report.hosts_processed += 1
                try:
                    actions = await reconcile_host(self._provider, host, ipv4, ipv6)
                except Exception as exc:  # noqa: BLE001 - report every error
                    _LOGGER.exception("reconcile failed for %s", host.hostname)
                    report.errors.append(f"{host.hostname}: {exc}")
                    continue
                report.actions.extend(actions)
                report.created += sum(1 for a in actions if a.startswith("created"))
                report.updated += sum(1 for a in actions if a.startswith("updated"))
                report.deleted += sum(1 for a in actions if a.startswith("deleted"))

        _LOGGER.info(
            "sync complete: groups=%d hosts=%d created=%d updated=%d deleted=%d errors=%d",
            report.groups_processed,
            report.hosts_processed,
            report.created,
            report.updated,
            report.deleted,
            len(report.errors),
        )
        return report

    async def run_forever(self, *, until: Any = UNBOUNDED) -> None:
        interval = self._settings.sync_interval_seconds
        _LOGGER.info("sync loop start; interval=%ds", interval)
        try:
            while True:
                if until is not UNBOUNDED and until.done():
                    break
                try:
                    await self.run_once()
                except CloudflareRegisterError as exc:
                    _LOGGER.error("sync cycle aborted: %s", exc)
                except Exception:  # noqa: BLE001 - a daemon must outlive one bad cycle
                    _LOGGER.exception("sync cycle failed unexpectedly")
                if until is UNBOUNDED:
                    await asyncio.sleep(interval)
                else:
                    # Wake as soon as `until` completes instead of sleeping
                    # out the full interval.
                    await asyncio.wait([asyncio.ensure_future(until)], timeout=interval)
        except asyncio.CancelledError:
            _LOGGER.info("sync loop cancelled")
            raise


def _group_by_label(hosts: list[HostConfig]) -> dict[str, list[HostConfig]]:
    out: dict[str, list[HostConfig]] = {}
    for host in hosts:
        out.setdefault(host.interface_group or "", []).append(host)
    return out
