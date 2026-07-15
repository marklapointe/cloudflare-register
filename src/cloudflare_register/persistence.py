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
"""Persistence of the configured ``HostConfig`` list.

Storage is a JSON file under ``$XDG_DATA_HOME/cloudflare_register/hosts.json``
(created on first use with 0600 permissions). Writes are atomic (write to a
sibling tempfile, fsync, os.replace) and guarded by an OS-level flock so
concurrent web-UI requests can't corrupt the file.

Design notes
------------
* Strategy pattern is NOT used here: storage layout is an internal detail. The
  public surface exposes load/save as functions; tests stub them via monkeypatch.
* TAOCP §2.3 (linked allocation) informed the choice of a flat JSON file over a
  database: the expected cardinality is "a few hosts" (V << 100), so the
  constant-time decode cost dominates per-record search either way.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import tempfile
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from pydantic import ConfigDict

from cloudflare_register.config import get_settings
from cloudflare_register.domain import HostConfig as DomainHostConfig
from cloudflare_register.domain import InterfaceGroup
from cloudflare_register.exceptions import PersistenceError
from cloudflare_register.logging_setup import get_logger

_LOGGER = get_logger(__name__)


class HostConfig(DomainHostConfig):
    """Storage-layer view of HostConfig.

    Inherits all domain validators but allows extra fields on disk — old
    deployments may have keys this version doesn't know about yet. The
    migration layer strips unknown fields on save.
    """

    model_config = ConfigDict(extra="ignore", validate_assignment=True)


def _resolve_storage_path() -> Path:
    settings = get_settings()
    settings.ensure_paths()
    return settings.data_dir / "hosts.json"


# flock exclusion is per open-file-description, so a naive nested acquire in
# the same process would deadlock. Track held locks per path and re-enter.
_LOCK_STATE: dict[str, tuple[int, int]] = {}  # path -> (fd, depth)
_LOCK_STATE_GUARD = threading.Lock()


@contextmanager
def _file_lock(path: Path) -> Iterator[Path]:
    """Hold an exclusive flock on ``path.lock``; reentrant within this process.

    The lock file lives next to the data file. Lock is released when the
    outermost context manager exits, even on exception.
    """
    key = str(path)
    with _LOCK_STATE_GUARD:
        held = _LOCK_STATE.get(key)
        if held is not None:
            fd, depth = held
            _LOCK_STATE[key] = (fd, depth + 1)
            acquired = False
        else:
            lock_path = path.with_suffix(path.suffix + ".lock")
            lock_path.touch(exist_ok=True)
            fd = os.open(lock_path, os.O_RDWR)
            acquired = True
    if acquired:
        fcntl.flock(fd, fcntl.LOCK_EX)  # may block: taken outside the guard
        with _LOCK_STATE_GUARD:
            _LOCK_STATE[key] = (fd, 1)
    try:
        yield path
    finally:
        with _LOCK_STATE_GUARD:
            fd, depth = _LOCK_STATE[key]
            if depth > 1:
                _LOCK_STATE[key] = (fd, depth - 1)
            else:
                del _LOCK_STATE[key]
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)


@contextmanager
def hosts_mutation_lock() -> Iterator[None]:
    """Hold the hosts-file lock across a whole read-modify-write sequence.

    ``load_hosts_config``/``save_hosts_config`` each lock individually, which
    protects the file from torn writes but not from lost updates when two
    callers interleave load → mutate → save. Mutating callers must wrap the
    sequence in this context manager.
    """
    with _file_lock(_resolve_storage_path()):
        yield


@contextmanager
def groups_mutation_lock() -> Iterator[None]:
    """Same as :func:`hosts_mutation_lock`, for the interface-group index."""
    with _file_lock(_resolve_groups_path()):
        yield


def load_hosts_config() -> list[HostConfig]:
    """Return the stored host list, creating an empty store on first run."""
    path = _resolve_storage_path()
    if not path.exists():
        return []
    try:
        with _file_lock(path):
            raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise PersistenceError(f"failed to read {path}: {exc}") from exc
    if not isinstance(raw, list):
        raise PersistenceError(f"{path} did not contain a JSON array")
    hosts: list[HostConfig] = []
    for index, entry in enumerate(raw):
        try:
            hosts.append(HostConfig.model_validate(entry))
        except ValueError as exc:
            raise PersistenceError(f"invalid host entry #{index}: {exc}") from exc
    _LOGGER.debug("loaded %d host(s) from %s", len(hosts), path)
    return hosts


def save_hosts_config(hosts: Sequence[DomainHostConfig]) -> None:
    """Persist the host list atomically.

    The function creates the parent directory if missing, writes to a tempfile
    in the same directory (``os.replace`` is atomic only when both paths share
    a filesystem), enforces 0600 permissions, and ``fsync``s before the swap
    so a power loss between write and replace cannot leave a torn file.
    """
    _write_json_atomic(
        _resolve_storage_path(),
        json.dumps([h.model_dump() for h in hosts], indent=2, sort_keys=True).encode("utf-8"),
    )


def _resolve_groups_path() -> Path:
    settings = get_settings()
    settings.ensure_paths()
    return settings.data_dir / "interface_groups.json"


def load_interface_groups() -> list[InterfaceGroup]:
    """Return the stored interface-group bindings, or ``[]`` on first run."""
    path = _resolve_groups_path()
    if not path.exists():
        return []
    try:
        with _file_lock(path):
            raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise PersistenceError(f"failed to read {path}: {exc}") from exc
    if not isinstance(raw, list):
        raise PersistenceError(f"{path} did not contain a JSON array")
    groups: list[InterfaceGroup] = []
    for index, entry in enumerate(raw):
        try:
            groups.append(InterfaceGroup.model_validate(entry))
        except ValueError as exc:
            raise PersistenceError(f"invalid group entry #{index}: {exc}") from exc
    return groups


def save_interface_groups(groups: list[InterfaceGroup]) -> None:
    """Persist the interface-group index atomically."""
    _write_json_atomic(
        _resolve_groups_path(),
        json.dumps([g.model_dump() for g in groups], indent=2, sort_keys=True).encode("utf-8"),
    )


def _write_json_atomic(path: Path, payload: bytes) -> None:
    """Atomic JSON write with 0600 perms and directory fsync.

    Shared by both ``save_hosts_config`` and ``save_interface_groups``.
    """
    with _file_lock(path):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(
                prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
            )
        except OSError as exc:
            raise PersistenceError(f"cannot create tempfile in {path.parent}: {exc}") from exc

        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp_name, 0o600)
            os.replace(tmp_name, path)
            with contextlib.suppress(OSError):
                dir_fd = os.open(str(path.parent), os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
            raise
