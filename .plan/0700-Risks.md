# Risk Register

| Field | Value |
|-------|-------|
| Document ID | 0700-CFR-Risks |
| Version | 1.0.0 |
| Last Updated | 2026-07-14 |
| Maintainer | Mark LaPointe <mark@cloudbsd.org> |
| Status | ACTIVE |
| Classification | INTERNAL |

---

## Risk Register

| ID | Category | Risk | Likelihood | Impact | Mitigation | Owner | Status |
|----|----------|------|------------|--------|------------|-------|--------|
| R-001 | Auth | Plaintext admin password (default config) | Medium | High | Refused at startup when `ADMIN_PASSWORD_HASH` set; init command generates random password | Mark | Mitigated |
| R-002 | Auth | Default `SECRET_KEY` accepted in dev | Medium | High | Same as R-001; refs to default trigger warnings | Mark | Mitigated |
| R-003 | Persistence | Concurrent writes corrupt hosts.json | Low | High | `flock` + atomic tempfile + fsync | Mark | Mitigated |
| R-004 | Network | Public IP detection leak (logs)? | Low | Low | Endpoints are no-tracking well-known services; responses discarded after regex check | Mark | Mitigated |
| R-005 | Provider | Cloudflare API rate limit | Medium | Medium | Retry with exponential backoff + jitter; logs 429s | Mark | Mitigated |
| R-006 | Service | rc.d script backgrounds itself | Low | Medium | `procname=`, no `&`, real pidfile (regression from pre-1.0) | Mark | Mitigated |
| R-007 | Privilege | Service runs as root | Low | High | `User=cloudflare-ddns` in systemd; `run_rc_command` with `cloudflare_ddns_user` | Mark | Mitigated |
| R-008 | Web | CSRF on state-changing routes | Medium | High | Double-submit cookie + `SameSite=Lax` | Mark | Mitigated |
| R-009 | Web | No HTTPS | Low | High | Localhost; production expects reverse-proxy + TLS (planned Caddy docs) | Mark | Planned |
| R-010 | Supply | Unpinned dependencies | Medium | Medium | `requirements.txt` has compatible-release pins (`>=X,<Y`) | Mark | Mitigated |
| R-011 | Testing | Integration tests touch real Cloudflare | Medium | High | All tests use httpx fake client; no network egress | Mark | Mitigated |
| R-012 | Packaging | `make install` differs between OS | Medium | Medium | Single Makefile with `uname`-driven backend selection | Mark | Mitigated |

## Top Risks In Flight

None — all P0/P1 items have a mitigation.

## Risk Treatment Process

* New risks captured in this register on identification.
* Risks reviewed per release; P0/P1 risks gate the release.
* A mitigation is "applied" only after a regression test references it.

---

## Change Log

| Version | Date | Author | Change |
|---------|------|--------|--------|
| 1.0.0 | 2026-07-14 | Mark LaPointe | Initial risk register; pre-1.0 risks reviewed. |

Last Updated: 2026-07-14
Contact: Mark LaPointe <mark@cloudbsd.org>
Classification: INTERNAL
