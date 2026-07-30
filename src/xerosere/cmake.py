# SPDX-FileCopyrightText: 2026 Brookhaven Science Associates, LLC.
# SPDX-License-Identifier: Apache-2.0

"""Drive the CMake super-build (devel/CMakeLists.txt) or single packages.

Ports ``umbrella config`` / ``umbrella build`` including its hard-won defences:
  * unset CPATH & friends so cmake's configure is deterministic/self-contained;
  * warn about stale sub-build caches pinned to the Spack view;
  * per-package stand-alone builds resolving siblings via the install prefix.
"""

from __future__ import annotations

import os
import re
import shutil
from importlib import resources
from pathlib import Path

from .config import Config
from .util import die, run

# Ambient compiler search-path vars a Spack-activated shell exports; if cmake's
# configure sees them it records $view/include as an implicit include dir and
# STRIPS it from imported targets, so the later (plain-shell) build cannot find
# e.g. arrow/api.h.  find_package() supplies every needed path via
# CMAKE_PREFIX_PATH, so unsetting these loses nothing.
_INCLUDE_VARS = ("CPATH", "CPLUS_INCLUDE_PATH", "C_INCLUDE_PATH", "OBJC_INCLUDE_PATH")

_CACHE_ENTRY = re.compile(r"^([A-Za-z0-9_]+)_(LIBRARY|DIR):(FILEPATH|PATH)=(.*)$")


def _cmake_environ() -> dict[str, str]:
    env = dict(os.environ)
    for var in _INCLUDE_VARS:
        env.pop(var, None)
    return env


def _cmake_exe(cfg: Config) -> str:
    """Prefer the view's cmake (may be newer than system), else $PATH cmake."""
    exe = cfg.path("view_dir") / "bin" / "cmake"
    if exe.is_file() and exe.stat().st_mode & 0o111:
        return str(exe)
    found = shutil.which("cmake")
    if found:
        return found
    die(f"no cmake in {exe.parent} or on PATH")


def _require_view(cfg: Config) -> Path:
    view = cfg.path("view_dir")
    if not (view / "bin" / "g++").is_file():
        die(f"environment view not built: {view}/bin/g++ missing (build the Spack env first)")
    return view


def ensure_superbuild(cfg: Config) -> Path:
    """Ensure devel/CMakeLists.txt exists, dropping in the template if not.

    An existing (possibly hand-edited) file is never overwritten.
    """
    devel = cfg.path("devel_root")
    devel.mkdir(parents=True, exist_ok=True)
    cml = devel / "CMakeLists.txt"
    if not cml.exists():
        template = (
            resources.files("xerosere.templates")
            .joinpath("superbuild.cmake.in")
            .read_text()
        )
        cml.write_text(template.replace("@PROJECT_NAME@", cfg.get("project_name")))
        print(f"xerosere: wrote super-build {cml}")
    return devel


def _render_define(key: str, value) -> str:
    if isinstance(value, bool):
        value = "ON" if value else "OFF"
    elif isinstance(value, (list, tuple)):
        value = ";".join(str(v) for v in value)
    return f"-D{key}={value}"


def _cmake_table_defines(cfg: Config, param: str) -> list[str]:
    """-D flags from the [cmake.<name>] table referenced by *param* (if any)."""
    name = cfg.params.get(param)
    if not name:
        return []
    return [_render_define(k, v) for k, v in cfg.cmake_table(name).items()]


def _split_args(cfg: Config, args: list[str]) -> tuple[list[str], list[str]]:
    """Split trailing args into (packages, passthrough cmake options)."""
    devel = cfg.path("devel_root")
    pkgs: list[str] = []
    opts: list[str] = []
    for arg in args:
        if arg.startswith("-"):
            opts.append(arg)
        elif (devel / arg).is_dir():
            pkgs.append(arg)
        else:
            print(f"xerosere: '{arg}' is not a devel/ package; passing to cmake")
            opts.append(arg)
    return pkgs, opts


def _dedupe_defines(defines: list[str]) -> list[str]:
    """Collapse repeated -D<VAR>=... flags, later occurrences winning.

    Lets a [cmake.<name>] table or CLI -D cleanly override a base flag instead
    of emitting a duplicate (cmake would otherwise silently take the last).
    """
    out: dict[str, str] = {}
    for d in defines:
        body = d[2:] if d.startswith("-D") else d
        key = body.split("=", 1)[0].split(":", 1)[0]
        out[key] = d  # last value wins; first position retained
    return list(out.values())


def _base_config_flags(cfg: Config, view: Path, install: Path) -> list[str]:
    return [
        _render_define("CMAKE_C_COMPILER", str(view / "bin" / "gcc")),
        _render_define("CMAKE_CXX_COMPILER", str(view / "bin" / "g++")),
        _render_define("CMAKE_INSTALL_PREFIX", str(install)),
        _render_define("CMAKE_BUILD_TYPE", cfg.get("build_type")),
        _render_define("CMAKE_CXX_STANDARD", cfg.get("cxx_standard")),
    ]


