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
"""Session-bound CSRF tokens (signed synchronizer pattern).

The token is ``HMAC-SHA256(secret_key, "csrf:" + access_token)`` — derived
from the session JWT itself, so it needs no extra cookie and cannot be
planted by a sibling subdomain or plain-HTTP MITM the way a naked
double-submit cookie can. The server injects the token into every form it
renders; :func:`require_match` recomputes it from the caller's session
cookie and compares in constant time.

A token is only as live as its session: re-login rotates the JWT and hence
every form token. ``SameSite=Lax`` on the session cookie provides defense
in depth.
"""

from __future__ import annotations

import hashlib
import hmac

from fastapi import HTTPException, Request, status

FORM_FIELD = "csrf_token"

SESSION_COOKIE = "access_token"


def token_for(secret_key: str, session_token: str) -> str:
    """Derive the CSRF token bound to ``session_token`` (the session JWT)."""
    mac = hmac.new(secret_key.encode("utf-8"), b"csrf:", hashlib.sha256)
    mac.update(session_token.encode("utf-8"))
    return mac.hexdigest()


async def require_match(request: Request) -> None:
    """FastAPI dependency: blocks POST/PUT/PATCH/DELETE without a valid token."""
    if request.method.upper() not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None
    session_token = request.cookies.get(SESSION_COOKIE)
    if not session_token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="missing session")
    try:
        form = await request.form()
    except Exception:
        form = None
    form_value = form.get(FORM_FIELD) if form else None
    if not isinstance(form_value, str) or not form_value:
        if form is not None:
            await form.close()  # release spooled upload files before rejecting
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="missing CSRF form field")
    secret_key = request.app.state.settings.secret_key
    expected = token_for(secret_key, session_token)
    if not hmac.compare_digest(expected, form_value):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token mismatch")
    return None
