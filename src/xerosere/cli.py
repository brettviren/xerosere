# SPDX-FileCopyrightText: 2026 Brookhaven Science Associates, LLC.
# SPDX-License-Identifier: Apache-2.0

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

from . import cmake as cmake_mod
from . import extern as extern_mod
from . import repo as repo_mod
from . import spack as spack_mod
from . import testrun
from . import variant as variant_mod
from .config import (
    DEFAULTS,
    DOTDIR,
    Config,
    ConfigError,
    find_root,
    resolve,
    set_params,
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

    # Persist any CLI parameter overrides into the active section so subsequent
    # xerosere calls in this area inherit them (e.g. `--extern-root` pointing at
    # an out-of-tree spack) without having to repeat them.
    overrides = ctx.obj["overrides"]
    if overrides:
        written = set_params(target, cfg.active_name, overrides)
        recorded = ", ".join(f"{k}={v!r}" for k, v in sorted(overrides.items()))
        print(f"xerosere: recorded {recorded} in [env.{cfg.active_name}] of {written}")

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
    target = set_params(cfg.root, section, {param: value})
    print(f"xerosere: set {param} = {value!r} in [env.{section}] of {target}")


# --- extern -----------------------------------------------------------------
@cli.group()
def extern() -> None:
    """Manage the external-package tree under extern_root."""


@extern.command("bootstrap")
@click.pass_context
def extern_bootstrap(ctx: click.Context) -> None:
    """Ensure the extern provider (extern_type) is installed (idempotent)."""
    cfg = _get_config(ctx)
    extern_mod.bootstrap(cfg)


@extern.command("repo")
@click.option("--tag", default=None, help="branch or tag to check out (GITURL only)")
@click.argument("giturl", required=False)
@click.pass_context
def extern_repo(ctx: click.Context, tag, giturl) -> None:
    """Add GITURL to extern_repo_urls and walk the list (idempotent).

    With no GITURL the existing extern_repo_urls list is walked to assure every
    entry is cloned and (for spack) registered in list order.
    """
    cfg = _get_config(ctx)
    extern_mod.repo(cfg, giturl, tag)


@extern.command("envs")
@click.option(
    "--from", "from_", default=None,
    help="seed from an existing named env or a spack.yaml file",
)
@click.argument("name")
@click.pass_context
def extern_envs(ctx: click.Context, from_, name) -> None:
    """Assure a directory Spack environment NAME exists (idempotent).

    With no --from an empty environment is created under spack_envs/NAME; with
    --from it is seeded from an existing named environment or a spack.yaml file.
    """
    cfg = _get_config(ctx)
    extern_mod.envs(cfg, name, from_)


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


@dev.group()
def variant() -> None:
    """Variant devel/ trees: build a package from a git-worktree branch."""


@variant.command("add")
@click.argument("name")
@click.option(
    "--pkg", "pkgs", multiple=True, metavar="PACKAGE=BRANCH",
    help="build devel/PACKAGE from a git worktree on BRANCH (repeatable)",
)
@click.option("--force", is_flag=True, help="reuse an existing worktree")
@click.option(
    "--remote", default="origin", show_default=True,
    help="remote to fetch a non-local branch from (fresh)",
)
@click.pass_context
def variant_add(ctx: click.Context, name, pkgs, force, remote) -> None:
    """Create variant NAME building the given package(s) from worktrees.

    A non-local branch is fetched fresh from --remote; a branch that exists
    neither locally nor on that remote is an error (add the fork's remote).

    Example: xerosere dev variant add spng --pkg wire-cell-toolkit=spng
    """
    variant_mod.add(_get_config(ctx), name, list(pkgs), force=force, remote=remote)


@variant.command("list")
@click.pass_context
def variant_list(ctx: click.Context) -> None:
    """List configured variants and their source overrides."""
    variant_mod.list_variants(_get_config(ctx))


@variant.command("remove")
@click.argument("name")
@click.option("--keep-worktrees", is_flag=True, help="leave the git worktrees in place")
@click.pass_context
def variant_remove(ctx: click.Context, name, keep_worktrees) -> None:
    """Remove variant NAME (its config sections and, by default, worktrees)."""
    variant_mod.remove(_get_config(ctx), name, keep_worktrees=keep_worktrees)


# --- spack ------------------------------------------------------------------
@cli.group()
@click.option(
    "--insecure", is_flag=True,
    help="pass spack's global --insecure (skip TLS cert/checksum checks)",
)
@click.pass_context
def spack(ctx: click.Context, insecure) -> None:
    """Drive the Spack directory-environment."""
    ctx.obj["insecure"] = insecure


@spack.command("concretize", context_settings=_PASSTHROUGH)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def spack_concretize(ctx: click.Context, args) -> None:
    """spack [--insecure] -e <env> concretize -f [args...]."""
    cfg = _get_config(ctx)
    spack_mod.concretize(cfg, list(args), insecure=ctx.obj["insecure"])


@spack.command("install", context_settings=_PASSTHROUGH)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def spack_install(ctx: click.Context, args) -> None:
    """spack [--insecure] -e <env> install [args...], then rebuild the view."""
    cfg = _get_config(ctx)
    spack_mod.install(cfg, list(args), insecure=ctx.obj["insecure"])


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