def warn_stale_caches(scanroot: Path, view: Path, install: Path, build: Path, env_name: str) -> None:
    """Warn about sub-build caches pinned to the view that the install shadows.

    A resolved *_LIBRARY / non-INCLUDE *_DIR entry whose value lives under the
    view while the shared install prefix now provides that same artifact means
    the sub-build would keep linking the OLD view copy (find_* never re-evaluate
    a cached hit).  Genuine view-only externals have no install counterpart and
    are not reported.  Never fatal.
    """
    if not scanroot.is_dir():
        return
    hits = 0
    stale_pkgs: set[Path] = set()
    view_s = str(view)
    for cache in scanroot.rglob("CMakeCache.txt"):
        try:
            lines = cache.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            m = _CACHE_ENTRY.match(line)
            if not m:
                continue
            name = f"{m.group(1)}_{m.group(2)}"
            if name.endswith("_INCLUDE_DIR"):
                continue
            val = m.group(4)
            if not val.startswith(view_s + os.sep):
                continue
            rel = val[len(view_s) + 1 :]
            cand = install / rel
            if not cand.exists():
                continue
            if hits == 0:
                print("xerosere: WARNING: stale sub-build cache(s) pinned to the Spack view;")
                print("xerosere:   the install prefix now provides the same artifact, so these")
                print("xerosere:   builds would keep linking the OLD view copy until removed:")
            hits += 1
            print(f"xerosere:   [{cache}]")
            print(f"xerosere:     {name} = {val}")
            print(f"xerosere:     shadows {cand}")
            try:
                relb = cache.relative_to(build)
                stale_pkgs.add(build / relb.parts[0])
            except ValueError:
                pass
    if hits:
        print("xerosere:   remedy: remove the affected build dir(s) and reconfigure:")
        for p in sorted(stale_pkgs):
            print(f"xerosere:     rm -rf {p}")
        print(f"xerosere:   then re-run: xerosere --env-name {env_name} dev config")


def config(cfg: Config, defines: list[str], args: list[str]) -> None:
    """Configure the super-build, or the listed package(s) stand-alone."""
    ensure_superbuild(cfg)
    view = _require_view(cfg)
    install = cfg.path("env_install")
    build = cfg.path("env_build")
    devel = cfg.path("devel_root")
    cmake = _cmake_exe(cfg)
    env = _cmake_environ()

    pkgs, opts = _split_args(cfg, args)
    cli_defines = [f"-D{d}" for d in defines]
    table_defines = _cmake_table_defines(cfg, "cmake_config")
    base_flags = _base_config_flags(cfg, view, install)

    if not pkgs:
        defines_all = [
            *base_flags,
            _render_define("CMAKE_PREFIX_PATH", str(view)),
            *table_defines,
            *cli_defines,
        ]
        run(
            [cmake, "-S", str(devel), "-B", str(build), *_dedupe_defines(defines_all), *opts],
            env=env,
        )
        warn_stale_caches(build, view, install, build, cfg.get("env_name"))
        return

    for pkg in pkgs:
        src = devel / pkg
        pbuild = build / pkg
        defines_all = [
            *base_flags,
            _render_define("CMAKE_PREFIX_PATH", f"{install};{view}"),
            _render_define("CMAKE_POLICY_DEFAULT_CMP0167", "NEW"),
            _render_define("CMAKE_INSTALL_RPATH_USE_LINK_PATH", "TRUE"),
            _render_define("CMAKE_INSTALL_RPATH", f"{install}/lib;{install}/lib64"),
            *table_defines,
            *cli_defines,
        ]
        run(
            [cmake, "-S", str(src), "-B", str(pbuild), *_dedupe_defines(defines_all), *opts],
            env=env,
        )
        warn_stale_caches(pbuild, view, install, build, cfg.get("env_name"))


def build(cfg: Config, defines: list[str], args: list[str]) -> None:
    """Build the super-build, or the listed package(s) stand-alone."""
    _require_view(cfg)
    build_dir = cfg.path("env_build")
    cmake = _cmake_exe(cfg)
    env = _cmake_environ()

    pkgs, opts = _split_args(cfg, args)
    build_defines = _dedupe_defines(
        _cmake_table_defines(cfg, "cmake_build") + [f"-D{d}" for d in defines]
    )
    passthrough = build_defines + opts

    if not pkgs:
        run([cmake, "--build", str(build_dir), *passthrough], env=env)
        return

    for pkg in pkgs:
        pbuild = build_dir / pkg
        if not pbuild.is_dir():
            die(f"package '{pkg}' not configured: run 'xerosere dev config {pkg}' first")
        run([cmake, "--build", str(pbuild), *passthrough], env=env)
