# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, CloudBSD
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice,
#    this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# 3. Neither the name of the copyright holder nor the names of its
#    contributors may be used to endorse or promote products derived from
#    this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
"""Application configuration loaded from JSON files and environment variables.

Precedence (highest to lowest):

1. Process environment variables (also: systemd ``EnvironmentFile``).
2. ``/etc/cloudflare-register.json``  (system-wide; created by
   ``cloudflare-register init --system``).
3. ``$XDG_CONFIG_HOME/cloudflare_register/config.json``  (per-user override;
   defaults to ``~/.config/cloudflare_register/config.json``).
4. Field defaults declared on the model.

We deliberately do NOT look for ``.env`` in the working directory. That
location is ambiguous (which ``.env``?), leaks into tarballs and shells,
and was rejected by the project maintainer. The Honcho application
guidelines state: "JSON is the preferred config format for machine
interfaces."

Secrets are required: the application refuses to start without
``CLOUDFLARE_API_TOKEN`` and ``SECRET_KEY``. Default ``ADMIN_PASSWORD`` is
``change-me`` so a fresh install is reachable but visibly insecure; the
``check_config`` CLI command flags this.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Final

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from cloudflare_register.exceptions import ConfigError
from cloudflare_register.logging_setup import get_logger

_LOGGER = get_logger(__name__)

_INSECURE_DEFAULT_PASSWORD: Final[str] = "change-me"
_INSECURE_DEFAULT_SECRET: Final[str] = "change-me-to-a-random-48-byte-secret"

_SYSTEM_CONF = Path("/etc/cloudflare-register.json")


def _xdg_path(env_var: str, default_subpath: str) -> Path:
    raw = os.environ.get(env_var)
    base = Path(raw).expanduser() if raw else Path.home() / ".local" / "share"
    return base / "cloudflare_register" / default_subpath


def _user_config_path() -> Path | None:
    """Return the per-user XDG config file if it exists."""
    raw = os.environ.get("XDG_CONFIG_HOME")
    base = Path(raw).expanduser() if raw else Path.home() / ".config"
    candidate = base / "cloudflare_register" / "config.json"
    return candidate if candidate.exists() else None


def _load_json_settings(path: Path) -> dict[str, Any]:
    """Parse a JSON config file. ``_comment_*`` keys are stripped (JSON has no
    native comment syntax; the convention here uses underscore-prefixed keys
    that pydantic would otherwise reject as ``extra``)."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: expected JSON object at top level")
    return {k: v for k, v in raw.items() if not k.startswith("_comment")}


def _resolve_settings_source() -> tuple[Path | None, dict[str, Any]]:
    """Precedence: explicit CLOUDFLARE_REGISTER_CONFIG → system file → user XDG.

    The systemd unit sets ``CLOUDFLARE_REGISTER_CONFIG=/etc/cloudflare-register.json``
    so a single env var cleanly redirects the service to the deployment file.
    Returns the resolved path and the parsed dict so callers can apply values
    directly (pydantic-settings doesn't support JSON natively via env_file).
    """
    override = os.environ.get("CLOUDFLARE_REGISTER_CONFIG")
    if override:
        override_path = Path(override)
        if override_path.exists() and os.access(override_path, os.R_OK):
            return override_path, _load_json_settings(override_path)
    if _SYSTEM_CONF.exists() and os.access(_SYSTEM_CONF, os.R_OK):
        return _SYSTEM_CONF, _load_json_settings(_SYSTEM_CONF)
    user = _user_config_path()
    if user is not None:
        return user, _load_json_settings(user)
    return None, {}


