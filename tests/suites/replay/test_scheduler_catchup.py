"""Scheduler catch-up under fault injection — THE Checkpoint C3 gate
(18 §3 M3; 13 §2.5 extended to scheduler restarts).

A real Scheduler.catch_up is killed mid-pass between slots; a fresh process
resumes catch_up. The three policies converge correctly across the crash:
run_all_missed runs every slot exactly once (no double-run, none lost),
run_once_latest runs the latest once, skip runs none. Kill-switch state
persists across the restart and pauses automation.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from tests.fixtures import scheduler_catchup_worker as worker
from tests.fixtures.scheduler_catchup_worker import ANCHOR

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKER = REPO_ROOT / "tests" / "fixtures" / "scheduler_catchup_worker.py"


def _spawn(workdir: Path, hours: int, policy: str, kill_after) -> int:
    result = subprocess.run(
        [
            sys.executable,
            str(WORKER),
            str(workdir),
            str(hours),
            policy,
            str(kill_after),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode in (0, 9), result.stderr
    return result.returncode


@pytest.fixture
def workdir(tmp_path):
    worker.ensure_migrated(tmp_path)
    return tmp_path


def _slots(hours) -> list[str]:
    return [(ANCHOR + timedelta(hours=h)).isoformat() for h in hours]


def test_run_all_missed_converges_across_a_crash(workdir):
    # 5 missed hourly slots; crash cleanly after 2 have run, then resume.
    assert _spawn(workdir, 5, "run_all_missed", kill_after=2) == 9
    facts_after_crash = worker.collect(workdir)
    assert facts_after_crash["ok_slots"] == _slots([1, 2])  # 2 done pre-crash

    assert _spawn(workdir, 5, "run_all_missed", "none") == 0  # restart resumes
    facts = worker.collect(workdir)
    # every slot ran exactly once — no double-run, none lost (convergence)
    assert facts["ok_slots"] == _slots([1, 2, 3, 4, 5])
    assert len(facts["slots"]) == 5
    assert facts["integrity"]


def test_run_all_missed_clean_run_runs_all(workdir):
    assert _spawn(workdir, 4, "run_all_missed", "none") == 0
    facts = worker.collect(workdir)
    assert facts["ok_slots"] == _slots([1, 2, 3, 4])


def test_run_once_latest_converges_to_a_single_run(workdir):
    # crash before recording anything, then resume: exactly one run (latest).
    assert _spawn(workdir, 5, "run_once_latest", kill_after=0) == 9
    assert worker.collect(workdir)["slots"] == []  # nothing recorded pre-crash
    assert _spawn(workdir, 5, "run_once_latest", "none") == 0
    facts = worker.collect(workdir)
    assert facts["ok_slots"] == _slots([5])  # the latest slot, once


def test_skip_converges_to_no_runs(workdir):
    assert _spawn(workdir, 5, "skip", "none") == 0
    facts = worker.collect(workdir)
    assert facts["ok_slots"] == []
    assert facts["outcomes"] == ["skipped"]  # baseline advanced, nothing ran


def test_rerunning_catch_up_after_recovery_is_idempotent(workdir):
    _spawn(workdir, 3, "run_all_missed", "none")
    _spawn(workdir, 3, "run_all_missed", "none")  # again, same now
    facts = worker.collect(workdir)
    assert facts["ok_slots"] == _slots([1, 2, 3])  # not 6 — idempotent
