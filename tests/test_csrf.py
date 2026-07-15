"""Session-bound CSRF token tests via FastAPI's TestClient.

The token is ``HMAC-SHA256(secret_key, "csrf:" + session_jwt)``: derived
from the session cookie, so there is no separate CSRF cookie an attacker
could plant. ``require_match`` recomputes the expected value from the
caller's session cookie and compares it to the form field in constant time.
"""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from cloudflare_register.web import csrf as csrf_module

_SECRET = "unit-test-secret-key-0123456789abcdef"
_SESSION = "session-jwt-value"


def _make_app() -> FastAPI:
    app = FastAPI()
    app.state.settings = SimpleNamespace(secret_key=_SECRET)

    @app.post("/echo")
    async def _echo(_: None = Depends(csrf_module.require_match)):
        return {"ok": True}

    return app


def _session_header() -> dict[str, str]:
    return {"cookie": f"{csrf_module.SESSION_COOKIE}={_SESSION}"}


def test_token_is_deterministic_and_session_bound():
    token = csrf_module.token_for(_SECRET, _SESSION)
    assert token == csrf_module.token_for(_SECRET, _SESSION)
    assert token != csrf_module.token_for(_SECRET, "other-session")
    assert token != csrf_module.token_for("another-secret-key-0123456789abcdef", _SESSION)


def test_post_without_session_rejected():
    client = TestClient(_make_app())
    response = client.post("/echo", data={csrf_module.FORM_FIELD: "anything"})
    assert response.status_code == 403


def test_post_without_form_field_rejected():
    client = TestClient(_make_app())
    response = client.post("/echo", data={"other": "x"}, headers=_session_header())
    assert response.status_code == 403


def test_post_with_matching_token_passes():
    token = csrf_module.token_for(_SECRET, _SESSION)
    client = TestClient(_make_app())
    response = client.post("/echo", data={csrf_module.FORM_FIELD: token}, headers=_session_header())
    assert response.status_code == 200, response.text


def test_post_with_wrong_token_rejected():
    client = TestClient(_make_app())
    response = client.post(
        "/echo", data={csrf_module.FORM_FIELD: "f" * 64}, headers=_session_header()
    )
    assert response.status_code == 403


def test_post_with_token_for_other_session_rejected():
    token = csrf_module.token_for(_SECRET, "someone-elses-session")
    client = TestClient(_make_app())
    response = client.post("/echo", data={csrf_module.FORM_FIELD: token}, headers=_session_header())
    assert response.status_code == 403


def test_file_upload_as_token_rejected_not_500():
    """A file part named csrf_token must 403, not crash the comparison."""
    client = TestClient(_make_app())
    response = client.post(
        "/echo",
        files={csrf_module.FORM_FIELD: ("t.txt", b"data")},
        headers=_session_header(),
    )
    assert response.status_code == 403
