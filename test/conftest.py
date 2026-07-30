"""Shared pytest fixtures for the xerosere test suite.

The suite is hermetic and offline.  It exercises the *real* code paths --
real ``git clone`` from local ``file://`` fixture repositories and the real
config/discovery/reconcile logic -- but replaces the two things that would
otherwise reach the network or take minutes:

* Spack itself is a **fake** ``spack`` executable (see ``FAKE_SPACK``) that
  implements just enough of ``repo list/add/remove`` -- crucially with Spack's
  *prepend-on-add* precedence -- to verify our ordering behaviour.
* ``extern bootstrap`` clones Spack from a local fake ``spack`` git repo by
  monkeypatching :data:`xerosere.extern.SPACK_GIT_URL` (see the ``spack_url``
  fixture); no github, no multi-minute clone.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from xerosere import config as config_mod
from xerosere import extern as extern_mod
from xerosere.cli import cli

# A stand-in ``spack`` that models the only behaviour extern relies on:
# ``repo add`` PREPENDS (newest wins) and errors on a duplicate path, ``repo
# remove`` drops by path, ``repo list`` prints top (= highest precedence)
# first.  State lives in $SPACK_USER_CONFIG_PATH/repos.txt (top-first).
FAKE_SPACK = """#!/usr/bin/env python3
import os, sys
from pathlib import Path

def statefile():
    d = Path(os.environ.get("SPACK_USER_CONFIG_PATH", "."))
    d.mkdir(parents=True, exist_ok=True)
    return d / "repos.txt"

def load():
    f = statefile()
    return [x for x in f.read_text().splitlines() if x.strip()] if f.exists() else []

def save(paths):
    statefile().write_text("".join(p + chr(10) for p in paths))

args = sys.argv[1:]

# Record every invocation (argv) so tests can assert how spack was called.
_cache = Path(os.environ.get("SPACK_USER_CACHE_PATH", "."))
try:
    _cache.mkdir(parents=True, exist_ok=True)
    with open(str(_cache / "calls.log"), "a") as _fh:
        _fh.write(" ".join(args) + chr(10))
except OSError:
    pass

if args[:1] == ["--version"]:
    print("0.0.0-fake"); sys.exit(0)
if args[:1] == ["repo"]:
    sub, rest = (args[1] if len(args) > 1 else ""), args[2:]
    paths = load()
    if sub == "list":
        for p in paths:
            print("[+] %s    v0    %s" % (Path(p).name, p))
        sys.exit(0)
    if sub == "add":
        path = os.path.abspath(rest[-1])
        if path in paths:
            sys.stderr.write("Error: a repository already exists: %s\\n" % path)
            sys.exit(1)
        paths.insert(0, path)          # prepend -> newest has highest precedence
        save(paths); print("Added repo %s" % path); sys.exit(0)
    if sub == "remove":
        path = os.path.abspath(rest[-1])
        save([p for p in paths if p != path]); print("Removed %s" % path); sys.exit(0)
    sys.stderr.write("fake spack: unknown repo subcommand %r\\n" % sub); sys.exit(2)
if args[:2] == ["env", "create"]:
    rest = [a for a in args[2:] if a not in ("-d", "--dir")]
    envdir = Path(rest[0]); envfile = rest[1] if len(rest) > 1 else None
    envdir.mkdir(parents=True, exist_ok=True)
    manifest = envdir / "spack.yaml"
    if envfile is None:
        manifest.write_text("spack:\\n  specs: []\\n")                  # empty
    elif Path(envfile).is_file():
        manifest.write_text(Path(envfile).read_text())                # from manifest
    else:
        manifest.write_text("spack:\\n  # from-env: %s\\n" % envfile)  # from name
    print("Created environment in %s" % envdir); sys.exit(0)
sys.exit(0)
"""


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def make_git_repo(
    path: Path,
    files: dict[str, str],
    *,
    tag: str | None = None,
    executables: tuple[str, ...] = (),
) -> str:
    """Create a git repo at *path* with *files*; return its ``file://`` URL."""
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    _git(path, "config", "commit.gpgsign", "false")
    for rel, content in files.items():
        f = path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content)
    for rel in executables:
        (path / rel).chmod(0o755)
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "init")
    if tag:
        _git(path, "tag", tag)
    return f"file://{path}"


def _repo_yaml(namespace: str) -> str:
    return f"repo:\n  namespace: {namespace}\n  api: v2.0\n"


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    """Keep every test off the real XDG config and XEROSERE_* environment."""
    monkeypatch.setattr(config_mod, "XDG_CONFIG", tmp_path / "no-such-xdg.toml")
    for key in [k for k in __import__("os").environ if k.startswith("XEROSERE_")]:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def workarea(tmp_path, monkeypatch):
    """A fresh working directory that is also the process cwd."""
    wd = tmp_path / "work"
    wd.mkdir()
    monkeypatch.chdir(wd)
    return wd


@pytest.fixture
def run_cli():
    """Invoke the xerosere CLI in-process; assert success unless told otherwise."""
    runner = CliRunner()

    def _run(*args, ok=True):
        result = runner.invoke(cli, list(args))
        if ok and result.exit_code != 0:
            raise AssertionError(
                f"`xerosere {' '.join(args)}` failed (exit {result.exit_code})\n"
                f"output:\n{result.output}\nexception: {result.exception!r}"
            )
        return result

    return _run


@pytest.fixture
def spack_url(tmp_path_factory, monkeypatch):
    """A local fake-Spack git repo (tag v1.2.2); patch it in as SPACK_GIT_URL."""
    src = tmp_path_factory.mktemp("spack-src") / "spack"
    url = make_git_repo(
        src,
        {"bin/spack": FAKE_SPACK, "README": "fake spack\n"},
        tag="v1.2.2",
        executables=("bin/spack",),
    )
    monkeypatch.setattr(extern_mod, "SPACK_GIT_URL", url)
    return url


@pytest.fixture(scope="session")
def pkg_repos(tmp_path_factory):
    """The three walk-through package repos as local git URLs.

    Layouts mirror the real repos: edep-simphony carries both an old-style
    top/nested ``repo.yaml`` (must be ignored) and a new-style
    ``spack_repo/edep_simphony`` (nested one level down); fnal_art and phlex are
    plain top-level ``spack_repo/<ns>`` repos.
    """
    base = tmp_path_factory.mktemp("pkg-remotes")
    return {
        "edep": make_git_repo(
            base / "edep-simphony-spack",
            {
                "edep_simphony/repo.yaml": _repo_yaml("edep_simphony"),  # old-style
                "edep_simphony/spack_repo/edep_simphony/repo.yaml": _repo_yaml(
                    "edep_simphony"
                ),
            },
        ),
        "fnal_art": make_git_repo(
            base / "fnal_art",
            {"spack_repo/fnal_art/repo.yaml": _repo_yaml("fnal_art")},
        ),
        "phlex": make_git_repo(
            base / "phlex-spack-recipes",
            {"spack_repo/phlex/repo.yaml": _repo_yaml("phlex")},
        ),
    }


@pytest.fixture
def booted(workarea, run_cli, spack_url):
    """An initialized area with the (fake) spack provider bootstrapped."""
    run_cli("init")
    run_cli("extern", "bootstrap")
    return workarea


@pytest.fixture
def registered_order():
    """Return the fake-spack registration, top (= highest precedence) first."""

    def _order(workarea: Path) -> list[str]:
        f = workarea / "extern" / "scopes" / "user" / "repos.txt"
        return [x for x in f.read_text().splitlines() if x.strip()] if f.exists() else []

    return _order