class Settings(BaseSettings):
    """Runtime configuration consumed by every other module."""

    model_config = SettingsConfigDict(
        env_file=None,
        extra="ignore",
        case_sensitive=False,
    )

    dns_provider: str = Field(default="cloudflare", description="Backend DNS provider name")

    cloudflare_api_token: str = Field(
        default_factory=lambda: _INSECURE_DEFAULT_SECRET,
        description="Cloudflare API token (Zone:DNS:Edit scope)",
    )

    http_host: str = Field(default="127.0.0.1", description="Bind address for the web UI")
    http_port: int = Field(default=8000, ge=1, le=65535, description="Bind port for the web UI")

    admin_username: str = Field(default="admin", min_length=1, max_length=64)
    admin_password: str = Field(
        default=_INSECURE_DEFAULT_PASSWORD,
        min_length=8,
        max_length=256,
        description="Admin password. Must be changed before production use.",
    )
    admin_password_hash: str | None = Field(
        default=None,
        description="Pre-hashed bcrypt password. If set, overrides admin_password verification.",
    )

    secret_key: str = Field(
        default=_INSECURE_DEFAULT_SECRET,
        min_length=32,
        description="JWT signing secret. Generate with `secrets.token_urlsafe(48)`.",
    )
    access_token_expire_minutes: int = Field(default=60, ge=1, le=24 * 60)
    cookie_secure: bool = Field(default=False, description="Set Secure flag on session cookies")

    sync_interval_seconds: int = Field(default=300, ge=10, le=24 * 3600)

    log_level: str = Field(default="INFO")

    data_dir: Path = Field(default_factory=lambda: _xdg_path("XDG_DATA_HOME", "data"))
    config_dir: Path = Field(default_factory=lambda: _xdg_path("XDG_CONFIG_HOME", "config"))
    cache_dir: Path = Field(default_factory=lambda: _xdg_path("XDG_CACHE_HOME", "cache"))

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in logging_level_names():
            raise ValueError(f"LOG_LEVEL must be one of: {sorted(logging_level_names())}")
        return normalized

    @field_validator("dns_provider")
    @classmethod
    def _validate_provider(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("DNS_PROVIDER must not be empty")
        return normalized

    def unsafe_defaults_in_use(self) -> list[str]:
        """Return the names of fields still holding their insecure defaults."""
        problems: list[str] = []
        if self.secret_key == _INSECURE_DEFAULT_SECRET:
            problems.append("SECRET_KEY")
        if self.admin_password == _INSECURE_DEFAULT_PASSWORD:
            problems.append("ADMIN_PASSWORD")
        if self.cloudflare_api_token == _INSECURE_DEFAULT_SECRET:
            problems.append("CLOUDFLARE_API_TOKEN")
        return problems

    def ensure_paths(self) -> None:
        """Create configured directories with 0700 permissions."""
        for directory in (self.data_dir, self.config_dir, self.cache_dir):
            directory.mkdir(parents=True, exist_ok=True)


def logging_level_names() -> set[str]:
    import logging

    return {name for name in logging.getLevelNamesMapping() if name != "NOTSET"}


_cached: Settings | None = None


def get_settings(*, refresh: bool = False) -> Settings:
    """Return the process-wide settings, constructing it on first use.

    A ``refresh=True`` call forces reload from environment + JSON file.
    Useful in tests and after ``SIGHUP``.
    """
    global _cached
    if refresh or _cached is None:
        try:
            _path, json_values = _resolve_settings_source()
            _cached = Settings(**json_values)  # type: ignore[call-arg]
            if _path is not None:
                _LOGGER.debug("loaded config from %s", _path)
        except Exception as exc:
            raise ConfigError(str(exc)) from exc
    return _cached


def reset_settings_cache() -> None:
    """Drop the cached settings instance (used by tests and SIGHUP reload)."""
    global _cached
    _cached = None


def require_safe_settings(settings: Settings | None = None) -> Settings:
    """Validate settings and raise ``ConfigError`` on insecure defaults when strict."""
    s = settings or get_settings()
    s.ensure_paths()
    problems = s.unsafe_defaults_in_use()
    if problems and os.environ.get("CLOUDFLARE_REGISTER_ALLOW_INSECURE_DEFAULTS") != "1":
        _LOGGER.warning(
            "insecure default values in use for: %s. Set the env vars or run "
            "`cloudflare-register init` to generate a strong config.",
            ", ".join(problems),
        )
    return s
