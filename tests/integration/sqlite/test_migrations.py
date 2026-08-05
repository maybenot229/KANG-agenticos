"""Migration harness proofs (07 Part XIII; 13 §2.11 skeleton).

Full chain on empty; checksum immutability (a modified historical migration
is startup-blocking); gapless numbering; atomic failure.
"""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
from pathlib import Path

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.migrations import MigrationError, apply_migrations, discover

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "migrations"


@pytest.fixture
def conn(tmp_path):
    connection = open_connection(tmp_path / "kang.db")
    yield connection
    connection.close()


def test_full_chain_applies_on_empty_database(conn):
    applied = apply_migrations(conn, MIGRATIONS_DIR, FakeClock())
    # initial, held_action, scheduler, api, held_action_lifecycle,
    # domain_entities, notification_queue, calendar_cache,
    # rename_app_state_to_setting, invocation_recent_index
    assert applied == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert {
        "schema_version",
        "change_log",
        "tombstone",
        "task",
        "held_action",
        "job",
        "job_run",
        "setting",
        "invocation",
        "idempotency_key",
        "session",
        # 0006 domain entities (07 §5.2)
        "goal",
        "project",
        "milestone",
        "competition",
        "deadline",
        # 0007 notification queue (ADR-005)
        "notification",
        # 0008 the calendar read stub
        "calendar_cache",
    } <= tables


def test_0006_preserves_task_rows_across_the_table_recreation(tmp_path):
    """0006 recreates `task` to add its deferred project_id FK. Data written
    under the old shape MUST survive (07 Part XIII: a migration that cannot
    map old rows losslessly refuses to run — this one maps them)."""
    conn = open_connection(tmp_path / "kang.db")
    early = sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))[:5]
    staged = tmp_path / "staged"
    staged.mkdir()
    for path in early:
        shutil.copy(path, staged / path.name)
    apply_migrations(conn, staged, FakeClock())
    conn.execute(
        "INSERT INTO task (id, title, status, priority, created_at, "
        "updated_at, device_id, revision) VALUES "
        "('t-1', 'pre-existing', 'open', 3, 'c', 'u', 'dev', 7)"
    )
    conn.commit()

    apply_migrations(conn, MIGRATIONS_DIR, FakeClock())  # applies 0006

    row = conn.execute(
        "SELECT title, status, priority, revision FROM task WHERE id = 't-1'"
    ).fetchone()
    assert row == ("pre-existing", "open", 3, 7)
    conn.close()


def test_0006_task_project_fk_is_enforced(conn):
    """The FK 0001 deferred to "the migration adding project" is live."""
    apply_migrations(conn, MIGRATIONS_DIR, FakeClock())
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO task (id, project_id, title, status, priority, "
            "created_at, updated_at, device_id, revision) VALUES "
            "('t-2', 'no-such-project', 'orphan', 'open', 3, 'c', 'u', 'dev', 1)"
        )


def test_0006_task_change_capture_still_fires_after_recreation(conn):
    """Triggers die with the table they are bound to; 0006 rebuilds them."""
    apply_migrations(conn, MIGRATIONS_DIR, FakeClock())
    conn.execute(
        "INSERT INTO task (id, title, status, priority, created_at, "
        "updated_at, device_id, revision) VALUES "
        "('t-3', 'captured', 'open', 3, 'c', 'u', 'dev', 1)"
    )
    captured = conn.execute(
        "SELECT op FROM change_log WHERE entity = 'task' AND entity_id = 't-3'"
    ).fetchall()
    assert captured == [("insert",)]


def test_applied_checksum_matches_the_file(conn):
    apply_migrations(conn, MIGRATIONS_DIR, FakeClock())
    stored = conn.execute(
        "SELECT checksum FROM schema_version WHERE version = 1"
    ).fetchone()[0]
    expected = hashlib.sha256(
        (MIGRATIONS_DIR / "0001_initial.sql").read_bytes()
    ).hexdigest()
    assert stored == expected


def test_reapply_is_a_noop(conn):
    apply_migrations(conn, MIGRATIONS_DIR, FakeClock())
    assert apply_migrations(conn, MIGRATIONS_DIR, FakeClock()) == []


def test_modified_historical_migration_blocks_startup(tmp_path):
    shipped = tmp_path / "migrations"
    shutil.copytree(MIGRATIONS_DIR, shipped)
    conn = open_connection(tmp_path / "kang.db")
    apply_migrations(conn, shipped, FakeClock())
    target = shipped / "0001_initial.sql"
    target.write_text(
        target.read_text(encoding="utf-8") + "\n-- tampered\n", encoding="utf-8"
    )
    with pytest.raises(MigrationError, match="modified"):
        apply_migrations(conn, shipped, FakeClock())
    conn.close()


def test_missing_applied_migration_blocks_startup(tmp_path, conn):
    shipped = tmp_path / "empty_migrations"
    shipped.mkdir()
    apply_migrations(conn, MIGRATIONS_DIR, FakeClock())
    with pytest.raises(MigrationError, match="missing from the shipped set"):
        apply_migrations(conn, shipped, FakeClock())


def test_version_gaps_are_rejected(tmp_path):
    shipped = tmp_path / "migrations"
    shipped.mkdir()
    (shipped / "0002_orphan.sql").write_text("CREATE TABLE x (id TEXT);")
    with pytest.raises(MigrationError, match="gapless"):
        discover(shipped)


def test_malformed_filenames_are_rejected(tmp_path):
    shipped = tmp_path / "migrations"
    shipped.mkdir()
    (shipped / "001_short.sql").write_text("CREATE TABLE x (id TEXT);")
    with pytest.raises(MigrationError, match="NNNN_description"):
        discover(shipped)


def test_failed_migration_leaves_no_partial_truth(tmp_path):
    shipped = tmp_path / "migrations"
    shipped.mkdir()
    (shipped / "0001_bad.sql").write_text(
        "CREATE TABLE half_done (id TEXT PRIMARY KEY);\n"
        "CREATE TABLE broken (id TEXT PRIMARY KEY;\n"  # syntax error
    )
    conn = open_connection(tmp_path / "kang.db")
    with pytest.raises(MigrationError, match="0001 failed"):
        apply_migrations(conn, shipped, FakeClock())
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("SELECT id FROM half_done")
    assert conn.execute("SELECT COUNT(version) FROM schema_version").fetchone()[0] == 0
    conn.close()
