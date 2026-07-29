"""`xerosere dev repo add`: clone a source repo under the devel root."""

from __future__ import annotations

from .config import Config
from .util import die, run


def _dirname_from_url(giturl: str) -> str:
    name = giturl.rstrip("/").rsplit("/", 1)[-1]
    if name.endswith(".git"):
        name = name[:-4]
    if not name:
        die(f"cannot derive a directory name from {giturl!r}; give one explicitly")
    return name


def add(cfg: Config, giturl: str, dirname: str | None = None) -> None:
    devel = cfg.path("devel_root")
    devel.mkdir(parents=True, exist_ok=True)
    dirname = dirname or _dirname_from_url(giturl)
    dest = devel / dirname
    if dest.exists():
        die(f"destination already exists: {dest}")
    run(["git", "clone", "--recurse-submodules", giturl, str(dest)])
