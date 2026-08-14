"""ADR-021's transactional-approve crash-kill gate — the C1-style proof this
path never had.

A worker process runs the REAL `held_action.approve` transactional driver
(`_approve_transactional`) and is killed at every real boundary inside its
`BEGIN IMMEDIATE`/`COMMIT` window via a decorator wrapper — the same
`os._exit(9)`, no-test-seam pattern `paired_write_worker.py` established for
the C2 gate (13 §2.5). "Recovery" is a fresh connection opening the
surviving file, exactly what a real restart does — no bespoke recovery code
exists for this path (ADR-001 Amendment's own claim is that none is
needed), so this suite is what actually proves that claim rather than
asserting it.

This suite closes a real gap found in review, not a speculative one:
ADR-021's own live verification proved the happy path and an in-process
Python-exception rollback — neither is equivalent to a genuine OS-level
kill mid-transaction. This is.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests.fixtures import transactional_approve_worker as worker

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKER = REPO_ROOT / "tests" / "fixtures" / "transactional_approve_worker.py"


def _spawn_worker(workdir: Path, kill_at: str) -> int:
    result = subprocess.run(
        [sys.executable, str(WORKER), str(workdir), kill_at],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode in (0, 9), result.stderr
    return result.returncode


@pytest.fixture
def workdir(tmp_path):
    return tmp_path


# -- the kill matrix: every real boundary inside the transaction ----------


def test_kill_before_approve_leaves_pending_and_untouched(workdir):
    assert _spawn_worker(workdir, "before_approve") == 9
    facts = worker.recover(workdir)
    assert facts["held_status"] == "pending"
    assert facts["job_enabled"] is True
    assert facts["integrity"]


def test_kill_after_approve_before_effect_leaves_pending_and_untouched(workdir):
    # The approve-flip write happened on the connection, but the
    # transaction was never committed — WAL rolls it back on reopen. If
    # this ever showed status='approved' with the job still enabled, that
    # would be exactly the partial-truth gap ADR-001 Amendment claims is
    # structurally impossible for transactional mode.
    assert _spawn_worker(workdir, "after_approve") == 9
    facts = worker.recover(workdir)
    assert facts["held_status"] == "pending"
    assert facts["job_enabled"] is True
    assert facts["integrity"]


def test_kill_after_effect_before_mark_executed_leaves_pending_and_untouched(workdir):
    # The hardest case: the job's own row was written (enabled=False) on
    # the connection, one write away from a fully committed effect — and
    # it must STILL roll back completely, not leave the job disabled with
    # no record of why. This is the exact scenario the review question
    # named: "the effect succeeds but mark-executed fails."
    assert _spawn_worker(workdir, "after_effect") == 9
    facts = worker.recover(workdir)
    assert facts["held_status"] == "pending"
    assert facts["job_enabled"] is True
    assert facts["integrity"]


def test_kill_after_mark_executed_before_commit_leaves_pending_and_untouched(workdir):
    # One write away from the finish line — all three writes landed on
    # the connection, only the COMMIT itself never happened. Still must
    # be all-or-nothing.
    assert _spawn_worker(workdir, "after_mark_executed") == 9
    facts = worker.recover(workdir)
    assert facts["held_status"] == "pending"
    assert facts["job_enabled"] is True
    assert facts["integrity"]


def test_clean_run_commits_everything(workdir):
    assert _spawn_worker(workdir, "none") == 0
    facts = worker.recover(workdir)
    assert facts["held_status"] == "executed"
    assert facts["job_enabled"] is False
    assert facts["integrity"]
