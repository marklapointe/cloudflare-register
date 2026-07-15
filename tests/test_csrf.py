"""CSRF double-submit-cookie tests via FastAPI's TestClient.

The route uses ``Depends(csrf_module.require_match)`` (rather than the bare
annotation ``_: None = csrf_module.require_match``) so FastAPI doesn't
interpret the default value as a request parameter expecting ``None``.

Cookies are passed through the ``Cookie`` header on a per-request basis;
the ``httpx2`` ``TestClient`` no longer accepts a pre-built ``Cookies`` jar
as a constructor kwarg on individual ``.post()`` calls.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from cloudflare_register.web import csrf as csrf_module


def _make_app() -> FastAPI:
    app = FastAPI()

    @app.post("/echo")
    async def _echo(_: None = Depends(csrf_module.require_match)):
        return {"ok": True}

    return app


def test_post_without_cookie_rejected():
    client = TestClient(_make_app())
    response = client.post("/echo", data={"csrf_token": "anything"})
    assert response.status_code == 403


def test_post_with_matching_form_passes():
    token = csrf_module.issue_token()
    client = TestClient(_make_app())
    response = client.post(
        "/echo",
        data={csrf_module.FORM_FIELD: token},
        headers={"cookie": f"{csrf_module.COOKIE_NAME}={token}"},
    )
    assert response.status_code == 200, response.text


def test_post_with_mismatched_tokens_rejected():
    client = TestClient(_make_app())
    response = client.post(
        "/echo",
        data={csrf_module.FORM_FIELD: "form-value"},
        headers={"cookie": f"{csrf_module.COOKIE_NAME}=different-value"},
    )
    assert response.status_code == 403
