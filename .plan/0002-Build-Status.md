# Build Status

| Field | Value |
|-------|-------|
| Document ID | 0002-CFR-Build-Status |
| Version | 1.0.0 |
| Last Updated | 2026-07-14 |
| Maintainer | Mark LaPointe <mark@cloudbsd.org> |
| Status | ACTIVE |
| Classification | INTERNAL |

---

## CI/CD Pipeline

Hosted CI: GitHub Actions (`.github/workflows/ci.yml`) — ruff, mypy, and
pytest (with the 80 % coverage gate) on Linux across Python 3.11–3.13.
Package builds are local-only make targets and are NOT exercised by CI;
statuses below reflect the last manual run on this workstation.

| Stage | Backend | Command | Status |
|-------|---------|---------|--------|
| Lint | ruff + mypy | `make lint` | green (local, 2026-07-14) |
| Test | pytest + coverage | `make test-cov` | green (local, 2026-07-14) |
| Build sdist/wheel | pep517 | `make package-generic` | green (local) |
| Build .deb | dpkg-buildpackage | `make package-debian` | untested since packaging rewrite |
| Build .txz | contrib/freebsd port | `make package-freebsd` | untested since packaging rewrite |

## Artifacts

| OS | Artifact | Path |
|----|----------|------|
| Linux | `.deb` | `../cloudflare-register_${VERSION}_all.deb` |
| FreeBSD | `.txz` | `dist/cloudflare-register-${VERSION}.txz` |
| macOS / generic | `.whl + .tar.gz` | `dist/` |

## Last Updated

2026-07-14 — security + correctness overhaul; debian/ and contrib/freebsd/
rewritten and pending a real package build on their target OSes.

Last Updated: 2026-07-14
Contact: Mark LaPointe <mark@cloudbsd.org>
Classification: INTERNAL
