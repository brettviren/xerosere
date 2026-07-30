"""`xerosere extern bootstrap` for the spack provider, incl. access policy."""

from __future__ import annotations

import tomlkit


def _section(workarea):
    doc = tomlkit.parse((workarea / ".xerosere" / "config.toml").read_text())
    return doc["env"]["DEFAULT"]


def _fake_spack_at(spack_root):
    """Place a minimal (non-git) spack checkout at *spack_root*."""
    (spack_root / "bin").mkdir(parents=True)
    exe = spack_root / "bin" / "spack"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)


def test_bootstrap_clones_when_missing(workarea, run_cli, spack_url):
    run_cli("init")
    run_cli("extern", "bootstrap")

    assert (workarea / "extern" / "spack" / "bin" / "spack").is_file()
    # opt/spack (default install_tree root) pre-created under read-write access
    assert (workarea / "extern" / "spack" / "opt" / "spack").is_dir()

    section = _section(workarea)
    assert section["extern_type"] == "spack"
    assert section["extern_version"] == "v1.2.2"
    assert section["spack_root"] == "extern/spack"
    assert section["spack_source_access"] == "read-write"
    assert section["spack_install_access"] == "read-write"


def test_bootstrap_rerun_read_write_updates_nonfatally(workarea, run_cli, spack_url):
    run_cli("init")
    run_cli("extern", "bootstrap")
    # second run: spack now exists -> read-write tries to update (git pull);
    # for a detached tag checkout the pull is a no-op/soft-fail, never crashes.
    result = run_cli("extern", "bootstrap")
    assert "updating existing spack" in result.output
    assert (workarea / "extern" / "spack" / "bin" / "spack").is_file()


def test_bootstrap_read_only_reuses_existing(workarea, run_cli):
    run_cli("init")
    spack_root = workarea / "extern" / "spack"
    _fake_spack_at(spack_root)
    run_cli("config", "set", "spack_source_access", "read-only")
    run_cli("config", "set", "spack_install_access", "read-only")

    result = run_cli("extern", "bootstrap")   # no network / no spack_url needed
    assert "read-only" in result.output
    # a read-only install area must not be touched
    assert not (spack_root / "opt" / "spack").exists()
    assert _section(workarea)["spack_source_access"] == "read-only"


def test_bootstrap_read_only_missing_errors(workarea, run_cli):
    run_cli("init")
    run_cli("config", "set", "spack_source_access", "read-only")
    result = run_cli("extern", "bootstrap", ok=False)
    assert result.exit_code != 0
    msg = str(result.exception) + result.output
    assert "read-only" in msg and "no spack" in msg


def test_bootstrap_refuses_populated_non_spack_dir(workarea, run_cli):
    run_cli("init")
    spack_root = workarea / "extern" / "spack"
    spack_root.mkdir(parents=True)
    (spack_root / "some-other-file").write_text("not spack\n")
    result = run_cli("extern", "bootstrap", ok=False)
    assert result.exit_code != 0
    assert "not a spack checkout" in str(result.exception) + result.output


def test_bootstrap_invalid_access_value_errors(workarea, run_cli):
    run_cli("init")
    run_cli("config", "set", "spack_source_access", "readonly")  # typo
    result = run_cli("extern", "bootstrap", ok=False)
    assert result.exit_code != 0
    assert "spack_source_access" in str(result.exception) + result.output
