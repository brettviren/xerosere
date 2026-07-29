"""Drive a Spack directory-environment: concretize and install.

Ports ``umbrella concretize`` / ``umbrella install`` with the same defensive
behaviour: the environment is always a *directory* env (``spack -e <env_dir>``),
the Spack scope/cache dirs are isolated from ~/.spack, and ``install`` rebuilds
the view from scratch because Spack's regenerate short-circuits on a stale
content-hash marker.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .config import Config
from .util import die, run


def _spack_exe(cfg: Config) -> str:
    """The spack executable: configured path, else fall back to $PATH."""
    exe = cfg.path("spack_exe")
    if exe.is_file() and exe.stat().st_mode & 0o111:
        return str(exe)
    found = shutil.which("spack")
    if found:
        return found
    die(f"spack not found at {exe} or on PATH")


def _require_env(cfg: Config) -> Path:
    env_dir = cfg.path("env_dir")
    if not env_dir.is_dir():
        die(f"no such environment directory: {env_dir}")
    return env_dir


def concretize(cfg: Config, extra: list[str]) -> None:
    """``spack -e <env_dir> concretize -f [extra...]``."""
    spack = _spack_exe(cfg)
    env_dir = _require_env(cfg)
    env = cfg.spack_environ()
    run([spack, "-e", env_dir, "concretize", "-f", *extra], env=env)


def install(cfg: Config, extra: list[str]) -> None:
    """``spack -e <env_dir> install`` then a clean-from-scratch view rebuild."""
    spack = _spack_exe(cfg)
    env_dir = _require_env(cfg)
    env = cfg.spack_environ()

    run([spack, "-e", env_dir, "install", *extra], env=env)

    # Guarantee the view is not stale.  Spack's view regeneration short-circuits
    # on a content-hash marker (<view>/.spack-view) and can be a NO-OP even when
    # the view is stale/partial; deleting only the marker is not enough because
    # _ensure_safe_to_replace() refuses to rebuild over a non-empty unmarked
    # directory.  Remove the whole view root and let regenerate rebuild it
    # cleanly from the current lock -- the only reliable cure.
    view = cfg.path("view_dir")
    if view.exists() or view.is_symlink():
        run(["rm", "-rf", str(view)])
    run([spack, "-e", env_dir, "env", "view", "regenerate"], env=env)
