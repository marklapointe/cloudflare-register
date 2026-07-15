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
"""FastAPI web UI for cloudflare-register.

Routes (all but ``/healthz`` and ``/login*`` require auth):

* ``GET  /``              - dashboard listing managed hosts grouped by interface.
* ``GET  /login``         - login form.
* ``POST /login``         - exchange credentials for a session cookie.
* ``POST /logout``        - invalidate all sessions and clear the cookie.
* ``GET  /wizard``        - add-host wizard (with interface selector).
* ``POST /wizard/zone``   - fetch available Cloudflare zones.
* ``POST /add-host``      - persist a single new host.
* ``POST /add-hosts-bulk``- persist many hostnames sharing one interface group.
* ``POST /delete-host``   - remove a managed host.
* ``GET  /healthz``       - unauthenticated liveness probe.

All persistence is delegated to :class:`HostService` and :class:`InterfaceService`;
this module is a thin controller.

The application is built lazily via :func:`get_application` so that importing
this module never touches settings; construction enforces
:func:`require_safe_settings` and refuses to serve on placeholder secrets.
"""

from __future__ import annotations

import asyncio
import hmac
import time
import uuid
from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import bcrypt
import jwt
from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from cloudflare_register.config import Settings, get_settings, require_safe_settings
from cloudflare_register.domain import HostConfig
from cloudflare_register.exceptions import PersistenceError, ProviderError
from cloudflare_register.logging_setup import get_logger
from cloudflare_register.providers.factory import build as build_provider
from cloudflare_register.services import HostService, InterfaceService
from cloudflare_register.web import csrf as csrf_module

_LOGGER = get_logger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"
templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))

SESSION_COOKIE = csrf_module.SESSION_COOKIE

# Failed-login throttling: after _MAX_LOGIN_FAILURES consecutive failures
# from one address, reject with 429 until _LOCKOUT_SECONDS elapse. Every
# failure also pays _FAILURE_DELAY so brute force can't run at line rate
# and both authenticate() branches present similar timing.
_MAX_LOGIN_FAILURES = 5
_LOCKOUT_SECONDS = 300.0
_FAILURE_DELAY = 0.3

_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
    ),
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


