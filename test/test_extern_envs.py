"""`xerosere extern envs <name> [--from ...]`: directory Spack environments."""

from __future__ import annotations


def _manifest(workarea, name):
    return (workarea / "extern" / "envs" / name / "spack.yaml").read_text()


def _env_name(run_cli):
    return run_cli("config", "get", "env_name").output.strip()


def test_create_empty_env(booted, run_cli):
    result = run_cli("extern", "envs", "default")
    envdir = booted / "extern" / "envs" / "default"
    assert (envdir / "spack.yaml").is_file()
    assert "specs: []" in _manifest(booted, "default")
    assert "created environment" in result.output


def test_creation_sets_env_name(booted, run_cli):
    run_cli("extern", "envs", "gcc15")
    assert _env_name(run_cli) == "gcc15"


def test_create_from_yaml_file(booted, run_cli):
    seed = booted / "seed.yaml"
    seed.write_text("spack:\n  specs: [zlib@1.2.3]\n")
    run_cli("extern", "envs", "gcc15", "--from", "seed.yaml")
    # the manifest is seeded from the file (relative --from resolved for us)
    assert "zlib@1.2.3" in _manifest(booted, "gcc15")


def test_create_from_named_env(booted, run_cli):
    run_cli("extern", "envs", "mine", "--from", "someexisting")
    # a non-file --from is passed through to spack as an environment name
    assert "from-env: someexisting" in _manifest(booted, "mine")


def test_idempotent_returns_when_dir_exists(booted, run_cli):
    run_cli("extern", "envs", "default")
    before = _manifest(booted, "default")

    # Even with a --from, an existing env dir is a trivial no-op: not reseeded.
    seed = booted / "seed.yaml"
    seed.write_text("spack:\n  specs: [should_not_appear]\n")
    result = run_cli("extern", "envs", "default", "--from", "seed.yaml")

    assert "already exists" in result.output
    assert _manifest(booted, "default") == before
    assert "should_not_appear" not in _manifest(booted, "default")


def test_noop_does_not_change_env_name(booted, run_cli):
    # First create 'first' (sets env_name=first), then a no-op re-create of an
    # already-existing 'second' must NOT touch env_name.
    run_cli("extern", "envs", "first")
    (booted / "extern" / "envs" / "second").mkdir(parents=True)
    run_cli("extern", "envs", "second")
    assert _env_name(run_cli) == "first"


def test_unsupported_extern_type_errors(booted, run_cli):
    run_cli("config", "set", "extern_type", "pixi")
    result = run_cli("extern", "envs", "x", ok=False)
    assert result.exit_code != 0
    assert "unsupported extern_type" in str(result.exception) or (
        "unsupported extern_type" in result.output
    )
