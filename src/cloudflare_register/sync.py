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
"""Backward-compatible facade over :mod:`cloudflare_register.services.sync_service`.

Older callers (tests, ad-hoc scripts) import ``reconcile_host`` and
``run_sync_once`` from this module. The new home is
:class:`cloudflare_register.services.SyncService`; this module re-exports
its symbols so existing import paths keep working.
"""

from __future__ import annotations

from datetime import UTC, datetime

from cloudflare_register.config import Settings, get_settings
from cloudflare_register.domain import HostConfig
from cloudflare_register.providers.base import Provider
from cloudflare_register.services.host_service import HostService
from cloudflare_register.services.interface_service import InterfaceService
from cloudflare_register.services.sync_service import (
    UNBOUNDED,
    SyncService,
    reconcile_host,
)

__all__ = [
    "reconcile_host",
    "summarize_state",
    "run_sync_once",
    "sync_forever",
    "cleanup_orphans",
    "SyncService",
    "UNBOUNDED",
]


def summarize_state(hosts: list[HostConfig], ipv4: str | None, ipv6: str | None) -> str:
    """One-line status summary used by CLI --check-config and the TUI."""
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    parts = [f"ipv4={ipv4 or 'none'}", f"ipv6={ipv6 or 'none'}", f"hosts={len(hosts)}"]
    return f"[{ts}] " + " | ".join(parts)


def _legacy_service(settings: Settings | None = None) -> SyncService:
    """Build a SyncService wired to the configured provider."""
    active = settings or get_settings()
    from cloudflare_register.providers.factory import build as build_provider

    provider = build_provider(active.dns_provider, token=active.cloudflare_api_token)
    return SyncService(
        host_service=HostService(),
        interface_service=InterfaceService(),
        provider=provider,
        settings=active,
    )


async def run_sync_once(
    provider: Provider,
    settings: Settings | None = None,
    *,
    hosts: list[HostConfig] | None = None,
) -> tuple[list[str], list[str]]:
    """Deprecated single-call facade.

    Returns ``(errors, actions)`` for compatibility with tests.
    Prefer ``SyncService.run_once()`` in new code.
    """
    service = SyncService(
        host_service=HostService(),
        interface_service=InterfaceService(),
        provider=provider,
        settings=settings,
    )
    report = await service.run_once()
    if hosts is not None:
        _ = hosts  # accepted for backward compatibility; SyncService reads from HostService
    return report.errors, report.actions


async def sync_forever(provider: Provider, settings: Settings | None = None) -> None:
    """Deprecated loop facade. Use ``SyncService.run_forever()``."""
    service = SyncService(
        host_service=HostService(),
        interface_service=InterfaceService(),
        provider=provider,
        settings=settings,
    )
    await service.run_forever()


async def cleanup_orphans(provider: Provider, dry_run: bool = True) -> list[str]:
    raise NotImplementedError("cleanup_orphans is a planned post-1.0 feature")
