# SPDX-FileCopyrightText: 2026 Brookhaven Science Associates, LLC.
# SPDX-License-Identifier: Apache-2.0

"""Configuration subsystem for xerosere.

The "active configuration" is a single flat set of string-valued parameters
built by a deterministic, phased procedure and then string-interpolated.

Phased resolution (see docs/clarification-prompt.md, item 6):

  Phase 0  built-in defaults (DEFAULTS) -- the baseline for every section.
  Phase 1  shell environment variables (XEROSERE_<PARAM>) override the baseline.
  Phase 2  XDG file  ~/.config/xerosere/config.toml   [env.<name>] sections.
  Phase 3  local file  <root>/.xerosere/config.toml    [env.<name>] sections.
  Phase 3b explicit  -c/--config <file>                [env.<name>] sections.
  Phase 4  the resolved [env.DEFAULT] section is the base of every named
           section; a named section overrides it.
  Phase 5  CLI option overrides win over everything.

Only the *deltas* actually present in each file section are carried between
phases, so a value set in [env.DEFAULT] is inherited by named sections unless
the named section overrides that specific key.

After the active section is selected (by ``config_name``) the parameter set is
iteratively string-interpolated: any ``{other_param}`` token is replaced by that
parameter's value, repeating until stable (bounded by MAX_INTERP_ITERS).  A
token that never resolves, or that never converges, is an error.

Path-valued parameters (PATH_PARAMS) that are relative are resolved, on demand,
against the project root -- the nearest ancestor directory containing a
``.xerosere/`` sub-directory.

TOML layout: environment parameter sections live under an ``[env.<name>]``
table; free-form CMake variable sets live under ``[cmake.<name>]`` tables that
an env section references via ``cmake_config`` / ``cmake_build``.
"""

from __future__ import annotations

import os
from pathlib import Path

import tomlkit


class ConfigError(Exception):
    """Raised for any configuration resolution problem."""


# --- Phase 0: built-in default parameter values -----------------------------
#
# Values may reference other parameters via {name}; they are expanded in the
# final interpolation phase.  Keep this list minimal and generic; it mirrors
# umbrella's layout (note the intermediate .../envs/<env_name>/ level).
DEFAULTS: dict[str, str] = {
    # extern tree (dependency provider)
    "extern_root": "extern",
    "extern_type": "spack",  # "spack" (only supported today) or "pixi" (future)
    # version/ref of the extern provider to bootstrap.  This is the default for
    # extern_type == "spack"; other provider types may want a different default
    # (see EXTERN_DEFAULT_VERSION in extern.py).
    "extern_version": "v1.2.2",
    # where `extern repo` clones augmenting package repos
    "extern_repos": "{extern_root}/repos",
    # ordered, whitespace-separated list of git URLs of augmenting package
    # repos.  `extern repo` walks this list in order; for spack the registration
    # order sets package precedence (last URL wins, as `spack repo add`
    # prepends).  Whitespace-separated so it is safe as a CLI arg / env var
    # without inventing a delimiter that might occur inside a git URL.
    "extern_repo_urls": "",
    # spack locations
    "spack_root": "{extern_root}/spack",
    "spack_exe": "{spack_root}/bin/spack",
    "spack_install": "{spack_root}/opt/spack",
    "spack_envs": "{extern_root}/envs",
    # how xerosere may treat the spack source tree and install area:
    #   "read-write" (default) -- xerosere may clone/pull spack and build/install
    #   "read-only"            -- reuse an existing (possibly shared/external)
    #                             spack: never modify its source or install tree
    "spack_source_access": "read-write",
    "spack_install_access": "read-write",
    # spack scope/cache isolation -- exported into any spawned spack so the
    # user's ~/.spack/ is never touched (see .envrc; a major source of grief
    # when spack is used from multiple trees).
    "spack_user_cache": "{extern_root}/cache",
    "spack_user_config": "{extern_root}/scopes/user",
    "spack_system_config": "{extern_root}/scopes/system",
    # active environment
    "env_name": "default",
    "env_dir": "{spack_envs}/{env_name}",  # holds spack.yaml (spack -e / -d target)
    "view_dir": "{env_dir}/view",  # environment view (not spack specific)
    # development sources and build/install outputs
    "devel_root": "devel",
    "builds_root": "builds",
    "env_build": "{builds_root}/envs/{env_name}",
    "installs_root": "installs",
    "env_install": "{installs_root}/envs/{env_name}",
    "tests_root": "tests",
    # super-build project() name (also names the per-project test output subdir)
    "project_name": "xerosere",
    # default CMake knobs surfaced as first-class parameters
    "build_type": "Release",
    "cxx_standard": "23",
    # which [env.<name>] section is active
    "config_name": "DEFAULT",
}

