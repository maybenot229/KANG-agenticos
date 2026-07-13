"""Backup/restore suite 2.15 — the C1 restore drill (18 §3 M1; 13 §2.15):

    snapshot -> corrupt live -> restore -> field-equality -> gap replay

The gap is replayed from eventlog.db's recovery-grade events past the
snapshot watermark (EB-009 form 2, snapshot gap-fill; DB-001 pairing) —
which is why eventlog.db "MUST survive/replay across kang.db restores"
(07 §1.2) and lives in its own recovery domain.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from kang.adapters.eventlog.event_log import SqliteEventLog
from kang.adapters.eventlog.schema import open_eventlog
from kang.adapters.fakes.clock import FakeClock
from kang.adapters.sqlite.backup import integrity_check, vacuum_into
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.migrations import apply_migrations
from kang.adapters.sqlite.recovery import apply_recovery_event
from kang.adapters.sqlite.task_store import SqliteTaskStore
from kang.domain.tasks import TaskDraft, complete_task, create_task
from tests.fixtures.paired_write_worker import task_envelope

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "migrations"

_TASK_COLUMNS = (
    "id, project_id, title, notes, status, priority, due, plan_date, "
    "estimate_min, actual_min, completed_at, created_at, updated_at, "
    "device_id, revision"
)


class Drill:
    """One live system: kang.db + eventlog.db + paired-write helper."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.clock = FakeClock()
        self.kang_path = root / "kang.db"
        self.kang = open_connection(self.kang_path)
        apply_migrations(self.kang, MIGRATIONS_DIR, self.clock)
        self.events_conn = open_eventlog(root / "events" / "eventlog.db")
        self.event_log = SqliteEventLog(self.events_conn, self.clock)
        self.store = SqliteTaskStore(self.kang, self.clock)
        self._counter = 0

    def paired_create(self, title: str):
        """append pending -> commit state -> confirm (the M1 pairing)."""
        self._counter += 1
        task = create_task(
            TaskDraft(title=title),
            task_id=f"task-{self._counter:04d}",
            clock=self.clock,
            device_id="device-test",
        )
        seq = self.event_log.append(
            task_envelope(task, event_id=f"event-{self._counter:04d}")
        )
        self.store.create(task)
        self.event_log.confirm(seq)
        return task

    def paired_complete(self, task):
        self._counter += 1
        committed = self.store.update(complete_task(task, self.clock))
        seq = self.event_log.append(
            task_envelope(
                committed,
                event_id=f"event-{self._counter:04d}",
                event_type="task.updated",
            )
        )
        self.event_log.confirm(seq)
        return committed

    def all_task_rows(self) -> list[tuple]:
        return self.kang.execute(
            f"SELECT {_TASK_COLUMNS} FROM task ORDER BY id"
        ).fetchall()

    def close(self) -> None:
        self.kang.close()
        self.events_conn.close()


@pytest.fixture
def drill(tmp_path):
    system = Drill(tmp_path)
    yield system
    system.close()


def test_the_c1_restore_drill(drill, tmp_path):
    # -- live activity before the snapshot --------------------------------
    kept = drill.paired_create("before snapshot A")
    drill.paired_create("before snapshot B")

    # -- daily snapshot (07 Part XII.1) + watermark ------------------------
    snapshot = tmp_path / "backups" / "daily" / "kang-20260101.db"
    vacuum_into(drill.kang, snapshot)
    watermark = drill.event_log.last_seq()

    # -- the gap: activity after the snapshot ------------------------------
    drill.paired_create("after snapshot C")
    completed = drill.paired_complete(kept)
    expected_rows = drill.all_task_rows()  # ground truth to converge back to

    # -- corrupt the live file ---------------------------------------------
    drill.kang.close()
    live = bytearray(drill.kang_path.read_bytes())
    for offset in range(4096, 4288):
        live[offset] ^= 0xFF
    drill.kang_path.write_bytes(bytes(live))
    corrupted = open_connection(drill.kang_path)
    assert not integrity_check(corrupted).ok  # detection, then freeze (F1)
    corrupted.close()

    # -- restore the verified snapshot --------------------------------------
    for sidecar in (".db-wal", ".db-shm"):
        leftover = drill.kang_path.with_name("kang" + sidecar)
        if leftover.exists():
            leftover.unlink()
    shutil.copyfile(snapshot, drill.kang_path)
    restored = open_connection(drill.kang_path)
    assert integrity_check(restored).ok

    # snapshot state = pre-gap truth: C and the completion are missing
    assert len(restored.execute("SELECT id FROM task").fetchall()) == 2

    # -- replay the gap from the surviving event log ------------------------
    for stored in drill.event_log.read_from(watermark):
        if stored.envelope.recovery_grade:
            apply_recovery_event(restored, stored.envelope)

    # -- field-level equality (13 §2.15) ------------------------------------
    recovered_rows = restored.execute(
        f"SELECT {_TASK_COLUMNS} FROM task ORDER BY id"
    ).fetchall()
    assert recovered_rows == expected_rows
    done_row = restored.execute(
        "SELECT status, revision FROM task WHERE id = ?", (completed.id,)
    ).fetchone()
    assert done_row == ("done", 2)
    restored.close()


def test_eventlog_takes_its_own_vacuum_snapshot(drill, tmp_path):
    """07 Part XII.2: eventlog is backed up by its own VACUUM INTO."""
    drill.paired_create("logged")
    destination = tmp_path / "backups" / "eventlog-20260101.db"
    vacuum_into(drill.events_conn, destination)
    copy = open_eventlog(destination)
    assert copy.execute("SELECT COUNT(seq) FROM event").fetchone()[0] == 1
    copy.close()


def test_restore_replay_is_idempotent(drill, tmp_path):
    """Replaying the same gap twice converges to the same rows (EB-003)."""
    drill.paired_create("only one of me")
    snapshot = tmp_path / "kang-snap.db"
    vacuum_into(drill.kang, snapshot)
    restored = open_connection(snapshot)
    for _ in range(2):
        for stored in drill.event_log.read_from(0):
            if stored.envelope.recovery_grade:
                apply_recovery_event(restored, stored.envelope)
    count = restored.execute("SELECT COUNT(id) FROM task").fetchone()[0]
    restored.close()
    assert count == 1
