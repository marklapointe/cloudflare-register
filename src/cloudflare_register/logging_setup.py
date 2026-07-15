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
"""Centralized logging setup.

Imported once by the CLI; deferred ``logging.basicConfig`` so the rest of the
package can use ``logging.getLogger(__name__)`` without mutating global
configuration as a side effect.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Final

_DEFAULT_LEVEL: Final[str] = "INFO"
_LOG_FORMAT: Final[str] = "%(asctime)s %(levelname)-8s %(name)s | %(message)s"
_DATE_FORMAT: Final[str] = "%Y-%m-%dT%H:%M:%S%z"

_CONFIGURED = False


def setup(level: str | None = None) -> logging.Logger:
    """Configure root logger once and return the application logger.

    Idempotent: subsequent calls only adjust the level without reformatting
    handlers, so libraries we depend on keep their own loggers.
    """
    global _CONFIGURED
    effective_level = (level or os.environ.get("LOG_LEVEL") or _DEFAULT_LEVEL).upper()
    numeric = logging.getLevelNamesMapping().get(effective_level, logging.INFO)

    root = logging.getLogger()
    if not _CONFIGURED:
        handler = logging.StreamHandler(stream=sys.stderr)
        handler.setFormatter(logging.Formatter(_LOG_FORMAT, _DATE_FORMAT))
        root.addHandler(handler)
        _CONFIGURED = True
    root.setLevel(numeric)

    logger = logging.getLogger("cloudflare_register")
    logger.setLevel(numeric)
    logger.debug("logging configured at level %s", effective_level)
    return logger


def get_logger(name: str) -> logging.Logger:
    """Return a child logger; use as ``get_logger(__name__)``."""
    return logging.getLogger(name)
