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

| Stage | Backend | Command | Status |
|-------|---------|---------|--------|
| Lint | ruff + mypy | `make lint` | green |
| Test | pytest + coverage | `make test-cov` | green |
| Build sdist/wheel | pep517 | `make package-generic` | green |
| Build .deb | dpkg-buildpackage | `make package-debian` | green |
| Build .txz | contrib/freebsd port | `make package-freebsd` | green |

## Artifacts

| OS | Artifact | Path |
|----|----------|------|
| Linux | `.deb` | `../cloudflare-register_${VERSION}_all.deb` |
| FreeBSD | `.txz` | `dist/cloudflare-register-${VERSION}.txz` |
| macOS / generic | `.whl + .tar.gz` | `dist/` |

## Last Updated

2026-07-14 — pipeline green from a single source tree on all three OSes.

Last Updated: 2026-07-14
Contact: Mark LaPointe <mark@cloudbsd.org>
Classification: INTERNAL
