# SPDX-FileCopyrightText: 2026 Brookhaven Science Associates, LLC.
# SPDX-License-Identifier: Apache-2.0

"""``xerosere extern``: manage the external-package tree under ``extern_root``.

Two idempotent operations:

``bootstrap``
    Ensure the extern package provider of type ``extern_type`` exists.  Only
    the ``spack`` provider is implemented today: it is either already present
    (all of ``spack_root``/``spack_exe``/``spack_install`` are defined and
    exist -> no-op), entirely absent (all undefined or missing -> git-clone
    Spack), or in an inconsistent partial state (error).

``repo``
    Ensure a git package-repo from a remote URL resides under ``extern_repos``.
"""

from __future__ import annotations

import re
from pathlib import Path

from .config import ACCESS_READ_WRITE, ACCESS_VALUES, Config, set_params
from .repo import _dirname_from_url
from .spack import _spack_exe
from .util import die, require_choice, run

# Default provider version/ref per extern_type.  ``config.DEFAULTS`` seeds
# ``extern_version`` with the spack value; this table lets bootstrap sanity the
# active type and gives future provider types their own default.
EXTERN_DEFAULT_VERSION: dict[str, str] = {
    "spack": "v1.2.2",
}

SPACK_GIT_URL = "https://github.com/spack/spack.git"


def _is_spack_checkout(path: Path) -> bool:
    """True if *path* looks like an existing Spack tree (has ``bin/spack``)."""
    return path.is_dir() and (path / "bin" / "spack").is_file()


def bootstrap(cfg: Config) -> None:
    """Ensure the ``extern_type`` provider is installed (idempotent)."""
    etype = cfg.get("extern_type")
    if etype != "spack":
        die(f"extern bootstrap: unsupported extern_type {etype!r} (only 'spack')")
    _bootstrap_spack(cfg)


def _bootstrap_spack(cfg: Config) -> None:
    spack_root = cfg.path("spack_root")
    src_access = require_choice(
        cfg.get("spack_source_access"), ACCESS_VALUES, "spack_source_access"
    )
    inst_access = require_choice(
        cfg.get("spack_install_access"), ACCESS_VALUES, "spack_install_access"
    )

    cloned = False
    version = cfg.get("extern_version") or EXTERN_DEFAULT_VERSION["spack"]

    if _is_spack_checkout(spack_root):
        # A spack already lives here.  Update it only when we may write to it.
        if src_access == ACCESS_READ_WRITE:
            print(f"xerosere: updating existing spack at {spack_root}")
            cp = run(["git", "-C", str(spack_root), "pull", "--ff-only"], check=False)
            if cp.returncode != 0:
                print(
                    f"xerosere: warning: 'git pull' in {spack_root} did not succeed "
                    f"(exit {cp.returncode}); leaving the checkout as-is"
                )
        else:
            print(
                f"xerosere: using existing spack at {spack_root} "
                "(spack_source_access=read-only)"
            )
    else:
        # No spack here.  Refuse to clone into a populated non-spack directory,
        # and never create one when we are only allowed read access.
        if spack_root.exists() and any(spack_root.iterdir()):
            die(
                f"extern bootstrap: {spack_root} exists but is not a spack "
                "checkout and is not empty; refusing to clone into it"
            )
        if src_access != ACCESS_READ_WRITE:
            die(
                f"extern bootstrap: no spack found at {spack_root} and "
                "spack_source_access=read-only; set spack_source_access=read-write "
                "or point spack_root at an existing spack"
            )
        spack_root.parent.mkdir(parents=True, exist_ok=True)
        run(
            ["git", "clone", "--branch", version, "--depth=2",
             SPACK_GIT_URL, str(spack_root)]
        )
        cloned = True

    # A freshly cloned Spack has bin/spack but no opt/spack -- that install tree
    # (Spack's default install_tree root) only appears once packages are built.
    # Pre-create it so `install` has a place and a re-bootstrap sees a complete
    # tree; but never touch a read-only install area (it may be shared/external).
    if inst_access == ACCESS_READ_WRITE:
        cfg.path("spack_install").mkdir(parents=True, exist_ok=True)

    # Record the parameters used so the tree is self-describing and stable.
    recorded = {
        "extern_type": cfg.get("extern_type"),
        "spack_root": cfg.get("spack_root"),
        "spack_exe": cfg.get("spack_exe"),
        "spack_install": cfg.get("spack_install"),
        "spack_source_access": src_access,
        "spack_install_access": inst_access,
    }
    if cloned:
        recorded["extern_version"] = version
    target = set_params(cfg.root, cfg.active_name, recorded)
    verb = "installed" if cloned else "configured"
    print(f"xerosere: {verb} spack at {spack_root}")
    print(f"xerosere: recorded extern params in [env.{cfg.active_name}] of {target}")