# Parameters whose values are filesystem paths; relative values are resolved
# against the project root on demand (Config.path).
PATH_PARAMS: frozenset[str] = frozenset(
    {
        "extern_root",
        "extern_repos",
        "spack_root",
        "spack_exe",
        "spack_install",
        "spack_envs",
        "spack_user_cache",
        "spack_user_config",
        "spack_system_config",
        "env_dir",
        "view_dir",
        "devel_root",
        "builds_root",
        "env_build",
        "installs_root",
        "env_install",
        "tests_root",
    }
)

# Spack environment-variable name -> config parameter supplying its value.
SPACK_ENV_VARS: dict[str, str] = {
    "SPACK_USER_CACHE_PATH": "spack_user_cache",
    "SPACK_USER_CONFIG_PATH": "spack_user_config",
    "SPACK_SYSTEM_CONFIG_PATH": "spack_system_config",
}

# Accepted values for the *_access parameters.
ACCESS_READ_WRITE = "read-write"
ACCESS_READ_ONLY = "read-only"
ACCESS_VALUES = (ACCESS_READ_WRITE, ACCESS_READ_ONLY)

ENV_PREFIX = "XEROSERE_"
XDG_CONFIG = Path("~/.config/xerosere/config.toml").expanduser()
DOTDIR = ".xerosere"
CONFIG_BASENAME = "config.toml"
MAX_INTERP_ITERS = 10


def env_var_name(param: str) -> str:
    """Shell environment variable name for a config parameter."""
    return ENV_PREFIX + param.upper()


def find_root(start: Path | None = None) -> Path:
    """Return the nearest ancestor of *start* containing a ``.xerosere/`` dir.

    Falls back to *start* (the cwd) when no such ancestor exists.
    """
    start = (start or Path.cwd()).resolve()
    for d in (start, *start.parents):
        if (d / DOTDIR).is_dir():
            return d
    return start


def _load_toml(path: Path) -> tomlkit.TOMLDocument | None:
    if not path.is_file():
        return None
    try:
        return tomlkit.parse(path.read_text())
    except Exception as exc:  # pragma: no cover - surfaced to the user
        raise ConfigError(f"cannot parse {path}: {exc}") from exc


def _sections(doc: tomlkit.TOMLDocument | None, table: str) -> dict[str, dict]:
    """Return the ``[<table>.<name>]`` sub-tables as plain dicts."""
    if doc is None:
        return {}
    top = doc.get(table)
    if top is None:
        return {}
    out: dict[str, dict] = {}
    for name, body in top.items():
        # only sub-tables (mappings) are sections
        if hasattr(body, "items"):
            out[name] = {k: v for k, v in body.items()}
    return out


def _interpolate(params: dict[str, str]) -> dict[str, str]:
    """Iteratively expand {param} references until stable."""
    cur = dict(params)
    for _ in range(MAX_INTERP_ITERS):
        changed = False
        new: dict[str, str] = {}
        for key, val in cur.items():
            if isinstance(val, str) and "{" in val:
                try:
                    expanded = val.format(**cur)
                except KeyError as exc:
                    raise ConfigError(
                        f"parameter {key!r} references undefined parameter {exc}"
                    ) from None
                except (IndexError, ValueError) as exc:
                    raise ConfigError(
                        f"parameter {key!r} has a malformed value {val!r}: {exc}"
                    ) from None
                new[key] = expanded
                changed = changed or expanded != val
            else:
                new[key] = val
        cur = new
        if not changed:
            break
    else:
        raise ConfigError(
            "interpolation did not converge after "
            f"{MAX_INTERP_ITERS} iterations (recursively defined parameters?)"
        )
    for key, val in cur.items():
        if isinstance(val, str) and "{" in val:
            raise ConfigError(
                f"parameter {key!r} left unresolved after interpolation: {val!r}"
            )
    return cur


