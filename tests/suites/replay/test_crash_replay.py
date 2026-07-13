"""Crash-replay suite 2.5 — THE Checkpoint C1 gate (18 §3 M1; 13 §2.5).

A worker process performing the paired write (event append -> state commit
-> confirm) is killed between every adjacent step pair; recovery
(reconciliation-lite over the pending window: re-apply recovery-grade
events idempotently, then confirm — 15 §4) must converge with zero
partial truth. EB-004 step 5 (fan-out) does not exist until M2; the kill
matrix covers every boundary that exists at M1.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from kang.adapters.eventlog.event_log import SqliteEventLog
from kang.adapters.eventlog.schema import open_eventlog
from kang.adapters.fakes.clock import FakeClock
from kang.adapters.sqlite.backup import integrity_check
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.migrations import apply_migrations
from kang.adapters.sqlite.recovery import apply_recovery_event
from tests.fixtures.paired_write_worker import TASK_ID

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "migrations"
WORKER = REPO_ROOT / "tests" / "fixtures" / "paired_write_worker.py"

_TASK_COLUMNS = (
    "id, project_id, title, notes, status, priority, due, plan_date, "
    "estimate_min, actual_min, completed_at, created_at, updated_at, "
    "device_id, revision"
)


def _spawn_worker(workdir: Path, kill_at: str) -> int:
    """Run the paired write in a real process and let it die mid-write."""
    result = subprocess.run(
        [sys.executable, str(WORKER), str(workdir), kill_at],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode in (0, 9), result.stderr
    return result.returncode


def _recover(workdir: Path) -> dict:
    """Reconciliation-lite (15 §4 steps 1-2): walk the pending window oldest
    first; re-apply recovery-grade payloads idempotently; confirm."""
    clock = FakeClock()
    kang_conn = open_connection(workdir / "kang.db")
    event_conn = open_eventlog(workdir / "eventlog.db")
    event_log = SqliteEventLog(event_conn, clock)

    reapplied = 0
    for stored in event_log.pending():
        if stored.envelope.recovery_grade:
            apply_recovery_event(kang_conn, stored.envelope)
            reapplied += 1
        event_log.confirm(stored.seq)

    task_row = kang_conn.execute(
        f"SELECT {_TASK_COLUMNS} FROM task WHERE id = ?", (TASK_ID,)
    ).fetchone()
    report = {
        "reapplied": reapplied,
        "task_row": task_row,
        "kang_integrity": integrity_check(kang_conn).ok,
        "pending_after": len(event_log.pending()),
        "event_states": [
            row[0] for row in event_conn.execute("SELECT state FROM event ORDER BY seq")
        ],
    }
    kang_conn.close()
    event_conn.close()
    return report


@pytest.fixture
def workdir(tmp_path):
    conn = open_connection(tmp_path / "kang.db")
    apply_migrations(conn, MIGRATIONS_DIR, FakeClock())
    conn.close()
    return tmp_path


def _assert_task_fully_present(task_row):
    """Zero partial truth: the row is complete or absent, never half."""
    assert task_row is not None
    (task_id, _, title, _, status, priority, *_rest) = task_row
    device_id, revision = task_row[-2], task_row[-1]
    assert (task_id, title, status, priority) == (TASK_ID, "crash me", "open", 3)
    assert (device_id, revision) == ("device-test", 1)
    assert all(task_row[index] is not None for index in (11, 12))  # quartet stamps


def test_kill_before_append_leaves_nothing(workdir):
    assert _spawn_worker(workdir, "before_append") == 9
    report = _recover(workdir)
    assert report["task_row"] is None
    assert report["event_states"] == []
    assert report["kang_integrity"]


def test_kill_after_append_ghost_event_is_reapplied(workdir):
    """The 2-3 crash: event pending, state lost — the ghost event.
    Recovery re-applies the self-sufficient payload (EB-004 §4.2)."""
    assert _spawn_worker(workdir, "after_append") == 9
    report = _recover(workdir)
    assert report["reapplied"] == 1
    _assert_task_fully_present(report["task_row"])
    assert report["event_states"] == ["confirmed"]
    assert report["pending_after"] == 0
    assert report["kang_integrity"]


def test_kill_after_state_reapply_is_a_noop(workdir):
    """The 3-4 crash: state committed, event still pending —
    indistinguishable from 2-3 by design; idempotent re-application makes
    the distinction irrelevant (EB-004)."""
    assert _spawn_worker(workdir, "after_state") == 9
    report = _recover(workdir)
    assert report["reapplied"] == 1  # re-applied idempotently (noop inside)
    _assert_task_fully_present(report["task_row"])
    assert report["event_states"] == ["confirmed"]
    assert report["kang_integrity"]


def test_kill_after_confirm_needs_no_reconciliation(workdir):
    assert _spawn_worker(workdir, "after_confirm") == 9
    report = _recover(workdir)
    assert report["reapplied"] == 0
    _assert_task_fully_present(report["task_row"])
    assert report["event_states"] == ["confirmed"]
    assert report["kang_integrity"]


def test_clean_run_converges_identically(workdir):
    assert _spawn_worker(workdir, "none") == 0
    report = _recover(workdir)
    _assert_task_fully_present(report["task_row"])
    assert report["event_states"] == ["confirmed"]


def test_recovery_is_idempotent_run_twice(workdir):
    """Re-running recovery after recovery changes nothing — re-applying a
    committed change is a no-op (EB-003)."""
    _spawn_worker(workdir, "after_append")
    first = _recover(workdir)
    second = _recover(workdir)
    assert second["reapplied"] == 0
    assert second["task_row"] == first["task_row"]
    assert second["event_states"] == ["confirmed"]