def repo(cfg: Config, giturl: str | None = None, tag: str | None = None) -> None:
    """Ensure the ordered ``extern_repo_urls`` list is cloned and registered.

    With *giturl*, that URL is appended to ``extern_repo_urls`` (if not already
    present) and persisted to the local config; the whole list is then walked
    in order.  With no *giturl* the existing list is walked to assure every
    entry is present and correctly registered.  Order is significant: for spack
    the registration order sets package precedence (last URL wins), and the
    user edits the list to control it.  *tag* (a branch or tag) applies only to
    *giturl* on this invocation.
    """
    urls = cfg.get("extern_repo_urls").split()

    if giturl:
        if giturl in urls:
            print(f"xerosere: {giturl} already in extern_repo_urls")
        else:
            urls.append(giturl)
            target = set_params(
                cfg.root, cfg.active_name, {"extern_repo_urls": " ".join(urls)}
            )
            print(
                f"xerosere: appended {giturl} to extern_repo_urls "
                f"in [env.{cfg.active_name}] of {target}"
            )

    if not urls:
        print("xerosere: extern_repo_urls is empty; nothing to do")
        return

    tags = {giturl: tag} if (giturl and tag) else {}
    _walk(cfg, urls, tags)


def _walk(cfg: Config, urls: list[str], tags: dict[str, str]) -> None:
    """Clone/checkout each URL in order, then (for spack) register in order."""
    repos = cfg.path("extern_repos")
    repos.mkdir(parents=True, exist_ok=True)

    for url in urls:
        _ensure_clone(repos / _dirname_from_url(url), url, tags.get(url))

    if cfg.get("extern_type") == "spack":
        _reconcile_spack_repos(cfg, urls)


def _ensure_clone(dest: Path, giturl: str, tag: str | None) -> None:
    """Ensure a single git repo is present at *dest* (idempotent)."""
    if (dest / ".git").is_dir():
        print(f"xerosere: repo already present at {dest}")
        if tag:
            run(["git", "-C", str(dest), "fetch", "--tags", "origin"])
            run(["git", "-C", str(dest), "checkout", tag])
    elif dest.exists():
        die(f"extern repo: destination exists but is not a git repo: {dest}")
    else:
        cmd = ["git", "clone", "--recurse-submodules"]
        if tag:
            cmd += ["--branch", tag]
        cmd += [giturl, str(dest)]
        run(cmd)


# A namespace value in repo.yaml: bare, single- or double-quoted.
_NAMESPACE_RE = re.compile(r"^\s*namespace:\s*['\"]?([^'\"\s#]+)", re.MULTILINE)


def _repo_namespace(repo_yaml: Path) -> str | None:
    """Return the ``namespace:`` value declared in a Spack ``repo.yaml``."""
    m = _NAMESPACE_RE.search(repo_yaml.read_text())
    return m.group(1) if m else None


def _spack_repo_paths(git_root: Path) -> list[Path]:
    """New-style Spack package-repo directories inside a cloned git tree.

    A repo is identified by a ``.../spack_repo/<namespace>/repo.yaml`` whose
    declared ``namespace`` equals its parent directory name ``<namespace>``;
    the directory to register is that parent.  Old-style ``repo.yaml`` files
    that do not live under a ``spack_repo/`` component are ignored.
    """
    out: list[Path] = []
    for repo_yaml in sorted(git_root.glob("**/spack_repo/*/repo.yaml")):
        parent = repo_yaml.parent
        namespace = _repo_namespace(repo_yaml)
        if namespace is not None and namespace == parent.name:
            out.append(parent)
    return out


