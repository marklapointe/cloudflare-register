"""Pure domain models.

These types live in their own package so that future extraction (e.g. into a
standalone ``cfr-domain`` library or a CloudBSD-wide schema crate) requires
zero changes to controllers or persistence code.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class HostConfig(BaseModel):
    """Domain-level HostConfig with the interface_group field.

    This supersedes the storage-layer HostConfig in ``persistence.py``. It is
    the model used by application services and adapters. The persistence
    layer round-trips through ``model_dump`` / ``model_validate``, so
    upgrades between storage versions only need to change this file.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    hostname: str = Field(min_length=1, max_length=253)
    zone_id: str = Field(min_length=32, max_length=32)
    zone_name: str = Field(min_length=1, max_length=253)
    proxied: bool = False
    ttl: int = Field(default=1, ge=1, le=86400, description="1 = automatic")
    interface_group: str | None = Field(
        default=None,
        max_length=64,
        description="Tags this host as belonging to a named interface group; "
        "all hosts in the same group share one IP set.",
    )

    @field_validator("hostname")
    @classmethod
    def _normalize_hostname(cls, value: str) -> str:
        candidate = value.strip().lower().rstrip(".")
        if not candidate or "." not in candidate:
            raise ValueError("hostname must be a fully-qualified domain name")
        return candidate

    @field_validator("zone_id")
    @classmethod
    def _validate_zone_id(cls, value: str) -> str:
        if not value.replace("-", "").isalnum():
            raise ValueError("zone_id must be alphanumeric (Cloudflare IDs are hex)")
        return value.lower()

    @field_validator("interface_group")
    @classmethod
    def _normalize_group(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            return None
        if any(c.isspace() for c in normalized):
            raise ValueError("interface_group must not contain whitespace")
        return normalized


class InterfaceGroup(BaseModel):
    """Named binding to a network interface (or to the system default route).

    A *group* is a user-meaningful label ("home-wan", "vpn-tunnel") paired
    with the system interface whose public IP the group will publish.

    ``interface_name == None`` means "default route / OS-chosen outbound
    interface" — the common case for a typical home server.
    """

    name: str = Field(min_length=1, max_length=64)
    interface_name: str | None = Field(default=None, max_length=64)
    enabled: bool = True
    description: str = Field(default="", max_length=200)

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("group name must not be empty")
        if any(c.isspace() for c in normalized):
            raise ValueError("group name must not contain whitespace")
        return normalized


class SyncReport(BaseModel):
    """Output of a single sync cycle.

    Kept as a Pydantic model (vs. plain tuple) for forward compatibility:
    new fields won't break callers that destructure the tuple today.
    """

    groups_processed: int = 0
    hosts_processed: int = 0
    created: int = 0
    updated: int = 0
    deleted: int = 0
    errors: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
