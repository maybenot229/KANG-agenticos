"""Crash-replay suite 2.5 — THE Checkpoint C2 gate (18 §3 M2; 13 §2.5).

A worker process performs the REAL bus publish (EB-004 steps 1-5) and is
killed between every adjacent step pair via a dying-port wrapper. "Restart"
runs the REAL production recovery — the caged `Reconciliation` module plus
per-subscriber delivery resume (`EventBus.recover`) — NOT any test-harness
reconciliation loop. Convergence, zero partial truth, and at-least-once
delivery with idempotent dedup are asserted for every kill point.

This suite is the reason the reconciliation module is caged (§4): it is the
module's exercise. If reconciliation grows a feature, a kill point here
must justify it — or it does not belong in the module.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.migrations import apply_migrations
from tests.fixtures import paired_write_worker as worker

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "migrations"
WORKER = REPO_ROOT / "tests" / "fixtures" / "paired_write_worker.py"


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
    """A freshly migrated kang.db; the worker creates events/eventlog.db and
    audit/ on first open."""
    conn = open_connection(tmp_path / "kang.db")
    apply_migrations(conn, MIGRATIONS_DIR, FakeClock())
    conn.close()
    return tmp_path


def _assert_task_present(row):
    """Zero partial truth: the row is complete, or it is absent — never half."""
    assert row is not None
    task_id, title, status, device_id, revision, created_at, updated_at = row
    assert (task_id, title, status) == (worker.TASK_ID, "crash me", "open")
    assert (device_id, revision) == ("device-test", 1)
    assert created_at and updated_at  # quartet stamps intact


# -- the kill matrix: every EB-004 boundary, real recovery ----------------


def test_kill_before_append_leaves_nothing(workdir):
    assert _spawn_worker(workdir, "before_append") == 9
    facts = worker.recover(workdir)
    assert facts["task_row"] is None
    assert facts["event_states"] == []  # nothing ever appended
    assert facts["delivered"] == []
    assert facts["kang_integrity"]


def test_kill_after_append_reapplies_the_ghost_event(workdir):
    """Crash 2-3: event pending, state lost. The caged reconciliation
    re-applies the self-sufficient payload and confirms (EB-004 §4.2)."""
    assert _spawn_worker(workdir, "after_append") == 9
    facts = worker.recover(workdir)
    assert facts["reapplied"] == 1
    _assert_task_present(facts["task_row"])
    assert facts["event_states"] == ["confirmed"]
    assert facts["pending_after"] == 0
    assert facts["delivered"] == [worker.EVENT_ID]  # delivered on resume
    assert facts["kang_integrity"]


def test_kill_after_state_reapply_is_idempotent(workdir):
    """Crash 3-4: state committed, event still pending — indistinguishable
    from 2-3 by design; idempotent re-application makes it irrelevant."""
    assert _spawn_worker(workdir, "after_state") == 9
    facts = worker.recover(workdir)
    assert facts["reapplied"] == 1  # re-applied; noop inside (id+revision)
    _assert_task_present(facts["task_row"])
    assert facts["event_states"] == ["confirmed"]
    assert facts["delivered"] == [worker.EVENT_ID]
    assert facts["kang_integrity"]


def test_kill_after_confirm_delivers_on_resume(workdir):
    """Crash 4-5: confirmed, undelivered. Reconciliation finds nothing
    pending; delivery resume from the cursor delivers exactly once."""
    assert _spawn_worker(workdir, "after_confirm") == 9
    facts = worker.recover(workdir)
    assert facts["reapplied"] == 0
    assert facts["window"] == 0  # already confirmed before the crash
    _assert_task_present(facts["task_row"])
    assert facts["event_states"] == ["confirmed"]
    assert facts["delivered"] == [worker.EVENT_ID]


def test_kill_during_deliver_dedups_the_redelivery(workdir):
    """Crash inside step 5: handler ran its side effect but the cursor did
    not advance. Redelivery on resume is absorbed by event_id dedup — the
    at-least-once + idempotent contract (§7.6). Delivered exactly once."""
    assert _spawn_worker(workdir, "during_deliver") == 9
    facts = worker.recover(workdir)
    _assert_task_present(facts["task_row"])
    assert facts["event_states"] == ["confirmed"]
    assert facts["delivered"] == [worker.EVENT_ID]  # once, not twice


def test_clean_run_converges_identically(workdir):
    assert _spawn_worker(workdir, "none") == 0
    facts = worker.recover(workdir)
    assert facts["window"] == 0  # nothing to reconcile after a clean run
    _assert_task_present(facts["task_row"])
    assert facts["event_states"] == ["confirmed"]
    assert facts["delivered"] == [worker.EVENT_ID]


def test_recovery_is_idempotent_run_twice(workdir):
    """Running the real recovery after recovery changes nothing (EB-003)."""
    _spawn_worker(workdir, "after_append")
    first = worker.recover(workdir)
    second = worker.recover(workdir)
    assert second["reapplied"] == 0 and second["window"] == 0
    assert second["task_row"] == first["task_row"]
    assert second["event_states"] == ["confirmed"]
    assert second["delivered"] == [worker.EVENT_ID]  # not redelivered
