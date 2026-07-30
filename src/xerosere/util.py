# SPDX-FileCopyrightText: 2026 Brookhaven Science Associates, LLC.
# SPDX-License-Identifier: Apache-2.0

"""Small shared helpers: echoed subprocess execution and fatal errors."""

from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path


class Die(Exception):
    """A fatal, user-facing error; carries the message and exit status."""

    def __init__(self, message: str, status: int = 1) -> None:
        super().__init__(message)
        self.status = status


def die(message: str, status: int = 1) -> None:
    raise Die(message, status)


def require_choice(value: str, choices, name: str) -> str:
    """Return *value* if it is one of *choices*, else :func:`die`."""
    if value not in choices:
        allowed = ", ".join(repr(c) for c in choices)
        die(f"{name} must be one of {allowed}; got {value!r}")
    return value


def run(
    cmd: list[str],
    *,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
    check: bool = True,
    capture: bool = False,
) -> subprocess.CompletedProcess:
    """Echo *cmd* (like ``set -x``) to stderr, then run it.

    With *capture* the child's stdout/stderr are captured (as text) on the
    returned :class:`~subprocess.CompletedProcess` instead of inherited.
    """
    printable = " ".join(shlex.quote(str(c)) for c in cmd)
    print(f"+ {printable}", file=sys.stderr, flush=True)
    return subprocess.run(
        [str(c) for c in cmd],
        env=env,
        cwd=str(cwd) if cwd is not None else None,
        check=check,
        capture_output=capture,
        text=True if capture else None,
    )
