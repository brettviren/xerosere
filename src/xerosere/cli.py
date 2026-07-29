"""xerosere command-line interface (Click).

Global options mirror the config parameters: parameter ``foo_bar`` is settable
as ``--foo-bar`` (and via ``XEROSERE_FOO_BAR`` / config files).  ``-c/--config``
supplies an extra config file that sits just below CLI options in precedence.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import click
import tomlkit

from . import cmake as cmake_mod
from . import repo as repo_mod
from . import spack as spack_mod
from . import testrun
from .config import (
    DEFAULTS,
    DOTDIR,
    Config,
    ConfigError,
    find_root,
    resolve,
)
from .util import Die

# Parameters that also get a short option flag.
_SHORT_FLAGS: dict[str, tuple[str, ...]] = {"env_name": ("-e",)}

_PASSTHROUGH = dict(ignore_unknown_options=True)


def _config_options(f):
    """Attach a --<param> override option for every config parameter."""
    for name in reversed(list(DEFAULTS)):
        decls = [*_SHORT_FLAGS.get(name, ()), "--" + name.replace("_", "-"), name]
        f = click.option(
            *decls, default=None, help=f"override config parameter '{name}'"
        )(f)
    return f


def _get_config(ctx: click.Context, root: Path | None = None) -> Config:
    obj = ctx.obj
    root = root or find_root()
    cfile = Path(obj["config_file"]) if obj["config_file"] else None
    try:
        return resolve(root, obj["overrides"], cfile)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from None


@click.group()
@click.option(
    "-c", "--config", "config_file",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="extra config TOML file (below CLI options in precedence)",
)
@_config_options
@click.pass_context
def cli(ctx: click.Context, config_file, **kwargs) -> None:
    """Manage a multi-repo, multi-environment software development tree."""
    overrides = {k: v for k, v in kwargs.items() if k in DEFAULTS and v is not None}
    ctx.obj = {"overrides": overrides, "config_file": config_file}


# --- init -------------------------------------------------------------------
@cli.command()
@click.argument("directory", required=False)
@click.pass_context
def init(ctx: click.Context, directory) -> None:
    """Create/refresh a working area's .xerosere/ (idempotent).

    With no DIRECTORY the current directory is (re)configured.
    """
    target = Path(directory).resolve() if directory else Path.cwd()
    dotdir = target / DOTDIR
    dotdir.mkdir(parents=True, exist_ok=True)

    cfile = ctx.obj["config_file"]
    seed = dotdir / "config.toml"
    if cfile and not seed.exists():
        shutil.copyfile(cfile, seed)
        print(f"xerosere: seeded {seed} from {cfile}")

    cfg = _get_config(ctx, root=target)
    for param in ("devel_root", "builds_root", "installs_root"):
        cfg.path(param).mkdir(parents=True, exist_ok=True)
    print(f"xerosere: initialized {target}")


# --- config -----------------------------------------------------------------
@cli.group()
def config() -> None:
    """Inspect and edit the active configuration."""


@config.command("show")
@click.pass_context
def config_show(ctx: click.Context) -> None:
    """Print the active (merged, interpolated) parameter set."""
    cfg = _get_config(ctx)
    print(f"# [env.{cfg.active_name}]  (root: {cfg.root})")
    for key, val in cfg.items():
        print(f"{key} = {val}")


@config.command("get")
@click.argument("param")
@click.pass_context
def config_get(ctx: click.Context, param) -> None:
    """Print the active value of one parameter."""
    cfg = _get_config(ctx)
    try:
        print(cfg.get(param))
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from None


@config.command("set")
@click.argument("param")
@click.argument("value")
@click.pass_context
def config_set(ctx: click.Context, param, value) -> None:
    """Set PARAM to VALUE in the local .xerosere/config.toml active section."""
    cfg = _get_config(ctx)
    section = cfg.active_name
    target = cfg.root / DOTDIR / "config.toml"
    target.parent.mkdir(parents=True, exist_ok=True)

    doc = tomlkit.parse(target.read_text()) if target.is_file() else tomlkit.document()
    if "env" not in doc:
        doc["env"] = tomlkit.table(is_super_table=True)
    env = doc["env"]
    if section not in env:
        env[section] = tomlkit.table()
    env[section][param] = value

    target.write_text(tomlkit.dumps(doc))
    print(f"xerosere: set {param} = {value!r} in [env.{section}] of {target}")


# --- dev --------------------------------------------------------------------
@cli.group()
def dev() -> None:
    """Develop the packages under the devel/ tree."""


@dev.group()
def repo() -> None:
    """Manage development source repositories."""


@repo.command("add")
@click.argument("giturl")
@click.argument("dirname", required=False)
@click.pass_context
def repo_add(ctx: click.Context, giturl, dirname) -> None:
    """Clone GITURL under the devel root (optionally as DIRNAME)."""
    cfg = _get_config(ctx)
    repo_mod.add(cfg, giturl, dirname)


@dev.command("config", context_settings=_PASSTHROUGH)
@click.option("-D", "defines", multiple=True, help="pass -D<def> through to cmake")
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def dev_config(ctx: click.Context, defines, args) -> None:
    """Configure the super-build (or the named package(s))."""
    cfg = _get_config(ctx)
    cmake_mod.config(cfg, list(defines), list(args))


@dev.command("build", context_settings=_PASSTHROUGH)
@click.option("-D", "defines", multiple=True, help="pass -D<def> through to cmake")
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def dev_build(ctx: click.Context, defines, args) -> None:
    """Build the super-build (or the named package(s))."""
    cfg = _get_config(ctx)
    cmake_mod.build(cfg, list(defines), list(args))


# --- spack ------------------------------------------------------------------
@cli.group()
def spack() -> None:
    """Drive the Spack directory-environment."""


@spack.command("concretize", context_settings=_PASSTHROUGH)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def spack_concretize(ctx: click.Context, args) -> None:
    """spack -e <env> concretize -f [args...]."""
    cfg = _get_config(ctx)
    spack_mod.concretize(cfg, list(args))


@spack.command("install", context_settings=_PASSTHROUGH)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def spack_install(ctx: click.Context, args) -> None:
    """spack -e <env> install [args...], then rebuild the view from scratch."""
    cfg = _get_config(ctx)
    spack_mod.install(cfg, list(args))


# --- test -------------------------------------------------------------------
@cli.command("test")
@click.argument("names", nargs=-1)
@click.pass_context
def test(ctx: click.Context, names) -> None:
    """Run project tests (tests/<name>/run.sh); all if none named."""
    cfg = _get_config(ctx)
    rc = testrun.run_tests(cfg, list(names))
    if rc:
        sys.exit(rc)


def main() -> None:
    try:
        cli(standalone_mode=True)
    except Die as exc:
        print(f"xerosere: {exc}", file=sys.stderr)
        sys.exit(exc.status)
