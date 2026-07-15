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
"""Textual-based keyboard-driven dashboard.

Lives in the ``[tui]`` optional extras; the rest of the package does not
import textual, so installing headless is fine.

The screen shows:

* current public IPv4/IPv6 and detected interfaces
* the list of managed hosts grouped by interface group
* footer key hints (``q`` quit, ``s`` sync now)
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

from cloudflare_register.config import Settings
from cloudflare_register.logging_setup import get_logger
from cloudflare_register.services import HostService, InterfaceService, SyncService

_LOGGER = get_logger(__name__)


class CloudflareRegisterTUI:
    """Thin wrapper exposed to the CLI; delegates to a textual App when available."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.hosts = HostService()
        self.interfaces = InterfaceService()

    def run(self) -> None:
        try:
            from textual.app import App, ComposeResult
            from textual.containers import Horizontal, Vertical
            from textual.widgets import DataTable, Footer, Header, Static
        except ImportError as exc:
            raise RuntimeError(f"textual is not installed: {exc}") from exc

        outer = self

        class _TUIApp(App):  # noqa: N805 - inner class shadows outer self intentionally
            CSS_PATH = None
            BINDINGS = [
                ("q", "quit_app", "Quit"),
                ("s", "sync", "Sync now"),
                ("r", "refresh", "Refresh"),
            ]

            def compose(inner_self) -> ComposeResult:  # noqa: N805
                yield Header(show_clock=True)
                with Horizontal():
                    with Vertical():
                        yield Static(id="status", markup=True)
                        yield Static(id="interfaces", markup=True)
                        yield DataTable(id="hosts")
                    yield Static(id="log", markup=True)
                yield Footer()

            def on_mount(inner_self) -> None:  # noqa: N805
                hosts_table = inner_self.query_one("#hosts", DataTable)
                hosts_table.add_columns("group", "hostname", "zone", "proxied")
                inner_self.set_interval(5.0, inner_self.refresh_panels)
                inner_self.refresh_panels()

            async def action_sync(inner_self) -> None:  # noqa: N805
                from cloudflare_register.providers.factory import build as build_provider

                provider = build_provider(
                    outer.settings.dns_provider, token=outer.settings.cloudflare_api_token
                )
                service = SyncService(
                    host_service=outer.hosts,
                    interface_service=outer.interfaces,
                    provider=provider,
                    settings=outer.settings,
                )
                try:
                    report = await service.run_once()
                    for action in report.actions:
                        outer._log.append(action)  # noqa: SLF001 - inner TUI log buffer
                finally:
                    await provider.close()

            def action_refresh(inner_self) -> None:  # noqa: N805
                inner_self.refresh_panels()

            def refresh_panels(inner_self) -> None:  # noqa: N805
                outer.refresh_panels(inner_self)

        if not hasattr(self, "_log"):
            self._log: list[str] = []
        _TUIApp().run()

    def refresh_panels(self, app: object) -> None:  # pragma: no cover - UI path
        from textual.widgets import DataTable, Static

        hosts_table = app.query_one("#hosts", DataTable)
        hosts_table.clear()
        grouped: dict[str, list] = defaultdict(list)
        for host in self.hosts.list_hosts():
            grouped[host.interface_group or "(default)"].append(host)
        for group_name in sorted(grouped):
            for host in grouped[group_name]:
                hosts_table.add_row(
                    group_name, host.hostname, host.zone_name, "yes" if host.proxied else "no"
                )

        status_widget = app.query_one("#status", Static)
        ts = datetime.now(UTC).strftime("%H:%M:%SZ")
        total = len(self.hosts.list_hosts())
        groups = self.hosts.load_interface_groups()
        status_widget.update(
            f"[b]cloudflare-register[/b] {ts}\n"
            f"hosts: [cyan]{total}[/cyan]  groups: [cyan]{len(groups)}[/cyan]"
        )

        iface_widget = app.query_one("#interfaces", Static)
        iface_lines = ["[b]interfaces[/b]"]
        for line in self.interfaces.summary_lines():
            iface_lines.append(line)
        iface_widget.update("\n".join(iface_lines))

        log_widget = app.query_one("#log", Static)
        if not hasattr(self, "_log"):
            self._log = []
        log_widget.update("\n".join(self._log[-12:]) or "[dim]log empty[/dim]")
