"""Host registry service.

Single owner of all read/write operations against the persistent host list.
Controllers (CLI / web / TUI) call into ``HostService``; they never reach into
``persistence`` directly. This makes the service easy to mock in tests and
re-implement (e.g. on top of a database) without touching the adapters.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from cloudflare_register.domain import HostConfig, InterfaceGroup
from cloudflare_register.exceptions import PersistenceError
from cloudflare_register.logging_setup import get_logger
from cloudflare_register.persistence import (
    HostConfig as LegacyHostConfig,
)
from cloudflare_register.persistence import (
    groups_mutation_lock,
    hosts_mutation_lock,
)
from cloudflare_register.persistence import (
    load_hosts_config as legacy_load,
)
from cloudflare_register.persistence import (
    save_hosts_config as legacy_save,
)

_LOGGER = get_logger(__name__)


@dataclass
class HostBulkResult:
    added: list[HostConfig]
    skipped: list[tuple[str, str]]  # (hostname, reason)


class HostService:
    """Encapsulates CRUD + grouping operations on managed hosts.

    The service deliberately depends on the legacy functions exposed by
    :mod:`cloudflare_register.persistence`. They already implement
    atomic-write semantics with locking; the service only adds use-case-level
    behavior such as "add a hostname unless it already exists" and
    "delete-by-group".
    """

    def __init__(self, *, storage_path: Path | None = None) -> None:
        # storage_path is currently advisory; persistence derives the real path
        # from settings. Reserved for future pluggable backends.
        self._storage_path = storage_path

    # ---- list / read -------------------------------------------------------

    def list_hosts(self) -> list[HostConfig]:
        entries = [_migrate(entry) for entry in legacy_load()]
        return sorted(entries, key=lambda h: (h.interface_group or "", h.hostname))

    def get_host(self, hostname: str) -> HostConfig | None:
        target = hostname.strip().lower().rstrip(".")
        return next((h for h in self.list_hosts() if h.hostname == target), None)

    def list_groups(self) -> list[str]:
        groups = {h.interface_group for h in self.list_hosts() if h.interface_group}
        return sorted(groups)

    def hosts_in_group(self, group_name: str) -> list[HostConfig]:
        return [h for h in self.list_hosts() if h.interface_group == group_name.lower()]

    # ---- mutating ---------------------------------------------------------

    def add_host(self, host: HostConfig) -> HostConfig:
        with hosts_mutation_lock():
            existing = self.list_hosts()
            if any(h.hostname == host.hostname for h in existing):
                raise PersistenceError(f"hostname {host.hostname} already managed")
            existing.append(host)
            legacy_save(existing)
        _LOGGER.info("added host %s in group=%s", host.hostname, host.interface_group or "<none>")
        return host

    def add_hosts_bulk(
        self,
        hostnames: Iterable[tuple[str, str, str, bool]],
        *,
        interface_group: str | None = None,
    ) -> HostBulkResult:
        """Add many hostnames at once.

        Each tuple is ``(hostname, zone_id, zone_name, proxied)``. Hosts
        whose hostname already exists are skipped (not errored). All additions
        share the same ``interface_group`` if provided.
        """
        added: list[HostConfig] = []
        skipped: list[tuple[str, str]] = []
        with hosts_mutation_lock():
            snapshot = self.list_hosts()
            existing = {h.hostname for h in snapshot}
            for hostname, zone_id, zone_name, proxied in hostnames:
                try:
                    host = HostConfig(
                        hostname=hostname,
                        zone_id=zone_id,
                        zone_name=zone_name,
                        proxied=proxied,
                        interface_group=interface_group,
                    )
                except ValueError as exc:
                    skipped.append((hostname, str(exc)))
                    continue
                if host.hostname in existing:
                    skipped.append((hostname, "already managed"))
                    continue
                snapshot.append(host)
                existing.add(host.hostname)
                added.append(host)

            if added:
                legacy_save(snapshot)
        if added:
            _LOGGER.info(
                "bulk-added %d host(s) to group=%s", len(added), interface_group or "<none>"
            )
        return HostBulkResult(added=added, skipped=skipped)

    def remove_host(self, hostname: str) -> bool:
        target = hostname.strip().lower().rstrip(".")
        with hosts_mutation_lock():
            current = self.list_hosts()
            filtered = [h for h in current if h.hostname != target]
            if len(filtered) == len(current):
                return False
            legacy_save(filtered)
        _LOGGER.info("removed host %s", target)
        return True

    def reassign_group(self, group_name: str, new_group: str | None) -> int:
        """Move all hosts currently tagged ``group_name`` to ``new_group``.

        Returns the number of hosts reassigned. Used when an interface
        changes (e.g. switching from eth0 to a VPN tunnel). The new group
        name goes through the model validator (``validate_assignment``), so
        an invalid name raises ``ValueError`` before anything is persisted.
        """
        normalized_old = group_name.lower()
        moved = 0
        with hosts_mutation_lock():
            current = self.list_hosts()
            for host in current:
                if host.interface_group == normalized_old:
                    host.interface_group = new_group  # validated on assignment
                    moved += 1
            if moved:
                legacy_save(current)
        if moved:
            _LOGGER.info("reassigned %d host(s) from %s to %s", moved, normalized_old, new_group)
        return moved

    # ---- interface-group registry -----------------------------------------

    def load_interface_groups(self) -> list[InterfaceGroup]:
        """Return the registered interface-group bindings from disk.

        Delegates to :func:`cloudflare_register.persistence.load_interface_groups`.
        """
        from cloudflare_register.persistence import load_interface_groups as _load

        return _load()

    def infer_interface_groups(self) -> list[InterfaceGroup]:
        """Best-effort fallback: groups inferred from hosts that have no binding.

        Useful for callers that want to show a UI before any ``register-group``
        has been performed.
        """
        registered = {g.name for g in self.load_interface_groups()}
        referenced = {
            h.interface_group
            for h in self.list_hosts()
            if h.interface_group and h.interface_group not in registered
        }
        return [
            InterfaceGroup(name=g, interface_name=None, enabled=True) for g in sorted(referenced)
        ]

    def register_interface_group(
        self,
        name: str,
        *,
        interface_name: str | None = None,
        description: str = "",
    ) -> InterfaceGroup:
        """Register (or update) a named interface group binding.

        Stored alongside the hosts file but in a tiny separate index file so
        renaming a group doesn't require rewriting every host entry.
        """
        group = InterfaceGroup(
            name=name, interface_name=interface_name, description=description, enabled=True
        )
        from cloudflare_register.persistence import (
            load_interface_groups as legacy_load_groups,
        )
        from cloudflare_register.persistence import (
            save_interface_groups as legacy_save_groups,
        )

        with groups_mutation_lock():
            current = {g.name: g for g in legacy_load_groups()}
            current[group.name] = group
            legacy_save_groups(list(current.values()))
        _LOGGER.info(
            "registered interface group %s -> %s", group.name, group.interface_name or "<default>"
        )
        return group


def _migrate(legacy: LegacyHostConfig) -> HostConfig:
    """Re-hydrate a legacy HostConfig (storage model) into the domain model.

    Pydantic's ``model_validate`` does this for free; the helper exists only
    to provide a clear, single point of migration if the storage schema
    diverges from the domain schema later.
    """
    return HostConfig.model_validate(legacy.model_dump())
