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
"""Package exception hierarchy.

Centralizing exceptions prevents ad-hoc ``Exception`` catches elsewhere and
gives callers a stable error contract to test against.
"""

from __future__ import annotations


class CloudflareRegisterError(Exception):
    """Base class for all cloudflare-register errors."""


class ConfigError(CloudflareRegisterError):
    """Configuration is missing, malformed, or unsafe to use."""


class ProviderError(CloudflareRegisterError):
    """DNS provider backend returned an error or unexpected response."""


class ProviderAuthError(ProviderError):
    """DNS provider rejected credentials (HTTP 401/403)."""


class ProviderNotFoundError(ProviderError):
    """DNS provider could not find the requested resource."""


class ProviderRateLimitError(ProviderError):
    """DNS provider rate limit was hit; caller should back off."""


class PersistenceError(CloudflareRegisterError):
    """Hosts configuration could not be read or written."""


class IPDetectionError(CloudflareRegisterError):
    """Public IP discovery failed for every configured source."""


class CSRFError(CloudflareRegisterError):
    """CSRF token missing, expired, or mismatched."""

    def __init__(self, message: str = "CSRF token missing or invalid") -> None:
        super().__init__(message)
