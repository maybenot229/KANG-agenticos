"""Backup mechanics (07 Part XII): VACUUM INTO snapshots, integrity gate."""

from __future__ import annotations

from pathlib import Path

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.sqlite.backup import (
    SnapshotError,
    integrity_check,
    vacuum_into,
)
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.migrations import apply_migrations
from kang.adapters.sqlite.task_store import SqliteTaskStore
from kang.domain.tasks import TaskDraft, create_task

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "migrations"


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def conn(tmp_path, clock):
    connection = open_connection(tmp_path / "kang.db")
    apply_migrations(connection, MIGRATIONS_DIR, clock)
    yield connection
    connection.close()


def _create_task(conn, clock, task_id="task-0001"):
    store = SqliteTaskStore(conn, clock)
    task = create_task(
        TaskDraft(title="survive the drill"),
        task_id=task_id,
        clock=clock,
        device_id="device-test",
    )
    store.create(task)
    return task


def test_integrity_check_ok_on_a_healthy_database(conn):
    report = integrity_check(conn)
    assert report.ok
    assert report.findings == ()


def test_snapshot_is_a_consistent_openable_copy(conn, clock, tmp_path):
    task = _create_task(conn, clock)
    destination = tmp_path / "backups" / "daily" / "kang-20260101.db"
    vacuum_into(conn, destination)
    snapshot = open_connection(destination)
    row = snapshot.execute(
        "SELECT id, title, revision FROM task WHERE id = ?", (task.id,)
    ).fetchone()
    snapshot.close()
    assert row == (task.id, task.title, 1)


def test_snapshot_never_overwrites_an_existing_snapshot(conn, tmp_path):
    destination = tmp_path / "kang-snap.db"
    vacuum_into(conn, destination)
    with pytest.raises(SnapshotError, match="already exists"):
        vacuum_into(conn, destination)


def test_snapshot_excludes_wal_sidecars(conn, clock, tmp_path):
    _create_task(conn, clock)
    destination = tmp_path / "backups" / "kang-snap.db"
    vacuum_into(conn, destination)
    assert destination.exists()
    assert not (tmp_path / "backups" / "kang-snap.db-wal").exists()


def test_integrity_check_fails_loudly_on_a_corrupted_file(tmp_path, clock):
    db_path = tmp_path / "kang.db"
    connection = open_connection(db_path)
    apply_migrations(connection, MIGRATIONS_DIR, clock)
    _create_task(connection, clock)
    connection.close()  # checkpoint WAL so the main file holds the pages

    corrupted = bytearray(db_path.read_bytes())
    # Flip bytes inside a data page (past the 100-byte header region).
    for offset in range(4096, 4160):
        corrupted[offset] ^= 0xFF
    db_path.write_bytes(bytes(corrupted))

    reopened = open_connection(db_path)
    report = integrity_check(reopened)
    reopened.close()
    assert not report.ok
    assert report.findings  # loud, named findings — never a silent ok
