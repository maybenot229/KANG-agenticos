"""Every registered cadence marker is selected by a CI job or is RESERVED
(ADR-050 D1/D3; 13 §3; 17 §11.2).

`--strict-markers` only validates markers that are *used*; it does not require
registered markers to be used or run. Without this test a fourth marker could
be registered (or a test marked) and silently never run, and a weekly-marked
test could run on every push because the commit/merge jobs deselect too few
markers. The read is deliberately plain: `pyproject.toml` via `tomllib`,
`ci.yml` as text (PyYAML is not a declared dependency — 11 §25).
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

# Registered cadence markers with no CI job yet: RESERVED by ADR-050 D3, with
# 03_ROADMAP §8's trigger "the first test carrying the marker". When a job is
# added for one, it leaves this set in the same commit.
RESERVED = {"weekly": "ADR-050 D3", "monthly": "ADR-050 D3"}

# Lines of ci.yml that run the default (unmarked) tiers, by the path they run.
DEFAULT_TIER_PATHS = ("tests/unit tests/suites", "tests/integration")

_EXPR = re.compile(r'-m\s+(?:"([^"]+)"|(\w+))')
_WORD = re.compile(r"[a-z_]+")


def _registered_markers() -> set[str]:
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    entries = config["tool"]["pytest"]["ini_options"]["markers"]
    return {entry.split(":", 1)[0].split("(", 1)[0].strip() for entry in entries}


def _pytest_selections() -> list[tuple[str, str]]:
    """(command line, -m expression) for every pytest run in ci.yml."""
    found = []
    for line in (
        (REPO_ROOT / ".github/workflows/ci.yml")
        .read_text(encoding="utf-8")
        .splitlines()
    ):
        if "pytest" not in line:
            continue
        match = _EXPR.search(line)
        if match:
            found.append((line, match.group(1) or match.group(2)))
    return found


def test_every_registered_cadence_marker_is_selected_by_a_job_or_reserved():
    registered = _registered_markers()
    selections = _pytest_selections()
    operators = {"not", "and", "or"}

    selected = set()
    for _, expr in selections:
        if not expr.lstrip().startswith("not"):
            selected |= set(_WORD.findall(expr)) - operators

    unaccounted = registered - selected - set(RESERVED)
    assert not unaccounted, (
        f"registered marker(s) {sorted(unaccounted)} are neither selected by a "
        "ci.yml job nor listed RESERVED — add a job or a RESERVED entry (ADR-050 D1/D3)"
    )
    stale = set(RESERVED) & selected
    assert not stale, f"{sorted(stale)} now have a CI job — remove from RESERVED"
    assert set(RESERVED) <= registered, "RESERVED lists an unregistered marker"

    # The bug this ADR fixed: default-tier jobs deselected only `nightly`.
    for path in DEFAULT_TIER_PATHS:
        lines = [expr for line, expr in selections if path in line]
        assert lines, f"no ci.yml pytest step runs {path!r}"
        for expr in lines:
            assert expr.lstrip().startswith("not"), expr
            missing = registered - (set(_WORD.findall(expr)) - operators)
            assert not missing, (
                f"the {path!r} job does not deselect {sorted(missing)}: a test "
                "carrying that marker would run on every push"
            )
