"""`xerosere init` creates the .xerosere/ area and standard trees (idempotent)."""

from __future__ import annotations


def test_init_creates_area(workarea, run_cli):
    run_cli("init")
    assert (workarea / ".xerosere").is_dir()
    for sub in ("devel", "builds", "installs"):
        assert (workarea / sub).is_dir(), sub


def test_init_idempotent(workarea, run_cli):
    run_cli("init")
    # a second run must not fail and must leave the area intact
    run_cli("init")
    assert (workarea / ".xerosere").is_dir()


def test_config_show_after_init(workarea, run_cli):
    run_cli("init")
    result = run_cli("config", "show")
    assert "extern_repos = extern/repos" in result.output
    assert "extern_repo_urls = " in result.output


def test_init_persists_cli_overrides(workarea, run_cli):
    # A --<param> override given to init is written to the local config so
    # later calls need not repeat it.
    run_cli("--extern-root", "../shared/extern", "init")

    cfg_toml = (workarea / ".xerosere" / "config.toml").read_text()
    assert 'extern_root = "../shared/extern"' in cfg_toml

    # a subsequent call with NO override still sees it
    assert run_cli("config", "get", "extern_root").output.strip() == "../shared/extern"


def test_init_without_overrides_writes_no_config(workarea, run_cli):
    run_cli("init")
    assert not (workarea / ".xerosere" / "config.toml").exists()
