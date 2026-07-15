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
"""Sync engine tests against a mock provider."""

from __future__ import annotations

import pytest

from cloudflare_register.persistence import HostConfig
from cloudflare_register.providers.base import DnsRecord, Provider
from cloudflare_register.sync import UNKNOWN_ADDRESS, reconcile_host


class _StaticProvider(Provider):
    name = "static-test"

    def __init__(self, existing: list[DnsRecord] | None = None) -> None:
        self.existing = list(existing or [])
        self.created: list[tuple[str, str, str, str, bool]] = []
        self.updated: list[tuple[str, str, str, str, str, bool]] = []
        self.deleted: list[tuple[str, str]] = []

    async def list_zones(self) -> list[dict[str, str]]:
        return []

    async def list_records(self, zone_id: str, name: str) -> list[DnsRecord]:
        return list(self.existing)

    async def create_record(self, zone_id, record_type, name, content, proxied=False, *, ttl=1):
        self.created.append((zone_id, record_type, name, content, proxied))
        return DnsRecord(
            record_id=f"new-{len(self.created)}",
            record_type=record_type,
            name=name,
            content=content,
            proxied=proxied,
            ttl=ttl,
        )

    async def update_record(
        self, zone_id, record_id, record_type, name, content, proxied=False, *, ttl=1
    ):
        self.updated.append((zone_id, record_id, record_type, name, content, proxied))
        return DnsRecord(
            record_id=record_id,
            record_type=record_type,
            name=name,
            content=content,
            proxied=proxied,
            ttl=ttl,
        )

    async def delete_record(self, zone_id, record_id):
        self.deleted.append((zone_id, record_id))

    async def close(self) -> None:
        pass


async def test_reconcile_creates_when_no_records(provider_with_no_records):
    provider = provider_with_no_records
    host = HostConfig(
        hostname="box.example.com", zone_id="0" * 32, zone_name="example.com", proxied=False
    )
    actions = await reconcile_host(provider, host, "1.2.3.4", "2001:db8::1")
    assert any("created A" in a for a in actions)
    assert any("created AAAA" in a for a in actions)
    assert len(provider.created) == 2


async def test_reconcile_updates_when_ip_changes(host_with_old_records):
    host, provider = host_with_old_records
    actions = await reconcile_host(provider, host, "9.9.9.9", "2001:db8::9")
    assert len(provider.updated) == 2
    assert all("updated" in a for a in actions)


async def test_reconcile_deletes_missing_family(host_with_records):
    host, provider = host_with_records
    actions = await reconcile_host(provider, host, "1.2.3.4", None)
    assert any("deleted AAAA" in a for a in actions)
    assert len(provider.deleted) == 1
    assert provider.deleted[0][1] == "aaaa1"


@pytest.fixture
def provider_with_no_records():
    return _StaticProvider()


@pytest.fixture
def host_with_old_records():
    provider = _StaticProvider(
        existing=[
            DnsRecord(record_id="a1", record_type="A", name="box.example.com", content="1.1.1.1"),
            DnsRecord(record_id="aaaa1", record_type="AAAA", name="box.example.com", content="::1"),
        ]
    )
    host = HostConfig(hostname="box.example.com", zone_id="0" * 32, zone_name="example.com")
    return host, provider


@pytest.fixture
def host_with_records():
    provider = _StaticProvider(
        existing=[
            DnsRecord(record_id="a1", record_type="A", name="box.example.com", content="1.1.1.1"),
            DnsRecord(record_id="aaaa1", record_type="AAAA", name="box.example.com", content="::1"),
        ]
    )
    host = HostConfig(hostname="box.example.com", zone_id="0" * 32, zone_name="example.com")
    return host, provider


async def test_reconcile_unknown_family_leaves_records(host_with_records):
    """UNKNOWN_ADDRESS (detection failed) must not touch any records."""
    host, provider = host_with_records
    actions = await reconcile_host(provider, host, UNKNOWN_ADDRESS, UNKNOWN_ADDRESS)
    assert actions == []
    assert not provider.created and not provider.updated and not provider.deleted


async def test_reconcile_deletes_duplicate_records():
    provider = _StaticProvider(
        existing=[
            DnsRecord(record_id="a1", record_type="A", name="box.example.com", content="1.2.3.4"),
            DnsRecord(record_id="a2", record_type="A", name="box.example.com", content="5.6.7.8"),
        ]
    )
    host = HostConfig(hostname="box.example.com", zone_id="0" * 32, zone_name="example.com")
    actions = await reconcile_host(provider, host, "1.2.3.4", None)
    assert ("0" * 32, "a2") in provider.deleted
    assert not provider.updated  # the kept record already has the right content
    assert any("duplicate" in a for a in actions)


async def test_reconcile_semantically_equal_ipv6_is_noop():
    provider = _StaticProvider(
        existing=[
            DnsRecord(
                record_id="aaaa1",
                record_type="AAAA",
                name="box.example.com",
                content="2001:db8:0:0:0:0:0:1",
            ),
        ]
    )
    host = HostConfig(hostname="box.example.com", zone_id="0" * 32, zone_name="example.com")
    actions = await reconcile_host(provider, host, None, "2001:db8::1")
    assert not provider.updated
    assert actions == []


async def test_reconcile_honors_configured_ttl():
    provider = _StaticProvider(
        existing=[
            DnsRecord(
                record_id="a1", record_type="A", name="box.example.com", content="1.2.3.4", ttl=1
            ),
        ]
    )
    host = HostConfig(
        hostname="box.example.com", zone_id="0" * 32, zone_name="example.com", ttl=300
    )
    actions = await reconcile_host(provider, host, "1.2.3.4", None)
    assert len(provider.updated) == 1  # same address, but TTL drifted
    assert any("updated A" in a for a in actions)
