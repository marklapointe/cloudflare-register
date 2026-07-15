# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, CloudBSD
"""CLI integration tests using Click's CliRunner.

Exercises each subcommand in-process to push coverage of ``cli.py`` past the
80% gate. Mocks the DNS provider and IP discovery where they would otherwise
require network access.
"""

from __future__ import annotations

import contextlib
import json
from typing import Any

import pytest
from click.testing import CliRunner

from cloudflare_register.cli import main
from cloudflare_register.domain import HostConfig
from cloudflare_register.providers import factory as provider_factory
from cloudflare_register.providers.base import DnsRecord, Provider

ZONE = "abcdef0123456789abcdef0123456789"


class _CapturingProvider(Provider):
    name = "capturing"

    def __init__(self, token: str, **kwargs: Any) -> None:
        self.token = token
        self.created: list[tuple[str, str, str, str, bool]] = []
        self.updated: list[tuple[str, str, str, str, str, bool]] = []
        self.deleted: list[tuple[str, str]] = []
        self.zones: list[dict[str, str]] = [
            {"id": ZONE, "name": "example.com"},
            {"id": "f" * 32, "name": "example.net"},
        ]

    async def list_zones(self):
        return list(self.zones)

    async def list_records(self, zone_id, name):
        return []

    async def create_record(self, zone_id, record_type, name, content, proxied=False, *, ttl=1):
        self.created.append((zone_id, record_type, name, content, proxied))
        return DnsRecord(
            record_id=f"new-{len(self.created)}",
            record_type=record_type,
            name=name,
            content=content,
            proxied=proxied,
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
        )

    async def delete_record(self, zone_id, record_id):
        self.deleted.append((zone_id, record_id))

    async def close(self):
        pass


@pytest.fixture
def capturing_provider(monkeypatch):
    provider_factory.register("capturing", _CapturingProvider)
    monkeypatch.setenv("DNS_PROVIDER", "capturing")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-token-1234567890abcdef")
    return _CapturingProvider


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_help_prints_subcommands(runner):
    r = runner.invoke(main, ["--help"])
    assert r.exit_code == 0
    assert "check-config" in r.output
    assert "init" in r.output
    assert "sync" in r.output
    assert "service" in r.output
    assert "tui" in r.output
    assert "web" in r.output
    assert "hosts" in r.output
    assert "interfaces" in r.output


def test_version_prints(runner):
    r = runner.invoke(main, ["--version"])
    assert r.exit_code == 0


def test_check_config_success(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "real-token-here")
    monkeypatch.setenv("SECRET_KEY", "x" * 48)
    monkeypatch.setenv("ADMIN_PASSWORD", "very-secret-test-password")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from cloudflare_register.config import reset_settings_cache

    reset_settings_cache()
    r = runner.invoke(main, ["check-config"])
    assert "config OK" in r.output


def test_check_config_insecure_warns(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "change-me-to-a-random-48-byte-secret")
    monkeypatch.setenv("SECRET_KEY", "change-me-to-a-random-48-byte-secret")
    monkeypatch.setenv("ADMIN_PASSWORD", "change-me")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from cloudflare_register.config import reset_settings_cache

    reset_settings_cache()
    r = runner.invoke(main, ["check-config"])
    assert "insecure defaults" in r.output


