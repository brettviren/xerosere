"""Discovery of new-style Spack package repos inside a cloned tree."""

from __future__ import annotations

from xerosere.extern import _repo_namespace, _spack_repo_paths


def _write(path, namespace):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"repo:\n  namespace: {namespace}\n")


def test_repo_namespace_variants(tmp_path):
    p = tmp_path / "repo.yaml"
    p.write_text("repo:\n  namespace: 'quoted_ns'\n")
    assert _repo_namespace(p) == "quoted_ns"
    p.write_text('repo:\n  namespace: "dq_ns"\n')
    assert _repo_namespace(p) == "dq_ns"
    p.write_text("repo:\n  namespace: bare_ns\n")
    assert _repo_namespace(p) == "bare_ns"


def test_top_level_and_nested_found(tmp_path):
    _write(tmp_path / "spack_repo" / "fnal_art" / "repo.yaml", "fnal_art")
    _write(
        tmp_path / "edep_simphony" / "spack_repo" / "edep_simphony" / "repo.yaml",
        "edep_simphony",
    )
    found = {p.name for p in _spack_repo_paths(tmp_path)}
    assert found == {"fnal_art", "edep_simphony"}


def test_old_style_repo_yaml_ignored(tmp_path):
    # A repo.yaml NOT under spack_repo/ is old-style and must be ignored, even
    # when a valid new-style one lives alongside it.
    _write(tmp_path / "repo.yaml", "wirecell")  # old-style top-level
    _write(tmp_path / "spack_repo" / "wirecell" / "repo.yaml", "wirecell")
    paths = _spack_repo_paths(tmp_path)
    assert [p.name for p in paths] == ["wirecell"]
    assert paths[0].parent.name == "spack_repo"


def test_namespace_mismatch_ignored(tmp_path):
    # Parent dir name must equal the declared namespace.
    _write(tmp_path / "spack_repo" / "wrongdir" / "repo.yaml", "other_ns")
    assert _spack_repo_paths(tmp_path) == []
