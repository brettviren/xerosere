# SPDX-FileCopyrightText: 2026 Brookhaven Science Associates, LLC.
# SPDX-License-Identifier: Apache-2.0

"""Variant devel/ trees via git worktrees.

A *variant* builds one (or a few) devel packages from a git worktree checked
out on a different branch, while SHARING the Spack view and every other package,
into a variant-specific build/install tree.

It is expressed entirely as configuration -- no code path is special-cased:

  * an ``[env.<name>]`` section overrides ``env_build`` / ``env_install`` (so a
    variant's artifacts never clobber the base), keeps ``env_name`` (so the
    Spack view is shared), and points ``cmake_config`` at ...
  * a ``[cmake.<name>_sources]`` table of ``XEROSERE_<ProjectName>_SUBDIR``
    overrides, one per worktree package, each an absolute worktree path.

The super-build (devel/CMakeLists.txt) honors those overrides, so
``xerosere --config-name <name> dev config`` builds the variant.
"""

from __future__ import annotations

import re
from pathlib import Path

import tomlkit

from .config import CONFIG_BASENAME, Config, DOTDIR
from .util import die, run

_PROJECT_RE = re.compile(r"^[ \t]*project[ \t]*\([ \t]*([A-Za-z0-9_]+)", re.MULTILINE)


def _project_name(pkg_dir: Path) -> str:
    """The ``project()`` name declared by a package's top CMakeLists.txt.

    This is the key the super-build uses for ``XEROSERE_<name>_SUBDIR``.
    """
    cml = pkg_dir / "CMakeLists.txt"
    if not cml.is_file():
        die(f"{pkg_dir} has no CMakeLists.txt (not a CMake package)")
    m = _PROJECT_RE.search(cml.read_text())
    if not m:
        die(f"no project() declaration found in {cml}")
    return m.group(1)


def _parse_pkgspecs(pkgs: list[str]) -> list[tuple[str, str]]:
    specs: list[tuple[str, str]] = []
    for spec in pkgs:
        if "=" not in spec:
            die(f"--pkg must be PACKAGE=BRANCH; got {spec!r}")
        name, branch = spec.split("=", 1)
        specs.append((name.strip(), branch.strip()))
    return specs


def _table_name(name: str) -> str:
    return f"{name}_sources"


def _resolve_branch(src: Path, branch: str, remote: str) -> tuple[str, bool]:
    """Resolve BRANCH to a checkout source for a new worktree.

    A local branch is used as-is.  Otherwise the branch must exist *now* on
    *remote* -- it is fetched fresh (so a stale remote-tracking ref can never be
    used silently) and the worktree is based on ``<remote>/<branch>``.  A branch
    that is neither local nor live on *remote* is a hard error (it may live on a
    fork that is not configured as a remote).

    Returns ``(base_ref, make_branch)``: base the worktree on *base_ref*, and if
    *make_branch* create a local branch of name *branch* tracking it.
    """
    local = run(
        ["git", "-C", str(src), "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        check=False,
    )
    if local.returncode == 0:
        return branch, False

    live = run(
        ["git", "-C", str(src), "ls-remote", "--heads", remote, branch],
        check=False, capture=True,
    )
    if live.returncode == 0 and live.stdout.strip():
        run(["git", "-C", str(src), "fetch", remote, branch])
        return f"{remote}/{branch}", True

    die(
        f"branch {branch!r} is not a local branch and does not exist on remote "
        f"{remote!r} of {src}.\n"
        f"  If it lives on a fork, add that remote and retry with --remote <name>:\n"
        f"    git -C {src} remote add <name> <url>"
    )


def _checked_out_at(src: Path, branch: str) -> str | None:
    """Return the worktree path where *branch* is checked out, else None.

    A git branch may be checked out in only one worktree at a time, so a branch
    already checked out (typically the base checkout) cannot be added again.
    """
    r = run(
        ["git", "-C", str(src), "worktree", "list", "--porcelain"],
        check=False, capture=True,
    )
    if r.returncode != 0:
        return None
    path: str | None = None
    for line in r.stdout.splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):].strip()
        elif line.strip() == f"branch refs/heads/{branch}":
            return path
    return None


def _config_path(cfg: Config) -> Path:
    return cfg.root / DOTDIR / CONFIG_BASENAME


def _load_doc(cfg: Config) -> tomlkit.TOMLDocument:
    path = _config_path(cfg)
    return tomlkit.parse(path.read_text()) if path.is_file() else tomlkit.document()


