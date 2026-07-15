# AGENTS_START_HERE

| Field | Value |
|-------|-------|
| Document ID | AGENTS-CFR |
| Version | 2.0.0 |
| Last Updated | 2026-07-14 |
| Maintainer | Mark LaPointe <mark@cloudbsd.org> |
| Status | ACTIVE |
| Classification | INTERNAL |

---

## FreeBSD / Cross-Platform Environment Disclaimer

`cloudflare-register` is a Python service. The intended production targets are
FreeBSD (rc.d), Debian/Ubuntu (systemd), and any Linux with cron. macOS is
supported via pip. The codebase does not contain kernel code; none of the
"VMM / bhyve / kernel module" rules in the CloudBSD guidelines apply.

## Project Summary

Smart DynDNS service for Cloudflare. Manages multiple hostnames across
multiple zones, supports dual-stack (IPv4 + IPv6) with auto-detect and
state synchronization, and offers three operator surfaces:

* Web UI (`make service`) — dashboard + JWT login + wizard + bulk add
* TUI (`make tui`) — keyboard-driven dashboard (Textual)
* CLI (`make sync`, cron-friendly) — single-shot reconciliation

The codebase is organized as a layered architecture:

```
domain/          ← pure Pydantic models (no infra)
services/        ← HostService, InterfaceService, SyncService
cli/web/tui      ← adapters; thin controllers that delegate
providers/       ← Strategy + Factory for DNS backends
persistence.py   ← atomic JSON storage with flock
```

## Document Map

* `README.md` — user-facing quick start, install, deployment recipes.
* `AGENTS_START_HERE.md` (this file) — entry point for autonomous agents.
* `.plan/0000-TOC.md` — table of contents and cross-reference index.
* `.plan/0001-Workflow.md` — how to work on this project.
* `.plan/0002-Build-Status.md` — CI/CD pipeline + artifacts.
* `.plan/0100-Security-Overview.md` — security stance and threats.
* `.plan/0200-Architecture.md` — components, diagrams, design patterns.
* `.plan/0300-Implementation-Tasks.md` — task tracker.
* `.plan/0400-Testing.md` — test strategy and tooling.
* `.plan/0500-Operations.md` — deployment matrix.
* `.plan/0700-Risks.md` — risk register.

## Four Primary Directives

1. **Security First** — secrets in the JSON config (0600), session-bound
   CSRF on every POST, bcrypt password hashing, login throttling, no shell
   expansion of user input. See `.plan/0100-Security-Overview.md`.
2. **Layered Architecture** — `domain/` (pure) → `services/` (orchestration)
   → adapters. Controllers MUST NOT touch `persistence.py` directly;
   they call `HostService` / `InterfaceService`. See
   `.plan/0200-Architecture.md`.
3. **Traceability** — every change is a task; every task is tested; every
   test passes before merge. See `.plan/0300-Implementation-Tasks.md`.
4. **Configuration Discipline** — XDG Base Directory paths, pydantic
   validation, no permissive defaults, fail fast on insecure config. See
   `pyproject.toml` and `src/cloudflare_register/config.py`.

## Reading Order for New Agents

1. `README.md`
2. `AGENTS_START_HERE.md`
3. `.plan/0000-TOC.md`
4. `.plan/0200-Architecture.md`
5. `.plan/0100-Security-Overview.md`
6. `.plan/0300-Implementation-Tasks.md` (claim a task)
7. `.plan/0400-Testing.md`
8. `.plan/0500-Operations.md`
9. `.plan/0700-Risks.md`

## Key Design Decisions

| Decision | Why | Where |
|----------|-----|-------|
| Layered domain/services/adapters | Future-extractable; controllers don't need to know about persistence | `domain/`, `services/`, `cli.py` |
| Click over Typer | Smaller dep surface; identical UX with decorators | `cli.py` |
| httpx async client over python-cloudflare | Web UI and sync loop share one connection pool | `providers/cloudflare.py` |
| Textual over urwid/blessed | Maintained async TUI; keyboard-first per CloudBSD TUI guidelines | `tui/app.py` |
| bcrypt over passlib | No known warnings on bcrypt ≥ 4; passlib maintenance is dormant | `web/app.py` |
| Atomic JSON over SQLite | Expected cardinality is "a few hosts"; SQLite brings a native dep | `persistence.py` |
| LRU/TTL cache for IP detection | Endpoints are best-effort; cache window is 30 s to absorb flapping | `ip_detection.py` |
| XDG paths | CloudBSD configuration mandate | `config.py` |
| OS-agnostic Makefile | One Makefile, `uname -s` selects backend | `Makefile` |
| psutil 7.x for interface detection | BSD-3, actively maintained, no root needed | `services/interface_service.py` |
| UDP-connect for default route | O(1) kernel-side lookup; no packet sent | `services/interface_service.py` |

## Quick Reference

| Need | Command |
|------|---------|
| Install deps | `make install` |
| Run service (foreground) | `make service` |
| Run web only | `make web` |
| Run TUI | `make tui` |
| Run sync once | `make sync` |
| Validate config | `make check-config` |
| Generate JSON config | `make init` |
| List interfaces | `make interfaces` |
| List hosts | `make hosts` |
| Run unit tests | `make test` |
| Run coverage (80 % gate) | `make test-cov` |
| Run Playwright E2E | `make test-e2e` |
| Run lint | `make lint` |
| Build native package | `make package` |
| Build FreeBSD port | `make package-freebsd` |
| Build Debian .deb | `make package-debian` |
| Build sdist+wheel | `make package-generic` |
| Install systemd unit | `make install-systemd` |
| Install rc.d script | `make install-rc` |
| Print platform info | `make info` |

| Need | Path |
|------|------|
| Default config (JSON) | `$CLOUDFLARE_REGISTER_CONFIG` → `/etc/cloudflare-register.json` → `~/.config/cloudflare_register/config.json` |
| Default data dir | `$XDG_DATA_HOME/cloudflare_register/` |
| Hosts JSON | `$XDG_DATA_HOME/cloudflare_register/hosts.json` (0600) |
| Interface groups JSON | `$XDG_DATA_HOME/cloudflare_register/interface_groups.json` (0600) |
| Logs | `stderr`; redirectable per service unit |
| Playwright screenshots | `docs/screenshots/0X-*.png` |

## Need Help?

* Read `.plan/0001-Workflow.md` for the daily loop.
* Skim `.plan/0700-Risks.md` for known limitations.
* Check the test suite (`make test`) for usage examples.
* Service tests are in `tests/test_services/`.
* E2E (Playwright) tests are in `tests/e2e_web/` — run with `make test-e2e`.
* File issues at https://github.com/cloudbsdorg/cloudflare-register/issues
  with `[cfr]` in the subject.

---

Last Updated: 2026-07-14
Contact: Mark LaPointe <mark@cloudbsd.org>
Classification: INTERNAL