def _create_app(settings: Settings | None = None) -> FastAPI:
    active = require_safe_settings(settings or get_settings())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        _LOGGER.info("web ui ready; http=%s:%d", active.http_host, active.http_port)
        yield

    app = FastAPI(
        title="cloudflare-register",
        version="0.2.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = active
    app.state.hosts = HostService()
    app.state.interfaces = InterfaceService()
    # Bumped on logout: every issued token carries the generation it was
    # minted under, so logout invalidates all outstanding sessions (this is
    # a single-admin tool; per-session revocation would be overkill).
    app.state.session_generation = 0
    # source ip -> (consecutive failures, monotonic time of last failure)
    app.state.login_failures = {}

    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        for name, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        if not request.url.path.startswith(("/static", "/healthz")):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    async def authenticate(username: str, password: str) -> bool:
        # Evaluate both factors unconditionally (no short-circuit) so failure
        # timing does not reveal which factor was wrong.
        user_ok = hmac.compare_digest(
            username.encode("utf-8"), active.admin_username.encode("utf-8")
        )
        if active.admin_password_hash:
            try:
                password_ok = bcrypt.checkpw(
                    password.encode("utf-8"), active.admin_password_hash.encode("utf-8")
                )
            except ValueError:
                password_ok = False
        else:
            password_ok = hmac.compare_digest(
                password.encode("utf-8"), active.admin_password.encode("utf-8")
            )
        return user_ok and password_ok

    def _client_ip(request: Request) -> str:
        return request.client.host if request.client else "unknown"

    def _locked_out(ip: str) -> bool:
        entry = app.state.login_failures.get(ip)
        if entry is None:
            return False
        count, last_failure = entry
        if count < _MAX_LOGIN_FAILURES:
            return False
        if time.monotonic() - last_failure > _LOCKOUT_SECONDS:
            del app.state.login_failures[ip]
            return False
        return True

    def _record_failure(ip: str) -> None:
        count, _ = app.state.login_failures.get(ip, (0, 0.0))
        app.state.login_failures[ip] = (count + 1, time.monotonic())

    def _create_token(subject: str) -> str:
        now = datetime.now(UTC)
        expire = now + timedelta(minutes=active.access_token_expire_minutes)
        claims = {
            "sub": subject,
            "iat": now,
            "exp": expire,
            "jti": uuid.uuid4().hex,
            "gen": app.state.session_generation,
        }
        return jwt.encode(claims, active.secret_key, algorithm="HS256")

    def _attach_session_cookie(response: RedirectResponse, jwt_value: str) -> None:
        response.set_cookie(
            SESSION_COOKIE,
            jwt_value,
            httponly=True,
            secure=active.cookie_secure,
            samesite="lax",
            max_age=active.access_token_expire_minutes * 60,
            path="/",
        )

    def _login_redirect() -> HTTPException:
        return HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})

    async def get_current_user(request: Request) -> str:
        token = request.cookies.get(SESSION_COOKIE)
        if not token:
            raise _login_redirect()
        try:
            payload = jwt.decode(
                token,
                active.secret_key,
                algorithms=["HS256"],
                options={"require": ["exp", "sub"]},
            )
        except jwt.PyJWTError as exc:
            _LOGGER.info("rejected session: %s", exc)
            raise _login_redirect() from exc
        if payload.get("gen") != app.state.session_generation:
            raise _login_redirect()
        subject = payload.get("sub") or ""
        if not subject:
            raise _login_redirect()
        return subject

    def _csrf_value(request: Request) -> str:
        session_token = request.cookies.get(SESSION_COOKIE, "")
        return csrf_module.token_for(active.secret_key, session_token)

    def _group_hosts(hosts: list[HostConfig]) -> dict[str, list[HostConfig]]:
        groups: dict[str, list[HostConfig]] = defaultdict(list)
        for host in hosts:
            groups[host.interface_group or "(default)"].append(host)
        return dict(sorted(groups.items()))

    def _split_zone(zone: str) -> tuple[str, str]:
        """Split the wizard's ``<zone_id>:<zone_name>`` select value."""
        zone_id, _, zone_name = zone.partition(":")
        if not zone_id or not zone_name:
            raise HTTPException(status_code=400, detail="malformed zone selection")
        return zone_id, zone_name

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request, user: str = Depends(get_current_user)) -> HTMLResponse:
        hosts = app.state.hosts.list_hosts()
        groups = app.state.hosts.load_interface_groups()
        interface_map = {g.name: g.interface_name for g in groups}
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "user": user,
                "host_groups": _group_hosts(hosts),
                "interface_map": interface_map,
                "csrf_value": _csrf_value(request),
                "csrf_field": csrf_module.FORM_FIELD,
            },
        )

    @app.get("/login", response_class=HTMLResponse)
    async def login_get(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "login.html", {"error": None})

    @app.post("/login")
    async def login_post(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
    ) -> object:
        ip = _client_ip(request)
        if _locked_out(ip):
            _LOGGER.warning("login lockout active for %s", ip)
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": "Too many failed attempts; try again later"},
                status_code=429,
            )
        if not await authenticate(username, password):
            _record_failure(ip)
            _LOGGER.warning("failed login for %r from %s", username, ip)
            await asyncio.sleep(_FAILURE_DELAY)
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": "Invalid credentials"},
                status_code=401,
            )
        app.state.login_failures.pop(ip, None)
        response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
        _attach_session_cookie(response, _create_token(username))
        _LOGGER.info("user %r logged in from %s", username, ip)
        return response

    @app.post("/logout")
    async def logout(
        request: Request,
        user: str = Depends(get_current_user),
        _: None = Depends(csrf_module.require_match),
    ) -> RedirectResponse:
        app.state.session_generation += 1
        response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
        response.delete_cookie(SESSION_COOKIE, path="/")
        _LOGGER.info("user %r logged out; all sessions invalidated", user)
        return response

    @app.get("/wizard", response_class=HTMLResponse)
    async def wizard(request: Request, user: str = Depends(get_current_user)) -> HTMLResponse:
        interfaces = app.state.interfaces.list_interfaces()
        return templates.TemplateResponse(
            request,
            "wizard.html",
            {
                "user": user,
                "zones": [],
                "interfaces": interfaces,
                "interface_groups": app.state.hosts.load_interface_groups(),
                "csrf_value": _csrf_value(request),
                "csrf_field": csrf_module.FORM_FIELD,
            },
        )

    @app.post("/wizard/zone")
    async def wizard_zones(
        request: Request,
        user: str = Depends(get_current_user),
        _: None = Depends(csrf_module.require_match),
    ) -> HTMLResponse:
        try:
            provider = build_provider(active.dns_provider, token=active.cloudflare_api_token)
        except ProviderError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            zones = await provider.list_zones()
        except ProviderError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        finally:
            await provider.close()
        return templates.TemplateResponse(
            request,
            "wizard.html",
            {
                "user": user,
                "zones": zones,
                "interfaces": app.state.interfaces.list_interfaces(),
                "interface_groups": app.state.hosts.load_interface_groups(),
                "csrf_value": _csrf_value(request),
                "csrf_field": csrf_module.FORM_FIELD,
            },
        )

    @app.post("/add-host")
    async def add_host(
        request: Request,
        user: str = Depends(get_current_user),
        _: None = Depends(csrf_module.require_match),
        hostname: str = Form(...),
        zone: str = Form(...),
        proxied: str | None = Form(None),
        interface_group: str | None = Form(None),
    ) -> RedirectResponse:
        zone_id, zone_name = _split_zone(zone)
        try:
            config = HostConfig(
                hostname=hostname,
                zone_id=zone_id,
                zone_name=zone_name,
                proxied=bool(proxied),
                interface_group=interface_group or None,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            app.state.hosts.add_host(config)
        except PersistenceError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    @app.post("/add-hosts-bulk")
    async def add_hosts_bulk(
        request: Request,
        user: str = Depends(get_current_user),
        _: None = Depends(csrf_module.require_match),
        hostnames: str = Form(...),
        zone: str = Form(...),
        proxied: str | None = Form(None),
        interface_group: str | None = Form(None),
    ) -> RedirectResponse:
        """Add many hostnames at once.

        ``hostnames`` is one hostname per line; blank lines ignored. All
        entries share ``interface_group`` and the selected zone.
        """
        zone_id, zone_name = _split_zone(zone)
        raw = [line.strip() for line in hostnames.splitlines() if line.strip()]
        rows = [(hostname, zone_id, zone_name, bool(proxied)) for hostname in raw]
        result = app.state.hosts.add_hosts_bulk(rows, interface_group=interface_group or None)
        _LOGGER.info(
            "bulk add by %r: %d added, %d skipped", user, len(result.added), len(result.skipped)
        )
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    @app.post("/delete-host")
    async def delete_host(
        request: Request,
        user: str = Depends(get_current_user),
        _: None = Depends(csrf_module.require_match),
        hostname: str = Form(...),
    ) -> RedirectResponse:
        if not app.state.hosts.remove_host(hostname):
            raise HTTPException(status_code=404, detail=f"unknown hostname: {hostname}")
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    @app.post("/register-group")
    async def register_group(
        request: Request,
        user: str = Depends(get_current_user),
        _: None = Depends(csrf_module.require_match),
        name: str = Form(...),
        interface_name: str | None = Form(None),
        description: str = Form(""),
    ) -> RedirectResponse:
        try:
            app.state.hosts.register_interface_group(
                name, interface_name=interface_name or None, description=description
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse(url="/wizard", status_code=status.HTTP_303_SEE_OTHER)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "ts": datetime.now(UTC).isoformat()}

    return app


def get_application() -> FastAPI:
    """ASGI factory for uvicorn (``--factory``) and the CLI entry points."""
    return _create_app()
