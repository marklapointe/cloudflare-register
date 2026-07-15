"""Synchronization application service.

Two layers:

1. The pure ``reconcile_host`` function — given a provider, a host, and the
   target IPv4/IPv6, return the list of taken actions. Idempotent, no I/O
   state of its own, easy to unit-test.
2. The ``SyncService`` class — wires :class:`HostService`, the public IP
   endpoints, the registered interface groups, and a ``Provider`` strategy
   into a single cycle (or a forever-loop). This is what CLI/TUI/web
   controllers call.
"""

from __future__ import annotations

import asyncio

from cloudflare_register.config import Settings, get_settings
from cloudflare_register.domain import HostConfig, SyncReport
from cloudflare_register.exceptions import CloudflareRegisterError
from cloudflare_register.ip_detection import get_public_ipv4, get_public_ipv6
from cloudflare_register.logging_setup import get_logger
from cloudflare_register.providers.base import Provider
from cloudflare_register.services.host_service import HostService
from cloudflare_register.services.interface_service import InterfaceService

_LOGGER = get_logger(__name__)

UNBOUNDED = object()


async def reconcile_host(
    provider: Provider,
    host: HostConfig,
    ipv4: str | None,
    ipv6: str | None,
) -> list[str]:
    """Apply the desired state for a single host. See ``reconcile_group``."""
    actions: list[str] = []
    existing = {r.record_type: r for r in await provider.list_records(host.zone_id, host.hostname)}
    for record_type, content in (("A", ipv4), ("AAAA", ipv6)):
        record = existing.get(record_type)
        if content is None:
            if record is not None:
                await provider.delete_record(host.zone_id, record.record_id)
                actions.append(f"deleted {record_type} {host.hostname} (no {record_type} address)")
            continue
        if record is None:
            await provider.create_record(
                host.zone_id, record_type, host.hostname, content, host.proxied
            )
            actions.append(f"created {record_type} {host.hostname} -> {content}")
        elif record.content != content or record.proxied != host.proxied:
            await provider.update_record(
                host.zone_id,
                record.record_id,
                record_type,
                host.hostname,
                content,
                host.proxied,
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

    Public IPs are fetched ONCE per cycle. When multiple groups exist, the
    same IP set may be reused across groups (the public IPv4 is always the
    same regardless of the interface the OS would *send* the request from,
    in the typical home-server case).
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

        ipv4, ipv6 = await asyncio.gather(get_public_ipv4(), get_public_ipv6())
        _LOGGER.info("discovered public ips: ipv4=%s ipv6=%s", ipv4, ipv6)

        groups = _group_by_label(hosts)
        for group_label, members in groups.items():
            if group_label == "":
                iface_name = None
                resolved = self._interfaces.default_route_interface()
            else:
                groups_table = {g.name: g for g in self._hosts.load_interface_groups()}
                iface_name = (
                    groups_table.get(group_label).interface_name
                    if group_label in groups_table
                    else None
                )
                resolved = self._interfaces.resolve_interface(iface_name)

            if iface_name and resolved is None:
                report.errors.append(
                    f"group {group_label}: interface {iface_name!r} missing or down"
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

    async def run_forever(self, *, until=UNBOUNDED) -> None:
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
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            _LOGGER.info("sync loop cancelled")
            raise


def _group_by_label(hosts: list[HostConfig]) -> dict[str, list[HostConfig]]:
    out: dict[str, list[HostConfig]] = {}
    for host in hosts:
        out.setdefault(host.interface_group or "", []).append(host)
    return out
