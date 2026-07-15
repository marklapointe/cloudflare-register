# Testing

| Field | Value |
|-------|-------|
| Document ID | 0400-CFR-Testing |
| Version | 1.0.0 |
| Last Updated | 2026-07-14 |
| Maintainer | Mark LaPointe <mark@cloudbsd.org> |
| Status | ACTIVE |
| Classification | INTERNAL |

---

## Goals

* 80 % line coverage; 100 % coverage on cryptographic, persistence, and
  CSRF paths.
* Every commit runs unit tests in < 5 seconds.
* Tests are deterministic; no network, no real clock, no shared global
  state.

## Layers

| Layer | Tooling | Targets |
|-------|---------|---------|
| Unit | pytest, pytest-asyncio | library code in `src/cloudflare_register/**` |
| Integration | pytest + httpx + TestClient | FastAPI routes against `TestClient` |
| Contract | respx (planned) | Cloudflare REST stubbed with httpx `MockTransport` |
| End-to-end | bhyve VM (planned) | full install + sync + cron smoke test |

## Test Conventions

* All tests live under `tests/`.
* Each test file starts with `test_<module>.py`.
* Tests are grouped by module: `test_persistence.py`, `test_sync.py`, etc.
* `tests/conftest.py` provides autouse fixtures that point `XDG_*` at a
  `tmp_path` and reset the settings cache.
* One logical assertion per test; descriptive names (e.g.
  `test_reconcile_deletes_missing_family`).
* `assert` is allowed inside tests (covered by ruff `S101` per-file ignore).
* Async tests use `pytest-asyncio` (`asyncio_mode = "auto"`).

## Mocks

* `httpx.AsyncClient` is replaced with a `_FakeAsyncClient` exposing a
  scripted queue of responses; no real network calls.
* The Cloudflare provider is exercised with this fake client.
* `Provider` subclasses may be implemented inline in test modules when a
  full Strategy implementation isn't needed (see `_StaticProvider` in
  `tests/test_sync.py`).

## Coverage Enforcement

`pyproject.toml` configures `pytest-cov` with `fail_under = 80`. CI exits
non-zero if coverage drops.

## Pre-Commit (Local)

`scripts/inject_license.py` ensures license headers stay on every Python
file. Wire it into a pre-commit hook if a team uses `pre-commit.com`.

---

## Change Log

| Version | Date | Author | Change |
|---------|------|--------|--------|
| 1.0.0 | 2026-07-14 | Mark LaPointe | Initial testing document. |

Last Updated: 2026-07-14
Contact: Mark LaPointe <mark@cloudbsd.org>
Classification: INTERNAL
