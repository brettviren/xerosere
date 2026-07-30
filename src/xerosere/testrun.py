# SPDX-FileCopyrightText: 2026 Brookhaven Science Associates, LLC.
# SPDX-License-Identifier: Apache-2.0

"""Run project-level tests: tests/<name>/run.sh <env_name> <outdir>.

Each run.sh reports via exit status (0=pass, 77=skip, other=fail).  Output goes
to <env_build>/<project_name>/<name>/.  Returns non-zero if any test failed.
"""

from __future__ import annotations

from .config import Config
from .util import die, run


def run_tests(cfg: Config, names: list[str]) -> int:
    testroot = cfg.path("tests_root")
    if not testroot.is_dir():
        die(f"no tests directory: {testroot}")

    if not names:
        names = sorted(
            d.name
            for d in testroot.iterdir()
            if d.is_dir() and (d / "run.sh").is_file() and (d / "run.sh").stat().st_mode & 0o111
        )
    if not names:
        die(f"no tests found (expected {testroot}/<name>/run.sh)")

    env_name = cfg.get("env_name")
    outbase = cfg.path("env_build") / cfg.get("project_name")

    rc = 0
    passed: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []
    for name in names:
        script = testroot / name / "run.sh"
        if not (script.is_file() and script.stat().st_mode & 0o111):
            print(f"xerosere: no such test: {script}")
            failed.append(name)
            rc = 1
            continue
        outdir = outbase / name
        print(f"== test: {name} ==")
        result = run([str(script), env_name, str(outdir)], check=False)
        if result.returncode == 0:
            passed.append(name)
        elif result.returncode == 77:
            skipped.append(name)
        else:
            failed.append(name)
            rc = 1

    print("----------------------------------------------------------------")
    print(f"tests: {len(passed)} passed, {len(skipped)} skipped, {len(failed)} failed")
    if passed:
        print(f"  passed:  {' '.join(passed)}")
    if skipped:
        print(f"  skipped: {' '.join(skipped)}")
    if failed:
        print(f"  failed:  {' '.join(failed)}")
    return rc