def test_init_creates_user_config(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    r = runner.invoke(main, ["init"])
    assert r.exit_code == 0
    config_file = tmp_path / "cloudflare_register" / "config.json"
    assert config_file.exists()
    assert (config_file.stat().st_mode & 0o777) == 0o600
    body = json.loads(config_file.read_text())
    assert body["dns_provider"] == "cloudflare"
    assert "secret_key" in body
    assert "admin_password_hash" in body


def test_init_with_existing_file_errors(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config_dir = tmp_path / "cloudflare_register"
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text("{}")
    r = runner.invoke(main, ["init"])
    assert r.exit_code == 2
    assert "already exists" in r.output


def test_init_with_force_overwrites(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config_dir = tmp_path / "cloudflare_register"
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text("{}")
    r = runner.invoke(main, ["init", "--force"])
    assert r.exit_code == 0
    body = json.loads((config_dir / "config.json").read_text())
    assert "secret_key" in body


def test_init_with_path(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    target = tmp_path / "custom.conf"
    r = runner.invoke(main, ["init", "--path", str(target)])
    assert r.exit_code == 0
    assert target.exists()


def test_init_system_and_path_conflict(runner, tmp_path):
    """--system and --path are mutually exclusive."""
    r = runner.invoke(main, ["init", "--system", "--path", str(tmp_path / "target.json")])
    assert r.exit_code == 2
    assert "mutually exclusive" in r.output


def test_init_system_creates_system_file(monkeypatch, runner, tmp_path):
    """--system writes the system config path with mode 0600.

    The destination is redirected into ``tmp_path`` — tests must never
    touch the real ``/etc``.
    """
    target = tmp_path / "etc" / "cloudflare-register.json"
    target.parent.mkdir()
    monkeypatch.setattr("cloudflare_register.cli.SYSTEM_CONFIG_PATH", target)
    r = runner.invoke(main, ["init", "--system"])
    assert r.exit_code == 0, r.output
    assert target.exists()
    assert (target.stat().st_mode & 0o777) == 0o600
    body = json.loads(target.read_text())
    assert "secret_key" in body


def test_init_system_existing_file_requires_force(monkeypatch, runner, tmp_path):
    target = tmp_path / "cloudflare-register.json"
    target.write_text("{}")
    monkeypatch.setattr("cloudflare_register.cli.SYSTEM_CONFIG_PATH", target)
    r = runner.invoke(main, ["init", "--system"])
    assert r.exit_code == 2
    assert "already exists" in r.output
    assert target.read_text() == "{}"


def test_hosts_empty(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "x" * 48)
    monkeypatch.setenv("SECRET_KEY", "y" * 48)
    monkeypatch.setenv("ADMIN_PASSWORD", "very-secret-test-password")
    from cloudflare_register.config import reset_settings_cache

    reset_settings_cache()
    r = runner.invoke(main, ["hosts"])
    assert "no hosts managed" in r.output


def test_hosts_lists_hosts(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "x" * 48)
    monkeypatch.setenv("SECRET_KEY", "y" * 48)
    monkeypatch.setenv("ADMIN_PASSWORD", "very-secret-test-password")
    from cloudflare_register.config import reset_settings_cache

    reset_settings_cache()
    from cloudflare_register.services import HostService

    HostService().add_host(
        HostConfig(
            hostname="a.example.com",
            zone_id=ZONE,
            zone_name="example.com",
            interface_group="wan",
        )
    )
    r = runner.invoke(main, ["hosts"])
    assert "a.example.com" in r.output
    assert "wan" in r.output


def test_hosts_with_group_filter(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "x" * 48)
    monkeypatch.setenv("SECRET_KEY", "y" * 48)
    monkeypatch.setenv("ADMIN_PASSWORD", "very-secret-test-password")
    from cloudflare_register.config import reset_settings_cache

    reset_settings_cache()
    from cloudflare_register.services import HostService

    svc = HostService()
    svc.add_host(
        HostConfig(
            hostname="a.example.com", zone_id=ZONE, zone_name="example.com", interface_group="wan"
        )
    )
    svc.add_host(
        HostConfig(
            hostname="b.example.com", zone_id=ZONE, zone_name="example.com", interface_group="vpn"
        )
    )
    r = runner.invoke(main, ["hosts", "--group", "wan"])
    assert "a.example.com" in r.output
    assert "b.example.com" not in r.output


def test_interfaces_command(runner):
    r = runner.invoke(main, ["interfaces"])
    assert r.exit_code == 0
    assert "default route" in r.output


def test_sync_once_success(runner, capturing_provider, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("SECRET_KEY", "x" * 48)
    monkeypatch.setenv("ADMIN_PASSWORD", "very-secret-test-password")
    from cloudflare_register.config import reset_settings_cache

    reset_settings_cache()
    from cloudflare_register.services import HostService

    HostService().add_host(
        HostConfig(hostname="a.example.com", zone_id=ZONE, zone_name="example.com")
    )

    async def _v4(source_ip=None):
        return "203.0.113.10"

    async def _v6(source_ip=None):
        return None

    monkeypatch.setattr("cloudflare_register.services.sync_service.get_public_ipv4", _v4)
    monkeypatch.setattr("cloudflare_register.services.sync_service.get_public_ipv6", _v6)

    r = runner.invoke(main, ["sync", "--once"])
    assert r.exit_code == 0
    assert "created A" in r.output


def test_sync_with_group_filter(runner, capturing_provider, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("SECRET_KEY", "x" * 48)
    monkeypatch.setenv("ADMIN_PASSWORD", "very-secret-test-password")
    from cloudflare_register.config import reset_settings_cache

    reset_settings_cache()
    from cloudflare_register.services import HostService

    svc = HostService()
    svc.add_host(
        HostConfig(
            hostname="a.example.com", zone_id=ZONE, zone_name="example.com", interface_group="wan"
        )
    )
    svc.add_host(
        HostConfig(
            hostname="b.example.com", zone_id=ZONE, zone_name="example.com", interface_group="vpn"
        )
    )

    async def _v4(source_ip=None):
        return "203.0.113.10"

    async def _v6(source_ip=None):
        return None

    monkeypatch.setattr("cloudflare_register.services.sync_service.get_public_ipv4", _v4)
    monkeypatch.setattr("cloudflare_register.services.sync_service.get_public_ipv6", _v6)

    r = runner.invoke(main, ["sync", "--once", "--group", "wan"])
    assert r.exit_code == 0


def test_sync_no_hosts_exits_zero(runner, tmp_path, monkeypatch, capturing_provider):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("SECRET_KEY", "x" * 48)
    monkeypatch.setenv("ADMIN_PASSWORD", "very-secret-test-password")
    from cloudflare_register.config import reset_settings_cache

    reset_settings_cache()
    r = runner.invoke(main, ["sync", "--once"])
    # No hosts configured → empty cycle → exit 0.
    assert r.exit_code == 0


def test_service_command_invokes_uvicorn(runner, tmp_path, monkeypatch):
    """The `service` command starts uvicorn + sync loop. Both block, so we
    monkeypatch them out and verify the wiring."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "x" * 48)
    monkeypatch.setenv("SECRET_KEY", "y" * 48)
    monkeypatch.setenv("ADMIN_PASSWORD", "very-secret-test-password")
    from cloudflare_register.config import reset_settings_cache

    reset_settings_cache()

    import uvicorn

    server_calls: list[dict] = []

    class FakeServer:
        def __init__(self, config):
            self.config = config
            server_calls.append({"config": config})

        async def serve(self):
            raise SystemExit(0)

    monkeypatch.setattr(uvicorn, "Server", FakeServer)
    sync_started = []

    def fake_run_forever(self):
        async def _coro():
            sync_started.append(True)
            raise SystemExit(0)

        return _coro()

    from cloudflare_register.services import SyncService

    monkeypatch.setattr(SyncService, "run_forever", fake_run_forever)

    try:
        r = runner.invoke(main, ["service"])
        assert r.exit_code in (0, 1)
    except SystemExit:
        pass
    assert len(server_calls) == 1


def test_web_command_invokes_uvicorn(runner, tmp_path, monkeypatch):
    """The `web` command is supposed to call uvicorn.run; we monkeypatch that
    out so the test doesn't bind a port."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "x" * 48)
    monkeypatch.setenv("SECRET_KEY", "y" * 48)
    monkeypatch.setenv("ADMIN_PASSWORD", "very-secret-test-password")
    from cloudflare_register.config import reset_settings_cache

    reset_settings_cache()
    import uvicorn

    captured = {}

    def fake_run(app, **kwargs):
        captured["called"] = True
        captured["kwargs"] = kwargs

    monkeypatch.setattr(uvicorn, "run", fake_run)
    r = runner.invoke(main, ["web"])
    assert r.exit_code == 0
    assert captured.get("called") is True


def test_tui_command_runs_or_errors_on_import(monkeypatch, runner, tmp_path):
    """The TUI's `run()` blocks inside Textual. We monkeypatch the App.run
    to exit immediately to verify the wiring without blocking."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "x" * 48)
    monkeypatch.setenv("SECRET_KEY", "y" * 48)
    monkeypatch.setenv("ADMIN_PASSWORD", "very-secret-test-password")
    from cloudflare_register.config import reset_settings_cache

    reset_settings_cache()

    from cloudflare_register.tui import app as tui_app_module

    called = []

    def fake_run(self):
        called.append(self)
        raise SystemExit(0)

    monkeypatch.setattr(tui_app_module.CloudflareRegisterTUI, "run", fake_run)
    with contextlib.suppress(SystemExit):
        runner.invoke(main, ["tui"])
    assert len(called) == 1
