# Makefile for cloudflare-register.
#
# This Makefile is deliberately OS-agnostic: `make install`, `make test`,
# `make package`, etc. behave the same on FreeBSD, Debian/Ubuntu, and macOS.
# The active backend is selected once at parse time from `uname -s`.
#
# Author: Mark LaPointe <mark@cloudbsd.org>
#
SHELL := /bin/sh

PACKAGE       := cloudflare_register
PROJECT_NAME  := cloudflare-register
VERSION       := $(shell grep '^version' pyproject.toml | head -1 | cut -d'"' -f2 2>/dev/null || echo 0.2.0)

PYTHON        ?= python3
VENV          ?= .venv
PIP           := $(VENV)/bin/pip
PYTEST        := $(VENV)/bin/pytest
RUFF          := $(VENV)/bin/ruff
MYPY          := $(VENV)/bin/mypy
PYTHON_BIN    := $(VENV)/bin/python
VENV_BIN      := $(VENV)/bin

# ---- OS detection ----------------------------------------------------------
ifeq ($(OS),Windows_NT)
  DETECTED_OS := Windows
else
  DETECTED_OS := $(shell uname -s)
endif

# Per-OS install paths and packaging backend. FreeBSD uses the local port
# skeleton; Debian/Ubuntu uses dpkg-buildpackage; macOS and everything else
# falls back to a pip-driven generic sdist+wheel installer.
ifeq ($(DETECTED_OS),FreeBSD)
  PYTHON        ?= python3.11
  PREFIX        ?= /usr/local
  SYSCONFDIR    ?= $(PREFIX)/etc
  LIBEXECDIR    ?= $(PREFIX)/libexec
  DATADIR       ?= $(PREFIX)/share/$(PACKAGE)
  RCDIR         ?= $(PREFIX)/etc/rc.d
  PKG_DIST      := dist/$(PROJECT_NAME)-$(VERSION).txz
  INSTALL_BACKEND := freebsd
else ifeq ($(DETECTED_OS),Linux)
  PREFIX        ?= /usr
  SYSCONFDIR    ?= /etc
  LIBEXECDIR    ?= $(PREFIX)/lib
  DATADIR       ?= $(PREFIX)/share/$(PACKAGE)
  SYSTEMDDIR    ?= $(LIBEXECDIR)/systemd/system
  PKG_DIST      := ../$(PROJECT_NAME)_$(VERSION)_all.deb
  INSTALL_BACKEND := debian
else ifeq ($(DETECTED_OS),Darwin)
  PREFIX        ?= $(HOME)/.local
  SYSCONFDIR    ?= $(PREFIX)/etc
  LIBEXECDIR    ?= $(PREFIX)/libexec
  DATADIR       ?= $(PREFIX)/share/$(PACKAGE)
  PKG_DIST      := dist/$(PROJECT_NAME)-$(VERSION)-py3-none-any.whl
  INSTALL_BACKEND := generic
else
  PREFIX        ?= /usr/local
  SYSCONFDIR    ?= $(PREFIX)/etc
  LIBEXECDIR    ?= $(PREFIX)/libexec
  DATADIR       ?= $(PREFIX)/share/$(PACKAGE)
  PKG_DIST      := dist/$(PROJECT_NAME)-$(VERSION)-py3-none-any.whl
  INSTALL_BACKEND := generic
endif

# Default goal
.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help.
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ---------------------------------------------------------------------------
# Virtualenv
# ---------------------------------------------------------------------------

.PHONY: venv
venv: ## Create a Python venv at $(VENV).
	@test -d "$(VENV)" || $(PYTHON) -m venv "$(VENV)"
	@touch "$(VENV_BIN)/activate"

.PHONY: install
install: venv ## Install runtime deps into the venv (editable, with dev extras).
	$(PIP) install --upgrade pip wheel
	$(PIP) install -r requirements-dev.txt
	$(PIP) install -e .

.PHONY: install-runtime
install-runtime: venv ## Install only the runtime deps (no tests / lint / tui).
	$(PIP) install --upgrade pip wheel
	$(PIP) install -r requirements.txt

