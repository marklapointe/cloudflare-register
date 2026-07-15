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
"""Configuration loading tests."""

from __future__ import annotations

import pytest

from cloudflare_register import config as config_module
from cloudflare_register.exceptions import ConfigError


def test_default_settings_use_xdg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-cfg"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    config_module.reset_settings_cache()
    settings = config_module.get_settings()
    assert str(settings.data_dir).startswith(str(tmp_path))


def test_log_level_normalized(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "warning")
    config_module.reset_settings_cache()
    settings = config_module.get_settings()
    assert settings.log_level == "WARNING"


def test_log_level_invalid_raises(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "FOOBAR")
    config_module.reset_settings_cache()
    with pytest.raises(Exception):
        config_module.get_settings()


def test_settings_detects_insecure_defaults(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "change-me-to-a-random-48-byte-secret")
    monkeypatch.delenv("CLOUDFLARE_REGISTER_ALLOW_INSECURE_DEFAULTS", raising=False)
    config_module.reset_settings_cache()
    settings = config_module.get_settings()
    problems = settings.unsafe_defaults_in_use()
    assert "SECRET_KEY" in problems


def test_settings_cache_is_cleared(monkeypatch):
    config_module.reset_settings_cache()
    s1 = config_module.get_settings()
    monkeypatch.setenv("HTTP_PORT", "19999")
    config_module.reset_settings_cache()
    s2 = config_module.get_settings()
    assert s2.http_port == 19999
    assert s1 is not s2
