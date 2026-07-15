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
"""Abstract DNS provider strategy.

Implementations must be safe to instantiate from settings only — no I/O at
construction time — so the factory can construct them deterministically.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DnsRecord:
    """Provider-agnostic DNS record description."""

    record_id: str
    record_type: str
    name: str
    content: str
    ttl: int = 1
    proxied: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_cloudflare(cls, raw: dict[str, Any]) -> DnsRecord:
        return cls(
            record_id=raw["id"],
            record_type=raw["type"],
            name=raw["name"],
            content=raw["content"],
            ttl=int(raw.get("ttl", 1) or 1),
            proxied=bool(raw.get("proxied", False)),
            extra={
                k: v
                for k, v in raw.items()
                if k not in {"id", "type", "name", "content", "ttl", "proxied"}
            },
        )


class Provider(ABC):
    """Strategy interface implemented by every DNS backend."""

    name: str = ""

    @abstractmethod
    async def list_zones(self) -> list[dict[str, str]]:
        """Return ``[{id, name}]`` for every zone the token can manage."""

    @abstractmethod
    async def list_records(self, zone_id: str, name: str) -> list[DnsRecord]:
        """Return existing records for ``name`` in ``zone_id`` (may be empty)."""

    @abstractmethod
    async def create_record(
        self,
        zone_id: str,
        record_type: str,
        name: str,
        content: str,
        proxied: bool = False,
        *,
        ttl: int = 1,
    ) -> DnsRecord:
        """Create a record and return the persisted entity. ``ttl=1`` means automatic."""

    @abstractmethod
    async def update_record(
        self,
        zone_id: str,
        record_id: str,
        record_type: str,
        name: str,
        content: str,
        proxied: bool = False,
        *,
        ttl: int = 1,
    ) -> DnsRecord:
        """Update an existing record and return the persisted entity."""

    @abstractmethod
    async def delete_record(self, zone_id: str, record_id: str) -> None:
        """Delete a record by id. Idempotent: missing records must not raise."""

    @abstractmethod
    async def close(self) -> None:
        """Release any owned HTTP sessions / connections."""
