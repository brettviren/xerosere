"""`xerosere extern repo`: the ordered extern_repo_urls list and spack registry.

These drive the real walk-through against local fixture repos + fake spack:

    xerosere extern repo <edep-simphony>
    xerosere extern repo <fnal_art>
    xerosere extern repo <phlex>
"""

from __future__ import annotations

def _urls(workarea):
    import tomlkit

    doc = tomlkit.parse((workarea / ".xerosere" / "config.toml").read_text())
    return str(doc["env"]["DEFAULT"]["extern_repo_urls"]).split()


def test_append_persists_and_registers(booted, run_cli, pkg_repos, registered_order):
    run_cli("extern", "repo", pkg_repos["edep"])
    assert _urls(booted) == [pkg_repos["edep"]]
    order = registered_order(booted)
    assert len(order) == 1
    assert order[0].endswith("spack_repo/edep_simphony")


def test_old_style_repo_yaml_not_registered(booted, run_cli, pkg_repos, registered_order):
    run_cli("extern", "repo", pkg_repos["edep"])
    order = registered_order(booted)
    # only the nested new-style repo is registered; the old-style
    # edep_simphony/repo.yaml (not under spack_repo/) is never added
    assert order == [o for o in order if o.endswith("spack_repo/edep_simphony")]
    assert not any(o.endswith("edep_simphony") and "spack_repo" not in o for o in order)


def test_walk_order_last_url_wins(booted, run_cli, pkg_repos, registered_order):
    run_cli("extern", "repo", pkg_repos["edep"])
    run_cli("extern", "repo", pkg_repos["fnal_art"])
    run_cli("extern", "repo", pkg_repos["phlex"])

    assert _urls(booted) == [pkg_repos["edep"], pkg_repos["fnal_art"], pkg_repos["phlex"]]
    # spack repo add prepends -> the last URL in the list has highest precedence
    top = registered_order(booted)[0]
    assert top.endswith("spack_repo/phlex")


def test_reorder_flips_winner(booted, run_cli, pkg_repos, registered_order):
    for key in ("edep", "fnal_art", "phlex"):
        run_cli("extern", "repo", pkg_repos[key])
    assert registered_order(booted)[0].endswith("spack_repo/phlex")

    # Put fnal_art last -> it must now win, with no new clones needed.
    reordered = " ".join(pkg_repos[k] for k in ("phlex", "edep", "fnal_art"))
    run_cli("config", "set", "extern_repo_urls", reordered)
    run_cli("extern", "repo")
    assert registered_order(booted)[0].endswith("spack_repo/fnal_art")


def test_bare_walk_is_idempotent(booted, run_cli, pkg_repos, registered_order):
    for key in ("edep", "fnal_art", "phlex"):
        run_cli("extern", "repo", pkg_repos[key])
    before = registered_order(booted)

    result = run_cli("extern", "repo")
    assert "already registered in list order" in result.output
    assert registered_order(booted) == before


def test_duplicate_url_not_appended(booted, run_cli, pkg_repos):
    run_cli("extern", "repo", pkg_repos["fnal_art"])
    result = run_cli("extern", "repo", pkg_repos["fnal_art"])
    assert "already in extern_repo_urls" in result.output
    assert _urls(booted) == [pkg_repos["fnal_art"]]


def test_empty_list_is_noop(booted, run_cli):
    result = run_cli("extern", "repo")
    assert "nothing to do" in result.output


def test_non_git_collision_errors(booted, run_cli, pkg_repos):
    (booted / "extern" / "repos" / "fnal_art").mkdir(parents=True)
    result = run_cli("extern", "repo", pkg_repos["fnal_art"], ok=False)
    assert result.exit_code != 0
    assert "not a git repo" in str(result.exception) or "not a git repo" in result.output