class Config:
    """A resolved, interpolated parameter set bound to a project root."""

    def __init__(
        self,
        params: dict[str, str],
        cmake_tables: dict[str, dict],
        root: Path,
        active_name: str,
    ) -> None:
        self.params = params
        self.cmake_tables = cmake_tables
        self.root = root
        self.active_name = active_name

    # -- accessors -----------------------------------------------------------
    def get(self, name: str) -> str:
        try:
            return self.params[name]
        except KeyError:
            raise ConfigError(f"no such parameter: {name}") from None

    def path(self, name: str) -> Path:
        """Absolute path for a path-valued parameter (relative -> under root)."""
        p = Path(self.get(name)).expanduser()
        if not p.is_absolute():
            p = self.root / p
        return p

    def cmake_table(self, name: str) -> dict:
        """Return the [cmake.<name>] variable table (empty if absent)."""
        return dict(self.cmake_tables.get(name, {}))

    def spack_environ(self, base: dict[str, str] | None = None) -> dict[str, str]:
        """os.environ augmented with the Spack scope/cache isolation vars."""
        env = dict(os.environ if base is None else base)
        for var, param in SPACK_ENV_VARS.items():
            env[var] = str(self.path(param))
        return env

    def items(self):
        return sorted(self.params.items())


def resolve(
    root: Path,
    cli_overrides: dict[str, str] | None = None,
    config_file: Path | None = None,
    environ: dict[str, str] | None = None,
) -> Config:
    """Run the full phased resolution and return a :class:`Config`.

    *cli_overrides* maps parameter name -> value for any option given on the
    command line (None values already dropped).  *config_file* is the optional
    ``-c/--config`` file.
    """
    cli_overrides = {k: v for k, v in (cli_overrides or {}).items() if v is not None}
    environ = os.environ if environ is None else environ

    # Phase 0 + 1: baseline = builtin defaults overridden by shell env vars.
    base: dict[str, str] = dict(DEFAULTS)
    for key in DEFAULTS:
        val = environ.get(env_var_name(key))
        if val is not None:
            base[key] = val

    # Phases 2/3/3b: collect per-section deltas and cmake tables across files,
    # later files winning.
    deltas: dict[str, dict[str, str]] = {}
    cmake_tables: dict[str, dict] = {}
    files = [XDG_CONFIG, root / DOTDIR / CONFIG_BASENAME]
    if config_file is not None:
        files.append(Path(config_file))
    for path in files:
        doc = _load_toml(path)
        for name, body in _sections(doc, "env").items():
            deltas.setdefault(name, {}).update(
                {k: str(v) for k, v in body.items()}
            )
        for name, body in _sections(doc, "cmake").items():
            cmake_tables.setdefault(name, {}).update(body)

    # Resolve which section is active.  Precedence: CLI > file [env.DEFAULT] >
    # (env/builtin via base).
    active_name = (
        cli_overrides.get("config_name")
        or deltas.get("DEFAULT", {}).get("config_name")
        or base["config_name"]
    )

    # Phase 4: DEFAULT section is the base of the active section.
    params: dict[str, str] = dict(base)
    params.update(deltas.get("DEFAULT", {}))
    if active_name != "DEFAULT":
        if active_name not in deltas:
            raise ConfigError(
                f"config_name {active_name!r} names no [env.{active_name}] section"
            )
        params.update(deltas[active_name])

    # Phase 5: CLI overrides win.
    params.update(cli_overrides)
    params["config_name"] = active_name

    # Final interpolation of the env parameter set.
    params = _interpolate(params)

    # Interpolate cmake table values against the resolved params, leaving any
    # unknown token untouched (cmake tables are a separate, open-ended space).
    resolved_cmake: dict[str, dict] = {}
    for name, body in cmake_tables.items():
        resolved_cmake[name] = {
            k: (_safe_format(v, params) if isinstance(v, str) else v)
            for k, v in body.items()
        }

    return Config(params, resolved_cmake, root, active_name)


def set_params(root: Path, section: str, values: dict[str, str]) -> Path:
    """Persist *values* into the ``[env.<section>]`` table of the local config.

    Creates ``<root>/.xerosere/config.toml`` (and the table) if needed, updates
    the given keys in place, and returns the file path.  Idempotent: writing the
    same values twice yields the same file.
    """
    target = root / DOTDIR / CONFIG_BASENAME
    target.parent.mkdir(parents=True, exist_ok=True)
    doc = (
        tomlkit.parse(target.read_text()) if target.is_file() else tomlkit.document()
    )
    if "env" not in doc:
        doc["env"] = tomlkit.table(is_super_table=True)
    env = doc["env"]
    if section not in env:
        env[section] = tomlkit.table()
    for key, val in values.items():
        env[section][key] = val
    target.write_text(tomlkit.dumps(doc))
    return target


class _LeaveMissing(dict):
    def __missing__(self, key):  # noqa: D401
        return "{" + key + "}"


def _safe_format(value: str, params: dict[str, str]) -> str:
    if "{" not in value:
        return value
    try:
        return value.format_map(_LeaveMissing(params))
    except (IndexError, ValueError):
        return value