def add(
    cfg: Config, name: str, pkgs: list[str], force: bool = False,
    remote: str = "origin", detach: bool = False,
) -> None:
    """Create variant *name*: worktree each PACKAGE=BRANCH and write its config."""
    if not pkgs:
        die("give at least one --pkg PACKAGE=BRANCH")
    if name == "DEFAULT":
        die("'DEFAULT' is not a valid variant name")
    specs = _parse_pkgspecs(pkgs)
    devel = cfg.path("devel_root")
    wt_root = cfg.root / "worktrees" / name

    cmake_defs: dict[str, str] = {}
    for pkg, branch in specs:
        src = devel / pkg
        dotgit = src / ".git"
        if not (dotgit.is_dir() or dotgit.is_file()):
            die(f"{src} is not a git working tree")
        proj = _project_name(src)
        wt = wt_root / pkg
        if wt.exists():
            if not force:
                die(f"worktree already exists: {wt} (use --force to reuse it)")
        else:
            base, make_branch = _resolve_branch(src, branch, remote)
            add_cmd = ["git", "-C", str(src), "worktree", "add"]
            if make_branch:
                # New local branch tracking the freshly-fetched remote tip; a
                # fresh branch name can never already be checked out.
                add_cmd += ["-b", branch, str(wt), base]
            else:
                # A local branch may be checked out in only one worktree.
                at = _checked_out_at(src, branch)
                if at and not detach:
                    die(
                        f"branch {branch!r} is already checked out at {at}.\n"
                        f"  A git branch can live in only one worktree, so it cannot\n"
                        f"  also be checked out for this variant.  Options:\n"
                        f"    * that tree already builds {branch!r} (likely your base\n"
                        f"      checkout) -- just build the base; no variant needed; or\n"
                        f"    * pick a different branch for the variant; or\n"
                        f"    * pass --detach to build {branch!r}'s tip in a detached\n"
                        f"      worktree (eg the same branch with different CMake flags)."
                    )
                if detach:
                    add_cmd += ["--detach", str(wt), branch]
                else:
                    add_cmd += [str(wt), base]
            run(add_cmd)
        cmake_defs[f"XEROSERE_{proj}_SUBDIR"] = str(wt.resolve())

    table = _table_name(name)
    env_vals = {
        "env_build": f"{{builds_root}}/envs/{{env_name}}-{name}",
        "env_install": f"{{installs_root}}/envs/{{env_name}}-{name}",
        "cmake_config": table,
    }

    doc = _load_doc(cfg)
    if "env" not in doc:
        doc["env"] = tomlkit.table(is_super_table=True)
    if name not in doc["env"]:
        doc["env"][name] = tomlkit.table()
    for key, val in env_vals.items():
        doc["env"][name][key] = val
    if "cmake" not in doc:
        doc["cmake"] = tomlkit.table(is_super_table=True)
    if table not in doc["cmake"]:
        doc["cmake"][table] = tomlkit.table()
    for key, val in cmake_defs.items():
        doc["cmake"][table][key] = val

    path = _config_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tomlkit.dumps(doc))

    print(f"xerosere: variant '{name}' written to {path}")
    for key, val in cmake_defs.items():
        print(f"    {key} = {val}")
    print("  build it with:")
    print(f"    xerosere --config-name {name} dev config")
    print(f"    xerosere --config-name {name} dev build")


def list_variants(cfg: Config) -> None:
    """Print each configured variant and its source overrides."""
    doc = _load_doc(cfg)
    envs = doc.get("env", {})
    cmakes = doc.get("cmake", {})
    found = False
    for sec, body in envs.items():
        if sec == "DEFAULT":
            continue
        table = body.get("cmake_config")
        srcs = cmakes.get(table, {}) if table else {}
        if not srcs:
            continue
        found = True
        print(f"{sec}:")
        for key, val in srcs.items():
            print(f"    {key} = {val}")
    if not found:
        print("(no variants configured)")


def remove(cfg: Config, name: str, keep_worktrees: bool = False) -> None:
    """Remove variant *name*'s config sections and (by default) its worktrees."""
    path = _config_path(cfg)
    if not path.is_file():
        die("no local config file")
    doc = tomlkit.parse(path.read_text())
    envs = doc.get("env", {})
    if name not in envs:
        die(f"no such variant: {name}")
    table = envs[name].get("cmake_config")
    devel = cfg.path("devel_root")

    if not keep_worktrees and table and "cmake" in doc and table in doc["cmake"]:
        for _key, val in dict(doc["cmake"][table]).items():
            wt = Path(str(val))
            if not wt.exists():
                continue
            # Prune from the main working tree (removing the worktree from within
            # itself is refused), which shares this package's dir name.
            main = devel / wt.name
            run(
                ["git", "-C", str(main), "worktree", "remove", "--force", str(wt)],
                check=False,
            )
        del doc["cmake"][table]

    del doc["env"][name]
    path.write_text(tomlkit.dumps(doc))
    print(f"xerosere: removed variant '{name}'")
