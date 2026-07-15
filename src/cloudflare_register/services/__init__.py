"""Application services: orchestration between domain, infrastructure, and adapters.

Services are stateless; configuration is passed in via constructor or method
arguments. This lets future extraction into separate processes (or a
``cfr-services`` library) work without rewriting interfaces.
"""

from cloudflare_register.services.host_service import HostService
from cloudflare_register.services.interface_service import InterfaceService
from cloudflare_register.services.sync_service import SyncService

__all__ = ["HostService", "InterfaceService", "SyncService"]
