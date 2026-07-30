# SPDX-FileCopyrightText: 2026 Brookhaven Science Associates, LLC.
# SPDX-License-Identifier: Apache-2.0

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

from .config import ACCESS_READ_ONLY, ACCESS_VALUES, Config
from .util import die, require_choice, run


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


def _base(cfg: Config, insecure: bool = False) -> list[str]:
    """Spack argv prefix: the exe plus any spack-global options."""
    cmd = [_spack_exe(cfg)]
    if insecure:
        # spack's global --insecure disables TLS cert / checksum verification;
        # must precede the subcommand.  Used when a source server has a broken
        # certificate (e.g. intel-oneapi-mkl).
        cmd.append("--insecure")
    return cmd


def concretize(cfg: Config, extra: list[str], insecure: bool = False) -> None:
    """``spack [--insecure] -e <env_dir> concretize -f [extra...]``."""
    base = _base(cfg, insecure)
    env_dir = _require_env(cfg)
    env = cfg.spack_environ()
    run([*base, "-e", env_dir, "concretize", "-f", *extra], env=env)


def install(cfg: Config, extra: list[str], insecure: bool = False) -> None:
    """``spack [--insecure] -e <env_dir> install`` then a clean view rebuild.

    When ``spack_install_access`` is ``read-only`` the package build/install
    step is skipped -- the environment and its view are still (re)produced,
    linking whatever is already installed (e.g. in a shared external spack) --
    so no new packages are built into the install tree.
    """
    base = _base(cfg, insecure)
    env_dir = _require_env(cfg)
    env = cfg.spack_environ()
    access = require_choice(
        cfg.get("spack_install_access"), ACCESS_VALUES, "spack_install_access"
    )

    if access == ACCESS_READ_ONLY:
        print(
            "xerosere: spack_install_access=read-only; skipping package install, "
            "regenerating the view only"
        )
    else:
        run([*base, "-e", env_dir, "install", *extra], env=env)

    # Guarantee the view is not stale.  Spack's view regeneration short-circuits
    # on a content-hash marker (<view>/.spack-view) and can be a NO-OP even when
    # the view is stale/partial; deleting only the marker is not enough because
    # _ensure_safe_to_replace() refuses to rebuild over a non-empty unmarked
    # directory.  Remove the whole view root and let regenerate rebuild it
    # cleanly from the current lock -- the only reliable cure.
    view = cfg.path("view_dir")
    if view.exists() or view.is_symlink():
        run(["rm", "-rf", str(view)])
    run([*base, "-e", env_dir, "env", "view", "regenerate"], env=env)
