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
* ``POST /login``         - exchange credentials for session cookies.
* ``POST /logout``        - clear session cookies.
* ``GET  /wizard``        - add-host wizard (with interface selector).
* ``POST /wizard/zone``   - fetch available Cloudflare zones.
* ``POST /add-host``      - persist a single new host.
* ``POST /add-hosts-bulk``- persist many hostnames sharing one interface group.
* ``POST /delete-host``   - remove a managed host.
* ``GET  /healthz``       - unauthenticated liveness probe.

All persistence is delegated to :class:`HostService` and :class:`InterfaceService`;
this module is a thin controller.
"""

from __future__ import annotations

from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import bcrypt
from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from jose import JWTError
from jose import jwt as jose_jwt

from cloudflare_register.config import Settings, get_settings
from cloudflare_register.domain import HostConfig
from cloudflare_register.exceptions import PersistenceError, ProviderError
from cloudflare_register.logging_setup import get_logger
from cloudflare_register.providers.factory import build as build_provider
from cloudflare_register.services import HostService, InterfaceService
from cloudflare_register.web import csrf as csrf_module

_LOGGER = get_logger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))


def _create_app(settings: Settings | None = None) -> FastAPI:
    active = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        active.ensure_paths()
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

    async def authenticate(username: str, password: str) -> bool:
        if active.admin_password_hash:
            try:
                return bcrypt.checkpw(
                    password.encode("utf-8"), active.admin_password_hash.encode("utf-8")
                )
            except ValueError:
                return False
        return username == active.admin_username and password == active.admin_password

    def _create_token(subject: str) -> str:
        expire = datetime.now(UTC) + timedelta(minutes=active.access_token_expire_minutes)
        return jose_jwt.encode(
            {"sub": subject, "exp": expire}, active.secret_key, algorithm="HS256"
        )

    def _attach_session_cookies(
        response: RedirectResponse, jwt_value: str, csrf_value: str
    ) -> None:
        max_age = active.access_token_expire_minutes * 60
        response.set_cookie(
            "access_token",
            jwt_value,
            httponly=True,
            secure=active.cookie_secure,
            samesite="lax",
            max_age=max_age,
            path="/",
        )
        csrf_module.set_cookie(response, csrf_value, secure=active.cookie_secure, max_age=max_age)

    def _detach_session_cookies(response: RedirectResponse) -> None:
        response.delete_cookie("access_token", path="/")
        csrf_module.delete_cookie(response)

    async def get_current_user(request: Request) -> str:
        token = request.cookies.get("access_token")
        if not token:
            raise HTTPException(
                status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"}
            )
        try:
            payload = jose_jwt.decode(token, active.secret_key, algorithms=["HS256"])
        except JWTError as exc:
            _LOGGER.info("rejected session: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"}
            ) from exc
        return payload.get("sub", "")

    def _group_hosts(hosts: list[HostConfig]) -> dict[str, list[HostConfig]]:
        groups: dict[str, list[HostConfig]] = defaultdict(list)
        for host in hosts:
            groups[host.interface_group or "(default)"].append(host)
        return dict(sorted(groups.items()))

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request, user: str = Depends(get_current_user)) -> HTMLResponse:
        csrf_value = request.cookies.get(csrf_module.COOKIE_NAME, "")
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
                "csrf_value": csrf_value,
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
        if not await authenticate(username, password):
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": "Invalid credentials"},
                status_code=401,
            )
        jwt_value = _create_token(username)
        csrf_value = csrf_module.issue_token()
        response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
        _attach_session_cookies(response, jwt_value, csrf_value)
        _LOGGER.info("user %s logged in", username)
        return response

    @app.post("/logout")
    async def logout() -> RedirectResponse:
        response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
        _detach_session_cookies(response)
        return response

    @app.get("/wizard", response_class=HTMLResponse)
    async def wizard(request: Request, user: str = Depends(get_current_user)) -> HTMLResponse:
        csrf_value = request.cookies.get(csrf_module.COOKIE_NAME, "")
        interfaces = app.state.interfaces.list_interfaces()
        return templates.TemplateResponse(
            request,
            "wizard.html",
            {
                "user": user,
                "zones": [],
                "interfaces": interfaces,
                "interface_groups": app.state.hosts.load_interface_groups(),
                "csrf_value": csrf_value,
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
        csrf_value = request.cookies.get(csrf_module.COOKIE_NAME, "")
        return templates.TemplateResponse(
            request,
            "wizard.html",
            {
                "user": user,
                "zones": zones,
                "interfaces": app.state.interfaces.list_interfaces(),
                "interface_groups": app.state.hosts.load_interface_groups(),
                "csrf_value": csrf_value,
                "csrf_field": csrf_module.FORM_FIELD,
            },
        )

    @app.post("/add-host")
    async def add_host(
        request: Request,
        user: str = Depends(get_current_user),
        _: None = Depends(csrf_module.require_match),
        hostname: str = Form(...),
        zone_id: str = Form(...),
        zone_name: str = Form(...),
        proxied: str | None = Form(None),
        interface_group: str | None = Form(None),
    ) -> RedirectResponse:
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
        zone_id: str = Form(...),
        zone_name: str = Form(...),
        proxied: str | None = Form(None),
        interface_group: str | None = Form(None),
    ) -> RedirectResponse:
        """Add many hostnames at once.

        ``hostnames`` is one hostname per line; blank lines ignored. All
        entries share ``interface_group`` and ``zone_id``.
        """
        raw = [line.strip() for line in hostnames.splitlines() if line.strip()]
        rows = [(hostname, zone_id, zone_name, bool(proxied)) for hostname in raw]
        result = app.state.hosts.add_hosts_bulk(rows, interface_group=interface_group or None)
        _LOGGER.info(
            "bulk add by %s: %d added, %d skipped", user, len(result.added), len(result.skipped)
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


app = _create_app()


def get_application() -> FastAPI:
    """ASGI entry point for uvicorn / hypercorn."""
    return app
