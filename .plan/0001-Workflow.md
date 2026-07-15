# Workflow

## Document Header

| Field | Value |
|-------|-------|
| Document ID | 0001-CFR-Workflow |
| Version | 1.0.0 |
| Last Updated | 2026-07-14 |
| Maintainer | Mark LaPointe <mark@cloudbsd.org> |
| Status | ACTIVE |
| Classification | INTERNAL |

---

## Daily Loop

1. Read `.plan/0300-Implementation-Tasks.md` and pick an unassigned task.
2. Move it to IN PROGRESS in the table; commit.
3. Implement + test.
4. Move it to DONE; commit.

## Commands

```sh
make install     # editable install in .venv
make test        # pytest
make lint        # ruff + mypy
make format      # ruff format + safe fixes
make package     # backend picked from `make info`
make package-freebsd | package-debian | package-generic
make install-systemd   # Linux
make install-rc        # FreeBSD
```

## Branching

`main` always passable. Feature branches named `feature/<scope>`. Squash on
merge so the result is one atomic commit per task.

## Verification Gate

A PR is mergeable when:

* `make test` exits 0
* `make lint` exits 0
* Coverage report has no regression for changed files
* `make package` exits 0 for the current OS

---

## Change Log

| Version | Date | Author | Change |
|---------|------|--------|--------|
| 1.0.0 | 2026-07-14 | Mark LaPointe | Initial workflow document. |

Last Updated: 2026-07-14
Contact: Mark LaPointe <mark@cloudbsd.org>
Classification: INTERNAL