# ---------------------------------------------------------------------------
# Run / operate
# ---------------------------------------------------------------------------

.PHONY: service
service: install ## Run web UI + sync loop in the foreground.
	PYTHONPATH=. $(PYTHON_BIN) -m $(PACKAGE) service

.PHONY: web
web: install ## Run only the FastAPI web UI (no background sync).
	PYTHONPATH=. $(PYTHON_BIN) -m $(PACKAGE) web

.PHONY: sync
sync: install ## Run a single sync cycle and exit. Cron-friendly.
	PYTHONPATH=. $(PYTHON_BIN) -m $(PACKAGE) sync --once

.PHONY: tui
tui: install ## Launch the Textual TUI dashboard.
	PYTHONPATH=. $(PYTHON_BIN) -m $(PACKAGE) tui

.PHONY: check-config
check-config: install ## Validate settings without starting the service.
	PYTHONPATH=. $(PYTHON_BIN) -m $(PACKAGE) check-config

.PHONY: init
init: install ## Generate a fresh .env with strong random secrets.
	PYTHONPATH=. $(PYTHON_BIN) -m $(PACKAGE) init

# ---------------------------------------------------------------------------
# Quality
# ---------------------------------------------------------------------------

.PHONY: test
test: install ## Run the pytest suite.
	PYTHONPATH=. $(PYTEST) --tb=short tests/

.PHONY: test-cov
test-cov: install ## Run pytest with coverage.
	PYTHONPATH=. $(PYTEST) --cov=$(PACKAGE) --cov-report=term-missing --cov-report=xml tests/

.PHONY: test-e2e
test-e2e: install ## Run end-to-end browser tests against a real uvicorn + Chromium.
	@command -v '$(PYTHON_BIN)' >/dev/null || (echo "no venv; run 'make install' first"; exit 1)
	$(PYTHON_BIN) -m playwright install chromium 2>/dev/null || true
	PYTHONPATH=. $(PYTEST) --no-cov -m e2e --browser chromium tests/e2e_web
	@echo ">>> Screenshots written to docs/screenshots/"

.PHONY: lint
lint: install ## Run ruff + mypy.
	$(RUFF) check src tests
	@$(RUFF) format --check src tests || true
	-$(MYPY) src

.PHONY: format
format: install ## Auto-format with ruff and apply safe fixes.
	$(RUFF) format src tests
	$(RUFF) check --fix src tests

.PHONY: license
license: ## Inject BSD 3-Clause license headers into every Python file.
	$(PYTHON) scripts/inject_license.py

# ---------------------------------------------------------------------------
# Secret scanning
#
# POSIX convention: scripts have no extension. Invoked as bare
# `./scripts/secret-scan`, never `./scripts/secret-scan.sh`. The shebang
# (`#!/usr/bin/env bash`) is the dispatch mechanism.
# ---------------------------------------------------------------------------

.PHONY: secret-scan
secret-scan: ## Scan staged + working diff for leaked credentials.
	@scripts/secret-scan

.PHONY: pre-commit
pre-commit: secret-scan ## Alias wired for git pre-commit hook installs.

.PHONY: install-hooks
install-hooks: ## Install git pre-commit hook -> scripts/secret-scan.
	@mkdir -p .git/hooks
	@ln -sf ../../scripts/secret-scan .git/hooks/pre-commit
	@echo "Installed .git/hooks/pre-commit -> scripts/secret-scan (relative symlink)"

.PHONY: uninstall-hooks
uninstall-hooks: ## Remove git pre-commit hook installed by `make install-hooks`.
	@rm -f .git/hooks/pre-commit
	@echo "Removed .git/hooks/pre-commit"

# ---------------------------------------------------------------------------
# Packaging & service installation
# ---------------------------------------------------------------------------

