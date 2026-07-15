# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, CloudBSD
"""Comprehensive web layer tests via FastAPI's TestClient.

Covers every authenticated route: dashboard, wizard, add-host, add-hosts-bulk,
register-group, delete-host, logout, /healthz, plus login, lockout, and CSRF
integration.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cloudflare_register.config import get_settings
from cloudflare_register.domain import HostConfig
from cloudflare_register.exceptions import ConfigError
from cloudflare_register.providers import factory as provider_factory
from cloudflare_register.providers.base import Provider
from cloudflare_register.web import csrf as csrf_module

ZONE = "abcdef0123456789abcdef0123456789"
ZONE_FORM_VALUE = f"{ZONE}:example.com"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    from cloudflare_register.config import reset_settings_cache
    from cloudflare_register.web.app import _create_app

    reset_settings_cache()
    return TestClient(_create_app())


def _login(client: TestClient, *, password: str = "very-secret-test-password") -> str:
    r = client.post(
        "/login",
        data={"username": "admin", "password": password},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    cookie_auth = client.cookies.get(csrf_module.SESSION_COOKIE)
    assert cookie_auth
    return f"{csrf_module.SESSION_COOKIE}={cookie_auth}"


def _csrf(client: TestClient) -> str:
    session = client.cookies.get(csrf_module.SESSION_COOKIE)
    assert session
    return csrf_module.token_for(get_settings().secret_key, session)


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "ts" in body


def test_login_get_renders_form(client):
    r = client.get("/login")
    assert r.status_code == 200
    assert "Login" in r.text
    assert 'name="username"' in r.text


def test_login_rejects_bad_password(client):
    r = client.post("/login", data={"username": "admin", "password": "wrong"})
    assert r.status_code == 401


def test_login_rejects_bad_username_with_correct_password(client):
    """The username is a credential factor — right password alone must fail."""
    r = client.post(
        "/login",
        data={"username": "not-admin", "password": "very-secret-test-password"},
    )
    assert r.status_code == 401


def test_login_rejects_bad_username_with_password_hash(tmp_path, monkeypatch):
    """Same, in the bcrypt-hash configuration (the production-recommended one)."""
    import bcrypt

    hashed = bcrypt.hashpw(b"very-secret-test-password", bcrypt.gensalt(rounds=4)).decode()
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", hashed)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    from cloudflare_register.config import reset_settings_cache
    from cloudflare_register.web.app import _create_app

    reset_settings_cache()
    client = TestClient(_create_app())

    bad = client.post(
        "/login",
        data={"username": "not-admin", "password": "very-secret-test-password"},
    )
    assert bad.status_code == 401
    good = client.post(
        "/login",
        data={"username": "admin", "password": "very-secret-test-password"},
        follow_redirects=False,
    )
    assert good.status_code == 303


def test_login_lockout_after_repeated_failures(client):
    for _ in range(5):
        r = client.post("/login", data={"username": "admin", "password": "wrong"})
        assert r.status_code == 401
    r = client.post("/login", data={"username": "admin", "password": "wrong"})
    assert r.status_code == 429
    # Even correct credentials are refused while locked out.
    r = client.post(
        "/login",
        data={"username": "admin", "password": "very-secret-test-password"},
    )
    assert r.status_code == 429


def test_create_app_refuses_insecure_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "change-me-to-a-random-48-byte-secret")
    monkeypatch.delenv("CLOUDFLARE_REGISTER_ALLOW_INSECURE_DEFAULTS", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    from cloudflare_register.config import reset_settings_cache
    from cloudflare_register.web.app import _create_app

    reset_settings_cache()
    with pytest.raises(ConfigError):
        _create_app()


def test_security_headers_present(client):
    r = client.get("/login")
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["cache-control"] == "no-store"


def test_vendored_stylesheet_served(client):
    r = client.get("/static/water.min.css")
    assert r.status_code == 200
    assert "background" in r.text


def test_dashboard_unauthenticated_redirects(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_dashboard_renders_empty(client):
    hdr = _login(client)
    r = client.get("/", headers={"cookie": hdr})
    assert r.status_code == 200
    assert "Managed hosts" in r.text
    assert "No hosts configured yet" in r.text


def test_dashboard_shows_groups_with_interface(client):
    from cloudflare_register.services import HostService

    service = HostService()
    service.add_host(
        HostConfig(
            hostname="a.example.com", zone_id=ZONE, zone_name="example.com", interface_group="wan"
        )
    )
    service.register_interface_group("wan", interface_name="eth0", description="uplink")

    hdr = _login(client)
    r = client.get("/", headers={"cookie": hdr})
    assert r.status_code == 200
    assert "wan" in r.text
    assert "eth0" in r.text
    assert "a.example.com" in r.text


def test_wizard_unauthenticated_redirects(client):
    r = client.get("/wizard", follow_redirects=False)
    assert r.status_code == 303


def test_wizard_renders(client):
    hdr = _login(client)
    r = client.get("/wizard", headers={"cookie": hdr})
    assert r.status_code == 200
    assert "Add host" in r.text
    assert "register a new interface group" in r.text


def test_add_host_success(client):
    hdr = _login(client)
    r = client.post(
        "/add-host",
        data={
            "hostname": "new.example.com",
            "zone": ZONE_FORM_VALUE,
            "interface_group": "wan",
            "proxied": "true",
            csrf_module.FORM_FIELD: _csrf(client),
        },
        headers={"cookie": hdr},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    from cloudflare_register.services import HostService

    assert HostService().get_host("new.example.com") is not None


def test_add_host_without_csrf_403(client):
    hdr = _login(client)
    r = client.post(
        "/add-host",
        data={"hostname": "x.example.com", "zone": ZONE_FORM_VALUE},
        headers={"cookie": hdr},
        follow_redirects=False,
    )
    assert r.status_code == 403
    from cloudflare_register.services import HostService

    assert HostService().get_host("x.example.com") is None


def test_add_host_duplicate_409(client):
    hdr = _login(client)
    data = {
        "hostname": "dup.example.com",
        "zone": ZONE_FORM_VALUE,
        csrf_module.FORM_FIELD: _csrf(client),
    }
    r1 = client.post("/add-host", data=data, headers={"cookie": hdr}, follow_redirects=False)
    assert r1.status_code == 303
    r2 = client.post("/add-host", data=data, headers={"cookie": hdr}, follow_redirects=False)
    assert r2.status_code == 409


def test_add_host_invalid_zone_id_400(client):
    hdr = _login(client)
    r = client.post(
        "/add-host",
        data={
            "hostname": "x.example.com",
            "zone": "short:example.com",
            csrf_module.FORM_FIELD: _csrf(client),
        },
        headers={"cookie": hdr},
        follow_redirects=False,
    )
    assert r.status_code == 400


def test_add_host_malformed_zone_400(client):
    hdr = _login(client)
    r = client.post(
        "/add-host",
        data={
            "hostname": "x.example.com",
            "zone": ZONE,  # missing ":<zone_name>" suffix
            csrf_module.FORM_FIELD: _csrf(client),
        },
        headers={"cookie": hdr},
        follow_redirects=False,
    )
    assert r.status_code == 400


def test_add_hosts_bulk_success(client):
    hdr = _login(client)
    r = client.post(
        "/add-hosts-bulk",
        data={
            "hostnames": "a.example.com\nb.example.com\n\nc.example.com",
            "zone": ZONE_FORM_VALUE,
            "interface_group": "wan",
            csrf_module.FORM_FIELD: _csrf(client),
        },
        headers={"cookie": hdr},
        follow_redirects=False,
    )
    assert r.status_code == 303
    from cloudflare_register.services import HostService

    svc = HostService()
    assert svc.get_host("a.example.com") is not None
    assert svc.get_host("c.example.com") is not None


def test_delete_host_success(client):
    hdr = _login(client)
    client.post(
        "/add-host",
        data={
            "hostname": "bye.example.com",
            "zone": ZONE_FORM_VALUE,
            csrf_module.FORM_FIELD: _csrf(client),
        },
        headers={"cookie": hdr},
        follow_redirects=False,
    )
    r = client.post(
        "/delete-host",
        data={"hostname": "bye.example.com", csrf_module.FORM_FIELD: _csrf(client)},
        headers={"cookie": hdr},
        follow_redirects=False,
    )
    assert r.status_code == 303
    from cloudflare_register.services import HostService

    assert HostService().get_host("bye.example.com") is None


def test_delete_host_missing_404(client):
    hdr = _login(client)
    r = client.post(
        "/delete-host",
        data={"hostname": "never.example.com", csrf_module.FORM_FIELD: _csrf(client)},
        headers={"cookie": hdr},
        follow_redirects=False,
    )
    assert r.status_code == 404


def test_register_group_success(client):
    hdr = _login(client)
    r = client.post(
        "/register-group",
        data={
            "name": "vpn-tunnel",
            "interface_name": "wg0",
            "description": "wireguard",
            csrf_module.FORM_FIELD: _csrf(client),
        },
        headers={"cookie": hdr},
        follow_redirects=False,
    )
    assert r.status_code == 303
    from cloudflare_register.services import HostService

    groups = {g.name: g for g in HostService().load_interface_groups()}
    assert "vpn-tunnel" in groups
    assert groups["vpn-tunnel"].interface_name == "wg0"


def test_register_group_invalid_name_400(client):
    hdr = _login(client)
    r = client.post(
        "/register-group",
        data={"name": "bad name with spaces", csrf_module.FORM_FIELD: _csrf(client)},
        headers={"cookie": hdr},
        follow_redirects=False,
    )
    assert r.status_code == 400


def test_wizard_zone_renders_zones(tmp_path, monkeypatch):
    """Use a per-test fixture pattern: set DNS_PROVIDER BEFORE the client fixture."""

    class _FakeProvider(Provider):
        name = "fake"

        def __init__(self, token: str, **kwargs) -> None:
            self._token = token

        async def list_zones(self):
            return [{"id": ZONE, "name": "example.com"}]

        async def list_records(self, zone_id, name):
            return []

        async def create_record(self, *args, **kwargs):
            raise NotImplementedError

        async def update_record(self, *args, **kwargs):
            raise NotImplementedError

        async def delete_record(self, *args, **kwargs):
            raise NotImplementedError

        async def close(self):
            pass

    provider_factory.register("fake", _FakeProvider)
    monkeypatch.setenv("DNS_PROVIDER", "fake")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    from cloudflare_register.config import reset_settings_cache
    from cloudflare_register.web.app import _create_app

    reset_settings_cache()
    client = TestClient(_create_app())

    hdr = _login(client)
    r = client.post(
        "/wizard/zone",
        data={csrf_module.FORM_FIELD: _csrf(client)},
        headers={"cookie": hdr},
    )
    assert r.status_code == 200
    assert "example.com" in r.text
    # The zone select now carries "<id>:<name>" so add-host gets both parts.
    assert f'value="{ZONE}:example.com"' in r.text


def test_logout_clears_cookies_and_invalidates_sessions(client):
    hdr = _login(client)
    r = client.post(
        "/logout",
        data={csrf_module.FORM_FIELD: _csrf(client)},
        headers={"cookie": hdr},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/login"
    # The old (pre-logout) token must no longer grant access.
    r = client.get("/", headers={"cookie": hdr}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_logout_without_csrf_403(client):
    hdr = _login(client)
    r = client.post("/logout", headers={"cookie": hdr}, follow_redirects=False)
    assert r.status_code == 403
    # Session must still be alive: the forced-logout attempt was rejected.
    r = client.get("/", headers={"cookie": hdr})
    assert r.status_code == 200


def test_authenticated_route_with_bad_jwt_redirects(client):
    r = client.get(
        "/",
        headers={"cookie": f"{csrf_module.SESSION_COOKIE}=invalid"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/login"
