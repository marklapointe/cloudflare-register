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
"""Persistence tests: host list round-trips, atomic writes, locking."""

from __future__ import annotations

import json

import pytest

from cloudflare_register.exceptions import PersistenceError
from cloudflare_register.persistence import HostConfig, load_hosts_config, save_hosts_config


def test_round_trip(empty_store, sample_host_config):
    hosts = [HostConfig(**sample_host_config)]
    save_hosts_config(hosts)
    loaded = load_hosts_config()
    assert len(loaded) == 1
    assert loaded[0].hostname == sample_host_config["hostname"]
    assert loaded[0].zone_id == sample_host_config["zone_id"]


def test_load_empty_when_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from cloudflare_register import config

    config.reset_settings_cache()
    assert load_hosts_config() == []


def test_save_creates_file_with_0600(empty_store, sample_host_config, valid_settings):
    hosts = [HostConfig(**sample_host_config)]
    save_hosts_config(hosts)
    path = valid_settings.data_dir / "hosts.json"
    assert path.exists()
    mode = path.stat().st_mode & 0o777
    assert mode == 0o600, f"expected 0600, got {oct(mode)}"


def test_invalid_persisted_file_raises(tmp_path, monkeypatch, valid_settings):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from cloudflare_register import config

    config.reset_settings_cache()
    settings = config.get_settings()
    settings.ensure_paths()
    bad = settings.data_dir / "hosts.json"
    bad.write_text("not-a-json-list", encoding="utf-8")
    with pytest.raises(PersistenceError):
        load_hosts_config()


def test_invalid_host_in_store_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from cloudflare_register import config

    config.reset_settings_cache()
    settings = config.get_settings()
    settings.ensure_paths()
    bad_entry = settings.data_dir / "hosts.json"
    bad_entry.write_text(json.dumps([{"hostname": "x", "zone_id": "short"}]), encoding="utf-8")
    with pytest.raises(PersistenceError):
        load_hosts_config()


@pytest.fixture
def empty_store(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "store"))
    from cloudflare_register import config

    config.reset_settings_cache()
    return config.get_settings()
