"""`xerosere spack` invocations, incl. the global --insecure flag."""

from __future__ import annotations


def _spack_calls(workarea):
    log = workarea / "extern" / "cache" / "calls.log"
    return log.read_text().splitlines() if log.exists() else []


def _install_line(workarea):
    lines = [ln for ln in _spack_calls(workarea) if ln.split()[-1:] == ["install"]]
    assert lines, f"no spack install call recorded in {_spack_calls(workarea)}"
    return lines[-1]


def test_insecure_is_passed_before_subcommand(booted, run_cli):
    run_cli("extern", "envs", "default")          # env_name -> default, env dir exists
    run_cli("spack", "--insecure", "install")
    line = _install_line(booted)
    # global flag must precede -e and the subcommand
    assert "--insecure" in line.split()
    assert line.index("--insecure") < line.index("install")
    assert line.index("--insecure") < line.index("-e")


def test_insecure_absent_by_default(booted, run_cli):
    run_cli("extern", "envs", "default")
    run_cli("spack", "install")
    assert "--insecure" not in _install_line(booted).split()


def test_insecure_applies_to_concretize(booted, run_cli):
    run_cli("extern", "envs", "default")
    run_cli("spack", "--insecure", "concretize")
    conc = [ln for ln in _spack_calls(booted) if "concretize" in ln][-1]
    assert conc.split()[0] == "--insecure"


def test_read_only_install_skips_build_but_regenerates_view(booted, run_cli):
    run_cli("extern", "envs", "default")
    run_cli("config", "set", "spack_install_access", "read-only")
    run_cli("spack", "install")

    calls = _spack_calls(booted)
    # no `install` was issued to spack ...
    assert not any(ln.split()[-1:] == ["install"] for ln in calls)
    # ... but the view was still (re)generated
    assert any("env view regenerate" in ln for ln in calls)
