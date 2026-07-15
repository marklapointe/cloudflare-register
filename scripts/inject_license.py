"""Inject the BSD 3-Clause license header into every Python source file.

Idempotent: re-running skips files that already start with the marker.
Run from the repository root::

    python scripts/inject_license.py

Author: Mark LaPointe <mark@cloudbsd.org>
"""

from __future__ import annotations

import sys
from pathlib import Path

HEADER_TEMPLATE = """# SPDX-License-Identifier: BSD-3-Clause
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
"""

MARKER = "# SPDX-License-Identifier: BSD-3-Clause"
TARGET_DIRS = ("src/cloudflare_register", "tests")


def needs_header(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        with path.open("r", encoding="utf-8") as handle:
            first_line = handle.readline().strip()
    except (OSError, UnicodeDecodeError):
        return False
    return first_line != MARKER


def inject(path: Path) -> str:
    original = path.read_text(encoding="utf-8")
    if original.startswith(HEADER_TEMPLATE):
        return "unchanged"
    if original.startswith(MARKER + "\n"):
        return "unchanged"
    path.write_text(HEADER_TEMPLATE + original, encoding="utf-8")
    return "wrote"


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    changed = 0
    skipped = 0
    for subdir in TARGET_DIRS:
        directory = root / subdir
        if not directory.exists():
            continue
        for py_file in sorted(directory.rglob("*.py")):
            if not needs_header(py_file):
                skipped += 1
                continue
            result = inject(py_file)
            if result == "wrote":
                changed += 1
            else:
                skipped += 1
    print(f"license headers: {changed} updated, {skipped} already-current")
    return 0


if __name__ == "__main__":
    sys.exit(main())
