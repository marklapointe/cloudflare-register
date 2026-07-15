"""E2E web UI tests run against a real uvicorn process + headless Chromium.

Marked with ``@pytest.mark.e2e`` so ``make test`` skips them by default.
Use ``make test-e2e`` to run the full browser suite; CI calls this only on
main-branch builds.

No real Cloudflare traffic: all provider calls are stubbed by setting an
arbitrary token (the wizard route will surface a 502 when it tries to list
zones; we don't trigger that path).
"""

from __future__ import annotations