.PHONY: package
package: ## Build a native package for the current OS.
	@echo ">>> active backend: $(INSTALL_BACKEND) (host: $(DETECTED_OS))"
	@case "$(INSTALL_BACKEND)" in \
	  freebsd) $(MAKE) package-freebsd ;; \
	  debian)  $(MAKE) package-debian ;; \
	  generic) $(MAKE) package-generic ;; \
	  *) echo "unknown package backend: $(INSTALL_BACKEND)" ; exit 1 ;; \
	esac

.PHONY: package-freebsd
package-freebsd: ## Build the FreeBSD .txz via contrib/freebsd/ port skeleton.
	@command -v bmake >/dev/null 2>&1 || (echo "bmake required on FreeBSD"; exit 1)
	cd contrib/freebsd && env BATCH=YES DISTDIR=$(PWD)/../../dist bmake package

.PHONY: package-debian
package-debian: ## Build the Debian .deb (requires dpkg-buildpackage).
	@command -v dpkg-buildpackage >/dev/null 2>&1 || (echo "install dpkg-dev"; exit 1)
	dpkg-buildpackage -us -uc -b
	@echo ">>> Result: $(PKG_DIST)"

.PHONY: package-generic
package-generic: ## Build a pip-installable sdist + wheel.
	$(PYTHON_BIN) -m pip install --upgrade build
	$(PYTHON_BIN) -m build --sdist --wheel --outdir dist/

.PHONY: install-systemd
install-systemd: ## Install the systemd unit (root required; Linux only).
	@sudo install -d -m 0755 '$(SYSTEMDDIR)'
	@sudo install -m 0644 deploy/cloudflare-ddns.service '$(SYSTEMDDIR)/cloudflare-ddns.service'
	@sudo systemctl daemon-reload
	@echo "Installed systemd unit; enable with:  sudo systemctl enable --now cloudflare-ddns"

.PHONY: uninstall-systemd
uninstall-systemd: ## Remove the systemd unit (root required).
	@sudo systemctl disable --now cloudflare-ddns 2>/dev/null || true
	@sudo rm -f '$(SYSTEMDDIR)/cloudflare-ddns.service'
	@sudo systemctl daemon-reload

.PHONY: install-rc
install-rc: ## Install the FreeBSD rc.d script (root required; FreeBSD only).
	@sudo install -d -m 0755 '$(RCDIR)'
	@sudo install -m 0555 deploy/cloudflare-ddns.rc '$(RCDIR)/cloudflare_ddns'
	@echo "Installed rc.d script; enable in /etc/rc.conf:  cloudflare_ddns_enable=YES"

.PHONY: uninstall-rc
uninstall-rc: ## Remove the FreeBSD rc.d script (root required).
	@sudo sysrc -x cloudflare_ddns_enable || true
	@sudo service cloudflare_ddns stop 2>/dev/null || true
	@sudo rm -f '$(RCDIR)/cloudflare_ddns'

.PHONY: install-generic
install-generic: package-generic ## pip install --user from a built wheel (no root).
	$(PYTHON_BIN) -m pip install --user 'dist/$(PROJECT_NAME)-$(VERSION)-py3-none-any.whl'

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

.PHONY: clean
clean: ## Remove venv + build/dist directories.
	rm -rf '$(VENV)' build dist *.egg-info src/*.egg-info contrib/freebsd/work
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type f -name '*.pyc' -delete

.PHONY: distclean
distclean: clean ## Also remove caches and coverage artefacts.
	rm -rf .pytest_cache .ruff_cache .mypy_cache .coverage htmlcov coverage.xml

# ---------------------------------------------------------------------------
# Self-information
# ---------------------------------------------------------------------------

.PHONY: info
info: ## Print detected environment variables (debug).
	@echo "detected_os     = $(DETECTED_OS)"
	@echo "install_backend = $(INSTALL_BACKEND)"
	@echo "prefix          = $(PREFIX)"
	@echo "sysconfdir      = $(SYSCONFDIR)"
	@echo "libexecdir      = $(LIBEXECDIR)"
	@echo "datadir         = $(DATADIR)"
	@echo "package         = $(PROJECT_NAME) $(VERSION)"
	@echo "pkg_dist        = $(PKG_DIST)"
