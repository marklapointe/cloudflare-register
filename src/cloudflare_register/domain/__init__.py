"""Domain package.

Pure domain models and validation rules. This layer must not depend on any
infrastructure concern (filesystem, network, settings, logging) — it's the
type-theoretic heart of the application.
"""

from cloudflare_register.domain.models import HostConfig, InterfaceGroup, SyncReport

__all__ = ["HostConfig", "InterfaceGroup", "SyncReport"]
