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
"""Factory + registry for :class:`Provider` strategies.

Implements the **Factory** half of the Strategy/Factory pair: callers hand in a
name (from configuration) and get back a fully-constructed provider. New
backends register themselves on import.
"""

from __future__ import annotations

from cloudflare_register.exceptions import ConfigError
from cloudflare_register.providers.base import Provider
from cloudflare_register.providers.cloudflare import CloudflareProvider

_REGISTRY: dict[str, type[Provider]] = {
    CloudflareProvider.name: CloudflareProvider,
}


def register(name: str, cls: type[Provider]) -> None:
    """Register a provider class under ``name`` (used by out-of-tree plugins)."""
    if not name:
        raise ValueError("provider name must be non-empty")
    if not issubclass(cls, Provider):
        raise TypeError("registered class must subclass cloudflare_register.providers.Provider")
    _REGISTRY[name.lower()] = cls


def get(name: str) -> type[Provider]:
    """Return the provider class registered under ``name``."""
    try:
        return _REGISTRY[name.lower()]
    except KeyError as exc:
        raise ConfigError(
            f"unknown DNS provider: {name!r}. Known providers: {sorted(_REGISTRY)}"
        ) from exc


def build(name: str, *, token: str) -> Provider:
    """Construct a provider instance for ``name`` using ``token``."""
    return get(name)(token=token)


def known() -> list[str]:
    """Return a sorted list of registered provider names."""
    return sorted(_REGISTRY)
