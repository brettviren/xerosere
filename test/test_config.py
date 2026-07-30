"""Config resolution: defaults, interpolation, files, sections, env, set_params."""

from __future__ import annotations

from xerosere.config import resolve, set_params


def test_defaults_and_interpolation(tmp_path):
    cfg = resolve(tmp_path)
    assert cfg.get("extern_root") == "extern"
    assert cfg.get("extern_repos") == "extern/repos"
    assert cfg.get("extern_repo_urls") == ""
    assert cfg.get("extern_version") == "v1.2.2"
    assert cfg.get("spack_source_access") == "read-write"
    assert cfg.get("spack_install_access") == "read-write"
    # interpolated
    assert cfg.get("spack_exe") == "extern/spack/bin/spack"
    # path params resolve under the project root
    assert cfg.path("extern_repos") == tmp_path / "extern" / "repos"


def test_local_file_default_section(tmp_path):
    dot = tmp_path / ".xerosere"
    dot.mkdir()
    (dot / "config.toml").write_text('[env.DEFAULT]\nextern_root = "ext2"\n')
    cfg = resolve(tmp_path)
    assert cfg.get("extern_root") == "ext2"
    # dependent interpolation follows the override
    assert cfg.get("extern_repos") == "ext2/repos"


def test_named_section_overrides_default(tmp_path):
    dot = tmp_path / ".xerosere"
    dot.mkdir()
    (dot / "config.toml").write_text(
        "[env.DEFAULT]\n"
        'config_name = "dev"\n'
        'extern_version = "v9"\n'
        "[env.dev]\n"
        'extern_version = "v1.2.2-dev"\n'
    )
    cfg = resolve(tmp_path)
    assert cfg.active_name == "dev"
    assert cfg.get("extern_version") == "v1.2.2-dev"


def test_env_var_override(tmp_path, monkeypatch):
    monkeypatch.setenv("XEROSERE_EXTERN_ROOT", "envext")
    cfg = resolve(tmp_path)
    assert cfg.get("extern_root") == "envext"
    assert cfg.get("extern_repos") == "envext/repos"


def test_set_params_round_trip(tmp_path):
    target = set_params(tmp_path, "DEFAULT", {"extern_repo_urls": "a b c"})
    assert target == tmp_path / ".xerosere" / "config.toml"
    cfg = resolve(tmp_path)
    assert cfg.get("extern_repo_urls") == "a b c"
    # a second write updates in place, does not duplicate the section
    set_params(tmp_path, "DEFAULT", {"extern_repo_urls": "a b"})
    assert resolve(tmp_path).get("extern_repo_urls") == "a b"
    assert target.read_text().count("[env.DEFAULT]") == 1
