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
"""Per-request CSRF token (double-submit-cookie pattern).

At login a random token is generated and stored in a non-``HttpOnly`` cookie.
Every state-changing form must echo the same value in a hidden form field.
Server compares cookie value to form value with a constant-time compare; a
missing or mismatched pair is rejected.

``SameSite=Lax`` on the cookie provides defense in depth.
"""

from __future__ import annotations

import secrets

from fastapi import HTTPException, Request, status

COOKIE_NAME = "csrf_token"
FORM_FIELD = "csrf_token"


def issue_token() -> str:
    """Return a fresh random CSRF token (raw value, never encoded)."""
    return secrets.token_urlsafe(32)


def set_cookie(response, token: str, *, secure: bool, max_age: int) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=False,
        secure=secure,
        samesite="lax",
        max_age=max_age,
        path="/",
    )


def delete_cookie(response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


async def require_match(request: Request) -> None:
    """FastAPI dependency: blocks POST/PUT/PATCH/DELETE without a matching token pair."""
    if request.method.upper() not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None
    cookie_value = request.cookies.get(COOKIE_NAME)
    if not cookie_value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="missing CSRF cookie")
    try:
        form = await request.form()
    except Exception:
        form = None
    form_value = form.get(FORM_FIELD) if form else None
    if not form_value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="missing CSRF form field")
    if not secrets.compare_digest(cookie_value, form_value):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token mismatch")
    return None
