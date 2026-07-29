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


def run(
    cmd: list[str],
    *,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Echo *cmd* (like ``set -x``) to stderr, then run it."""
    printable = " ".join(shlex.quote(str(c)) for c in cmd)
    print(f"+ {printable}", file=sys.stderr, flush=True)
    return subprocess.run(
        [str(c) for c in cmd],
        env=env,
        cwd=str(cwd) if cwd is not None else None,
        check=check,
    )
