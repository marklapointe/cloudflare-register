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
"""Top-level CLI for cloudflare-register.

Subcommands:

* ``init``         - generate a strong ``.env`` and XDG directories.
* ``check-config`` - validate settings and exit non-zero on failure.
* ``sync``         - run the sync loop once and exit (cron-friendly).
* ``service``      - run the full web UI + sync loop as a foreground process.
* ``tui``          - launch the Textual dashboard.
* ``web``          - run the FastAPI app only (no background sync).

Each subcommand is a thin Click controller: it parses arguments, sets up
logging, constructs the relevant service(s), and delegates.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import secrets
import stat
import sys
from pathlib import Path

import click

from cloudflare_register import __version__
from cloudflare_register.config import (
    get_settings,
    require_safe_settings,
    reset_settings_cache,
)
from cloudflare_register.exceptions import ConfigError, ProviderError
from cloudflare_register.logging_setup import get_logger
from cloudflare_register.logging_setup import setup as setup_logging
from cloudflare_register.providers.factory import build as build_provider
from cloudflare_register.providers.factory import known
from cloudflare_register.services import HostService, InterfaceService, SyncService

_LOGGER = get_logger("cli")

_PROVIDER_TOKEN_HINTS = {
    "cloudflare": "CLOUDFLARE_API_TOKEN",
}


def _print_error(message: str) -> None:
    click.echo(click.style(message, fg="red", bold=True), err=True)


def _chmod_0600(path: Path) -> None:
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def _build_sync_service() -> SyncService:
    """Compose a SyncService with the configured provider and settings."""
    settings = get_settings()
    provider = build_provider(settings.dns_provider, token=settings.cloudflare_api_token)
    return SyncService(
        host_service=HostService(),
        interface_service=InterfaceService(),
        provider=provider,
        settings=settings,
    )


@click.group(context_settings={"help_option_names": ["-h", "--help"]}, name="cloudflare-register")
@click.version_option(__version__, "-V", "--version")
@click.option("--log-level", default=None, help="DEBUG, INFO, WARNING, or ERROR.")
def main(log_level: str | None) -> None:
    """Smart DynDNS service for Cloudflare."""


@main.command("init")
@click.option(
    "--system",
    "write_system",
    is_flag=True,
    help="Write to /etc/cloudflare-register.json (root required).",
)
@click.option(
    "--path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Override the destination path (default: per-user XDG config file).",
)
@click.option("--force", is_flag=True, help="Overwrite an existing file.")
def cmd_init(write_system: bool, path: Path | None, force: bool) -> None:
    """Generate a fresh config with sane defaults and a strong secret.

    Default destination: ``$XDG_CONFIG_HOME/cloudflare_register/config.json``
    (or ``~/.config/cloudflare_register/config.json``). Use ``--system`` to
    write to ``/etc/cloudflare-register.json`` instead — for production
    deployments behind systemd or rc.d.

    Output is JSON (per Honcho application guidelines: "JSON is the preferred
    config format for machine interfaces").
    """
    if write_system and path is not None:
        _print_error("--system and --path are mutually exclusive")
        sys.exit(2)
    destination: Path
    if write_system:
        destination = Path("/etc/cloudflare-register.json")
    elif path is not None:
        destination = path
    else:
        raw = os.environ.get("XDG_CONFIG_HOME")
        base = Path(raw).expanduser() if raw else Path.home() / ".config"
        destination = base / "cloudflare_register" / "config.json"

    if destination.exists() and not force:
        _print_error(f"{destination} already exists; pass --force to overwrite.")
        sys.exit(2)

    new_secret = secrets.token_urlsafe(48)
    new_password = secrets.token_urlsafe(24)
    new_password_hash = _bcrypt_hash(new_password)

    body = json.dumps(
        {
            "_comment_format": "JSON config (see Honcho guidelines: JSON is preferred).",
            "_comment_path": f"Generated by cloudflare-register init. Mode 0600.",
            "_comment_password_rotation": (
                "python3 -c 'import bcrypt; "
                "print(bcrypt.hashpw(b\"NEW\", bcrypt.gensalt(rounds=12)).decode())'"
            ),
            "dns_provider": "cloudflare",
            "cloudflare_api_token": "replace_me",
            "secret_key": new_secret,
            "admin_username": "admin",
            "admin_password_hash": new_password_hash,
            "access_token_expire_minutes": 60,
            "cookie_secure": False,
            "http_host": "127.0.0.1",
            "http_port": 8000,
            "sync_interval_seconds": 300,
            "log_level": "INFO",
        },
        indent=2,
        sort_keys=True,
    )
    if write_system:
        _write_system_config(destination, body)
        click.echo(f"wrote {destination} (mode 0600, owner root:root)")
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(body, encoding="utf-8")
        _chmod_0600(destination)
        click.echo(f"wrote {destination} (mode 0600)")
    click.echo("Plaintext admin password (save to your password manager NOW):")
    click.echo(f"    {new_password}")
    click.echo("rotate ADMIN_PASSWORD via your editor before first run.")


def _bcrypt_hash(password: str) -> str:
    import bcrypt

    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode()


def _write_system_config(path: Path, body: str) -> None:
    """Write /etc/cloudflare-register.json using sudo. Idempotent."""
    import subprocess

    result = subprocess.run(
        ["/bin/sh", "-c", f"cat > {path} <<'CONF'\n{body}CONF"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"failed to write {path}: {result.stderr}")
    subprocess.run(["sudo", "chown", "root:root", str(path)], check=True)
    subprocess.run(["sudo", "chmod", "0600", str(path)], check=True)


@main.command("check-config")
@click.pass_context
def cmd_check_config(ctx: click.Context) -> None:
    """Validate settings, DNS provider reachability, and persistent storage."""
    log_level = ctx.parent.params.get("log_level") if ctx.parent else None
    setup_logging(log_level)
    try:
        settings = require_safe_settings()
    except ConfigError as exc:
        _print_error(str(exc))
        sys.exit(2)

    problems = settings.unsafe_defaults_in_use()
    if problems:
        click.echo(click.style("Warning: insecure defaults still in use: ", fg="yellow"), nl=False)
        click.echo(", ".join(problems))

    host_service = HostService()
    hosts = host_service.list_hosts()
    interfaces = InterfaceService()
    groups = host_service.load_interface_groups()

    click.echo(f"data_dir:        {settings.data_dir}")
    click.echo(f"config_dir:      {settings.config_dir}")
    click.echo(f"http_listen:     {settings.http_host}:{settings.http_port}")
    click.echo(f"hosts_managed:   {len(hosts)}")
    click.echo(f"groups:          {', '.join(g.name for g in groups) or '<none>'}")
    click.echo(f"interfaces:      {len(interfaces.list_interfaces())}")
    click.echo(f"provider_known:  {', '.join(known())}")

    token_env = _PROVIDER_TOKEN_HINTS.get(settings.dns_provider, "API_TOKEN")
    if settings.cloudflare_api_token.startswith("replace_me"):
        _print_error(f"{token_env} is unset; cloudflare lookups will fail.")
        sys.exit(3)

    click.echo("config OK")


@main.command("sync")
@click.option(
    "--once/--loop", default=True, show_default=True, help="Run cycles forever instead of once."
)
@click.option(
    "--group",
    "group_filter",
    default=None,
    help="Only reconcile hosts in this interface group.",
)
@click.pass_context
def cmd_sync(ctx: click.Context, once: bool, group_filter: str | None) -> None:
    """Run the synchronization loop. Use ``--loop`` for background daemon mode."""
    log_level = ctx.parent.params.get("log_level") if ctx.parent else None
    setup_logging(log_level)
    try:
        require_safe_settings()
    except ConfigError as exc:
        _print_error(str(exc))
        sys.exit(2)

    async def _runner() -> int:
        service = _build_sync_service()
        try:
            if once:
                report = await service.run_once(group_filter=group_filter)
                for action in report.actions:
                    click.echo(action)
                for error in report.errors:
                    click.echo(click.style(error, fg="red"))
                return 0 if not report.errors else 1
            await service.run_forever()
            return 0
        finally:
            await service._provider.close()  # noqa: SLF001 - service owns provider lifetime

    sys.exit(asyncio.run(_runner()))


@main.command("interfaces")
@click.pass_context
def cmd_interfaces(ctx: click.Context) -> None:
    """List detected network interfaces and the OS default route."""
    log_level = ctx.parent.params.get("log_level") if ctx.parent else None
    setup_logging(log_level)
    service = InterfaceService()
    for line in service.summary_lines():
        click.echo(line)


@main.command("hosts")
@click.option("--group", "group_filter", default=None, help="Filter to one interface group.")
@click.pass_context
def cmd_hosts(ctx: click.Context, group_filter: str | None) -> None:
    """List managed hosts grouped by interface group."""
    setup_logging(ctx.parent.params.get("log_level") if ctx.parent else None)
    service = HostService()
    hosts = service.list_hosts()
    if group_filter:
        hosts = [h for h in hosts if h.interface_group == group_filter.lower()]
    if not hosts:
        click.echo("no hosts managed")
        return
    for host in hosts:
        group = host.interface_group or "-"
        click.echo(
            f"{host.hostname:<40} zone={host.zone_name} group={group:<20} proxied={host.proxied}"
        )


@main.command("service")
@click.pass_context
def cmd_service(ctx: click.Context) -> None:
    """Run web UI + sync loop in one foreground process. Stop with SIGTERM."""
    log_level = ctx.parent.params.get("log_level") if ctx.parent else None
    setup_logging(log_level)
    try:
        import uvicorn  # local import keeps `cloudflare-register init` light.

        from cloudflare_register.web.app import app
    except ImportError as exc:
        _print_error(f"web extras not installed: {exc}")
        sys.exit(2)

    settings = get_settings()
    try:
        service = _build_sync_service()
    except (ConfigError, ProviderError) as exc:
        _print_error(str(exc))
        sys.exit(2)

    async def _main() -> None:
        runner = uvicorn.Server(
            uvicorn.Config(
                app,
                host=settings.http_host,
                port=settings.http_port,
                log_level=(log_level or "info").lower(),
                access_log=False,
            )
        )
        sync_task = asyncio.create_task(service.run_forever())
        try:
            await runner.serve()
        finally:
            sync_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sync_task
            await service._provider.close()  # noqa: SLF001

    asyncio.run(_main())


@main.command("web")
@click.pass_context
def cmd_web(ctx: click.Context) -> None:
    """Run only the FastAPI web UI (no background sync)."""
    log_level = ctx.parent.params.get("log_level") if ctx.parent else None
    setup_logging(log_level)
    import uvicorn

    from cloudflare_register.web.app import app

    settings = get_settings()
    uvicorn.run(
        app,
        host=settings.http_host,
        port=settings.http_port,
        log_level=(log_level or "info").lower(),
    )


@main.command("tui")
@click.pass_context
def cmd_tui(ctx: click.Context) -> None:
    """Launch the keyboard-driven Textual dashboard."""
    log_level = ctx.parent.params.get("log_level") if ctx.parent else None
    setup_logging(log_level)
    try:
        from cloudflare_register.tui.app import CloudflareRegisterTUI
    except ImportError as exc:
        _print_error(f"TUI extras not installed: {exc}; pip install 'cloudflare-register[tui]'")
        sys.exit(2)
    settings = require_safe_settings()
    CloudflareRegisterTUI(settings).run()


def sync_once() -> None:
    """Console-script entry point (``cr-sync``) — equivalent to ``cloudflare-register sync``."""
    sys.argv = ["cr-sync", "sync", "--once"]
    main(obj={})


if __name__ == "__main__":
    main(obj={})
