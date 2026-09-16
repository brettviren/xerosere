"""Variant devel/ trees: project-name parsing, branch resolution, config I/O."""

import subprocess

import pytest
import tomlkit

from xerosere import variant
from xerosere.config import resolve
from xerosere.util import Die


def _make_pkg(root, name, project):
    devel = root / "devel" / name
    devel.mkdir(parents=True)
    (devel / "CMakeLists.txt").write_text(
        f"cmake_minimum_required(VERSION 3.20)\nproject({project} VERSION 1.0)\n"
    )
    (devel / ".git").mkdir()  # mark it a git working tree


def _fake_run(returncode=0, stdout=""):
    """A stand-in for util.run returning a canned CompletedProcess."""
    def run(cmd, **kw):
        run.calls.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout)
    run.calls = []
    return run


def test_project_name(tmp_path):
    _make_pkg(tmp_path, "wire-cell-toolkit", "WireCell")
    assert variant._project_name(tmp_path / "devel" / "wire-cell-toolkit") == "WireCell"


def test_add_local_branch_writes_config(tmp_path, monkeypatch):
    _make_pkg(tmp_path, "wire-cell-toolkit", "WireCell")
    fake = _fake_run(returncode=0)  # show-ref succeeds -> local branch, no fetch
    monkeypatch.setattr(variant, "run", fake)

    variant.add(resolve(tmp_path), "spng", ["wire-cell-toolkit=spng"])

    # a git worktree was created for the local branch (no fetch/-b needed)
    assert any("worktree" in c and "spng" in c for c in fake.calls)
    assert not any("fetch" in c for c in fake.calls)

    vcfg = resolve(tmp_path, cli_overrides={"config_name": "spng"})
    assert vcfg.get("env_build") == "builds/envs/default-spng"
    assert vcfg.get("env_install") == "installs/envs/default-spng"
    assert vcfg.get("cmake_config") == "spng_sources"
    wt = tmp_path / "worktrees" / "spng" / "wire-cell-toolkit"
    assert vcfg.cmake_table("spng_sources") == {
        "XEROSERE_WireCell_SUBDIR": str(wt.resolve())
    }


def test_add_unknown_branch_errors(tmp_path, monkeypatch):
    _make_pkg(tmp_path, "wct", "WireCell")

    def run(cmd, **kw):
        if "show-ref" in cmd:
            return subprocess.CompletedProcess(cmd, 1)          # not a local branch
        if "ls-remote" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="")  # not on the remote
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(variant, "run", run)

    with pytest.raises(Die, match="does not exist on remote"):
        variant.add(resolve(tmp_path), "spng", ["wct=spng"])
    # no config was written for the failed variant
    assert not (tmp_path / ".xerosere" / "config.toml").exists()


def test_add_remote_branch_fetches(tmp_path, monkeypatch):
    _make_pkg(tmp_path, "wct", "WireCell")

    def run(cmd, **kw):
        run.calls.append(cmd)
        if "show-ref" in cmd:
            return subprocess.CompletedProcess(cmd, 1)               # not local
        if "ls-remote" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="abc123\trefs/heads/spng")
        return subprocess.CompletedProcess(cmd, 0)
    run.calls = []
    monkeypatch.setattr(variant, "run", run)

    variant.add(resolve(tmp_path), "spng", ["wct=spng"], remote="myfork")

    assert any("fetch" in c and "myfork" in c for c in run.calls)
    # worktree created as a new tracking branch off the fresh remote tip
    assert any("worktree" in c and "-b" in c and "myfork/spng" in c for c in run.calls)


def test_list_and_remove(tmp_path, monkeypatch):
    _make_pkg(tmp_path, "wct", "WireCell")
    monkeypatch.setattr(variant, "run", _fake_run(returncode=0))

    cfg = resolve(tmp_path)
    variant.add(cfg, "spng", ["wct=spng"])
    variant.remove(cfg, "spng")

    doc = tomlkit.parse((tmp_path / ".xerosere" / "config.toml").read_text())
    assert "spng" not in doc.get("env", {})
    assert "spng_sources" not in doc.get("cmake", {})
