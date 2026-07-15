# Implementation Tasks

| Field | Value |
|-------|-------|
| Document ID | 0300-CFR-Implementation-Tasks |
| Version | 2.0.0 |
| Last Updated | 2026-07-14 |
| Maintainer | Mark LaPointe <mark@cloudbsd.org> |
| Status | ACTIVE |
| Classification | INTERNAL |

---

## Task Format

Columns: ID | Task | Priority | Status | Assigned To | Owner | Phase | Start | End | Dependencies | Files | Spec | Notes

| Phase | Focus | Emoji |
|-------|-------|-------|
| 0 | Foundation | :white_circle: |
| 1 | Providers & persistence | :white_circle: |
| 2 | Web & CLI | :white_circle: |
| 3 | Packaging & service | :white_circle: |
| 4 | Hardening | :white_circle: |
| 5 | Layered architecture | :white_circle: |

Emoji states:
* :white_circle: not started
* :large_blue_circle: in progress
* :white_check_mark: completed
* :red_circle: blocked / failed

## TODO Tracker

| ID | Task | Priority | Status | Phase | Files |
|----|------|----------|--------|-------|-------|
| 1 | Restructure into `src/cloudflare_register/` package | P0 | DONE | 1 | src/ |
| 2 | Add BSD 3-Clause headers via `scripts/inject_license.py` | P0 | DONE | 1 | scripts/ |
| 3 | Strategy + Factory for DNS providers | P0 | DONE | 1 | providers/ |
| 4 | Atomic JSON persistence with flock | P0 | DONE | 1 | persistence.py |
| 5 | LRU/TTL cache in IP detection | P1 | DONE | 1 | ip_detection.py |
| 6 | Web UI CSRF (double-submit cookie) | P0 | DONE | 2 | web/ |
| 7 | bcrypt password verification | P0 | DONE | 2 | web/app.py |
| 8 | Click CLI subcommands | P0 | DONE | 2 | cli.py |
| 9 | Textual TUI | P2 | DONE | 2 | tui/ |
| 10 | OS-agnostic Makefile | P0 | DONE | 3 | Makefile |
| 11 | FreeBSD rc.d hardening | P1 | DONE | 3 | deploy/ |
| 12 | systemd hardening directives | P1 | DONE | 3 | deploy/ |
| 13 | FreeBSD port skeleton | P2 | DONE | 3 | contrib/freebsd/ |
| 14 | Debian packaging | P2 | DONE | 3 | debian/ |
| 15 | .gitignore / .editorconfig / pyproject.toml | P1 | DONE | 3 | . |
| 16 | Test suite expansion | P1 | DONE | 2 | tests/ |
| 17 | Domain layer (pure models) | P0 | DONE | 5 | domain/ |
| 18 | HostService (CRUD + bulk + grouping) | P0 | DONE | 5 | services/host_service.py |
| 19 | InterfaceService (psutil + UDP-connect) | P0 | DONE | 5 | services/interface_service.py |
| 20 | SyncService (group-aware orchestration) | P0 | DONE | 5 | services/sync_service.py |
| 21 | Refactor CLI to delegate to services | P0 | DONE | 5 | cli.py |
| 22 | Refactor Web to delegate to services | P0 | DONE | 5 | web/app.py |
| 23 | Refactor TUI to delegate to services | P1 | DONE | 5 | tui/app.py |
| 24 | Bulk-hostname wizard | P1 | DONE | 2 | web/templates/wizard.html |
| 25 | Service-layer unit tests | P1 | DONE | 5 | tests/test_services/ |
| 26 | Playwright E2E + screenshot capture | P1 | DONE | 2 | tests/e2e_web/, docs/screenshots/ |
| 27 | CSP / HSTS / X-Frame-Options headers | P1 | NOT STARTED | 4 | web/app.py |
| 28 | HTTPS listener via uvicorn[standard] + TLS certs | P2 | NOT STARTED | 4 | web/app.py |
| 29 | Login rate limiting (`slowapi`) | P2 | NOT STARTED | 4 | web/app.py |
| 30 | Audit log file | P2 | NOT STARTED | 4 | logging_setup.py |
| 31 | Provider: Route53 strategy | P3 | NOT STARTED | 4 | providers/ |
| 32 | Provider: Hetzner DNS strategy | P3 | NOT STARTED | 4 | providers/ |
| 33 | End-to-end smoke test in bhyve | P3 | NOT STARTED | 4 | tests/ |
| 34 | Cloudflare batch endpoint (one POST / batch update) | P2 | NOT STARTED | 4 | providers/cloudflare.py |

## Completed Work (Pre-Plan Files)

Pre-1.0 work shipped in commit history:

* FastAPI scaffolding (`src/app/main.py`).
* Single-provider DNS sync (`src/client/sync_service.py`).
* JSON host persistence (`src/common/persistence.py`).
* `make install` / `make run` / `make test` plumbing.

These are now superseded by the Phase 1–3 deliverables; historical references
remain only in commit messages.

---

## Change Log

| Version | Date | Author | Change |
|---------|------|--------|--------|
| 1.0.0 | 2026-07-14 | Mark LaPointe | Initial task tracker. |
| 2.0.0 | 2026-07-14 | Mark LaPointe | Phase 5 layered architecture delivered; service tests in place; Playwright E2E wired. |

Last Updated: 2026-07-14
Contact: Mark LaPointe <mark@cloudbsd.org>
Classification: INTERNAL