def _registered_paths(spack: str, env: dict[str, str]) -> list[Path]:
    """Registered repo paths in ``spack repo list`` order (top = precedence)."""
    cp = run([spack, "repo", "list"], env=env, capture=True, check=False)
    paths: list[Path] = []
    for line in (cp.stdout or "").splitlines():
        tok = line.split()
        # Columns are: [status] name [version] path; the builtin repo's final
        # token is a git URL, not a path -- keep only real filesystem paths.
        if tok and tok[-1].startswith("/"):
            paths.append(Path(tok[-1]))
    return paths


def _reconcile_spack_repos(cfg: Config, urls: list[str]) -> None:
    """Make the spack registration of *our* repos match ``urls`` order.

    The desired registration order is the package-repo directories discovered
    under each URL's clone, in list order.  Because ``spack repo add`` prepends,
    adding them in that order makes the last URL win.  Only repos living under
    ``extern_repos`` are touched; anything the user registered by hand is left
    alone.  A no-op when already correct.
    """
    repos = cfg.path("extern_repos")
    desired: list[Path] = []
    for url in urls:
        dest = repos / _dirname_from_url(url)
        if dest.is_dir():
            desired.extend(_spack_repo_paths(dest))

    spack = _spack_exe(cfg)
    env = cfg.spack_environ()

    # Currently-registered repos that we manage (under extern_repos), in file
    # order.  Reversing gives the order they were *added* in, which is what we
    # compare against the desired add-order.
    managed_now = [p for p in _registered_paths(spack, env) if p.is_relative_to(repos)]
    if list(reversed(managed_now)) == desired:
        print("xerosere: spack package repos already registered in list order")
        return

    for path in managed_now:
        run([spack, "repo", "remove", str(path)], env=env)
    for path in desired:
        run([spack, "repo", "add", str(path)], env=env)


def envs(cfg: Config, name: str, from_: str | None = None) -> None:
    """Assure the directory environment *name* exists (idempotent).

    Only the ``spack`` provider is supported.  See :func:`_envs_spack`.
    """
    etype = cfg.get("extern_type")
    if etype != "spack":
        die(f"extern envs: unsupported extern_type {etype!r} (only 'spack')")
    _envs_spack(cfg, name, from_)


def _envs_spack(cfg: Config, name: str, from_: str | None) -> None:
    """Create a directory-based Spack environment at ``spack_envs/<name>``.

    Trivially idempotent: if the environment directory already exists this is a
    no-op.  Otherwise one of three creations is done via a single
    ``spack env create -d <dir> [envfile]`` where *from_* supplies ``envfile``:

    * no *from_*                 -> a fresh, empty environment;
    * *from_* is an existing file -> seed from that ``spack.yaml`` manifest;
    * *from_* otherwise           -> copy the existing named environment.
    """
    envdir = cfg.path("spack_envs") / name
    if envdir.exists():
        print(f"xerosere: environment already exists: {envdir}")
        return

    spack = _spack_exe(cfg)
    env = cfg.spack_environ()
    envdir.parent.mkdir(parents=True, exist_ok=True)

    cmd = [spack, "env", "create", "-d", str(envdir)]
    detail = "empty"
    if from_:
        src = Path(from_).expanduser()
        # A real file is a manifest -- pass its absolute path so a relative
        # --from is not re-interpreted against spack's cwd; anything else is
        # taken as the name of an existing environment.
        cmd.append(str(src.resolve()) if src.is_file() else from_)
        detail = f"from {from_}"
    run(cmd, env=env)
    print(f"xerosere: created environment {envdir} ({detail})")

    # Make the freshly created environment the active one so that later
    # commands (concretize/install, dev build) target it by default.
    target = set_params(cfg.root, cfg.active_name, {"env_name": name})
    print(f"xerosere: set env_name = {name!r} in [env.{cfg.active_name}] of {target}")
