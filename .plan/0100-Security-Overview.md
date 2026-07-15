# Security Overview

| Field | Value |
|-------|-------|
| Document ID | 0100-CFR-Security-Overview |
| Version | 1.0.0 |
| Last Updated | 2026-07-14 |
| Maintainer | Mark LaPointe <mark@cloudbsd.org> |
| Status | ACTIVE |
| Classification | CONFIDENTIAL |

---

> MANDATORY per CloudBSD §1. All CloudBSD products must carry a security
> document.

## Trust Model

| Tier | Description |
|------|-------------|
| T0 | Source repository owner (Mark LaPointe). |
| T1 | Package maintainers (`cloudbsdorg/cloudflare-register` maintainers). |
| T2 | The user running the service. Holds all credentials. |
| T3 | The web UI session after T2 logs in. Held only over HTTPS (or local). |
| T4 | The DNS provider API (Cloudflare). Token-scoped to Zone:DNS:Edit only. |

## Threats (STRIDE summary)

| Category | Risk | Mitigation |
|----------|------|------------|
| Spoofing | Cross-site request forgery against dashboard | CSRF double-submit cookie; SameSite=Lax; POST-only state changes |
| Tampering | Hosts JSON overwritten or replaced mid-write | `O_EXCL` tempfile + `fsync` + `os.replace`, fcntl flock |
| Repudiation | User logs in but operations aren't attributable | Future: per-user audit log; today at least access_token session ID |
| Information disclosure | `.env` readable by other users | `.env` mode 0600; systemd `ProtectHome` + `ReadWritePaths=...`; rc.d uses unprivileged user |
| Denial of service | HTTP loop / loop flood | FastAPI is async; uvicorn workers not yet pool-sized, FUTURE |
| Elevation of privilege | Web UI runs as root | Service drops to `cloudflare-ddns` system user before binding |

## Secrets Handling

| Secret | Storage | Permission |
|--------|---------|-----------|
| `CLOUDFLARE_API_TOKEN` | Env var / `.env` | 0600 file |
| `SECRET_KEY` | Env var / `.env` | 0600 file |
| `ADMIN_PASSWORD` / hash | Env var | bcrypt 12 rounds |

## Cryptography

| Primitive | Purpose | Library |
|-----------|---------|---------|
| bcrypt | password hash | `bcrypt` 4.x |
| HMAC-SHA-256 | JWT signing | `python-jose`/`pyjwt` |
| `secrets.token_urlsafe(32)` | CSRF token | stdlib |

## Web Security

* **CSRF**: double-submit cookie + `SameSite=Lax` + `Secure` when HTTPS.
* **XSS**: Jinja2 auto-escape is on by default; no `|safe` on user content.
* **Headers**: `Strict-Transport-Security`, `Content-Security-Policy`,
  `X-Content-Type-Options`, `X-Frame-Options` are NOT yet set.
  Tracked in `0300-Implementation-Tasks.md`.

## Code Risks

| Risk | File | Status |
|------|------|--------|
| Plaintext admin password in dev | `config.py` | gated behind `ADMIN_PASSWORD_HASH` |
| `requests` style sync I/O left over | none after refactor | n/a |
| `subprocess` ever introduced | none | guard ruff `S603` |

## Audit Hooks

| Event | Log level | Sink |
|-------|-----------|------|
| Login success | INFO | stderr (configurable to file) |
| Login failure | WARNING | stderr |
| Host added/removed | INFO | stderr |
| Provider auth error | ERROR | stderr |

## Future Work (Post-1.0)

* HTTPS via Caddy or Let's Encrypt.
* Rate limiting on `/login` (`slowapi`).
* Per-user audit log.

---

## Change Log

| Version | Date | Author | Change |
|---------|------|--------|--------|
| 1.0.0 | 2026-07-14 | Mark LaPointe | Initial security overview; threat model + secret handling. |

Last Updated: 2026-07-14
Contact: Mark LaPointe <mark@cloudbsd.org>
Classification: CONFIDENTIAL
