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
    # Derived from the shipped set, not hardcoded: the real claims are
    # that applying an empty database runs EVERY discovered migration,
    # in order, gapless, starting at 1. A literal list additionally
    # asserted "there are exactly N", which is a change-detector with no
    # constitutional claim behind it — it broke on 0015, 0016 and 0017 in
    # succession and each time the fix was to retype the number.
    shipped = [m.version for m in discover(MIGRATIONS_DIR)]
    assert applied == shipped
    assert applied == list(range(1, len(shipped) + 1))
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


def test_0020_message_rebuild_is_lossless(tmp_path):
    """0020 recreates `message` to add its D2 rowid alias fts_message's
    content_rowid binds to. Rows written under the old shape MUST survive,
    in order, with the cascade and index intact (07 Part XIII.5; model:
    test_0006_preserves_task_rows_across_the_table_recreation)."""
    all_migrations = sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    pre_0020 = [p for p in all_migrations if int(p.name[:4]) < 20]

    conn = open_connection(tmp_path / "kang.db")
    staged = tmp_path / "staged"
    staged.mkdir()
    for path in pre_0020:
        shutil.copy(path, staged / path.name)
    apply_migrations(conn, staged, FakeClock())

    conn.execute(
        "INSERT INTO conversation (id, started, last_message, message_count) "
        "VALUES ('conv-1', 'c', 'u', 2)"
    )
    conn.execute(
        "INSERT INTO message (id, conversation_id, role, content, at) VALUES "
        "('msg-1', 'conv-1', 'kang', 'first', '2026-09-17T00:00:00.000Z')"
    )
    conn.execute(
        "INSERT INTO message (id, conversation_id, role, content, at) VALUES "
        "('msg-2', 'conv-1', 'agent', 'second', '2026-09-17T00:00:01.000Z')"
    )
    conn.commit()

    apply_migrations(conn, MIGRATIONS_DIR, FakeClock())  # applies 0020

    rows = conn.execute(
        "SELECT id, role, content, at FROM message ORDER BY rowid"
    ).fetchall()
    assert rows == [
        ("msg-1", "kang", "first", "2026-09-17T00:00:00.000Z"),
        ("msg-2", "agent", "second", "2026-09-17T00:00:01.000Z"),
    ]
    indexes = {row[1] for row in conn.execute("PRAGMA index_list('message')")}
    assert "idx_message_conversation_at" in indexes

    conn.execute("DELETE FROM conversation WHERE id = 'conv-1'")
    remaining = conn.execute(
        "SELECT COUNT(*) FROM message WHERE conversation_id = 'conv-1'"
    ).fetchone()[0]
    assert remaining == 0  # ON DELETE CASCADE survived the rebuild
    conn.close()


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


def test_0021_memory_revision_rebuild_is_lossless_and_captures_its_own_device(tmp_path):
    """ADR-048 Amendment (2026-09-18): 0021 recreates `memory_revision` to
    add its own `device_id` (07 Part X §1 — a synchronizable row). A row
    written under 0020's shape survives with `device_id` taken from its
    owning record (the only honest value 0020 had), the cascade survives,
    and a row written AFTER 0021 is change-captured with the device it
    itself carries — never the parent's (0020's subquery is gone)."""
    all_migrations = sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    pre_0021 = [p for p in all_migrations if int(p.name[:4]) < 21]

    conn = open_connection(tmp_path / "kang.db")
    staged = tmp_path / "staged"
    staged.mkdir()
    for path in pre_0021:
        shutil.copy(path, staged / path.name)
    apply_migrations(conn, staged, FakeClock())

    conn.execute(
        "INSERT INTO memory_record (id, type, status, content, trust_tier, "
        "source_kind, source_detail, reason, created_by, created_at, "
        "updated_at, device_id) VALUES ('mem-1', 'fact', 'active', 'v1', 2, "
        "'stated', 'chat', 'kang said so', 'kang', 't', 't', 'dev-parent')"
    )
    conn.execute(
        "INSERT INTO memory_revision (record_id, revision, content, edited_by, "
        "edited_at) VALUES ('mem-1', 1, 'v0', 'kang', 't0')"
    )
    conn.commit()

    apply_migrations(conn, MIGRATIONS_DIR, FakeClock())  # applies 0021

    rows = conn.execute(
        "SELECT record_id, revision, content, device_id FROM memory_revision "
        "ORDER BY revision"
    ).fetchall()
    assert rows == [("mem-1", 1, "v0", "dev-parent")]

    conn.execute(
        "INSERT INTO memory_revision (record_id, revision, content, edited_by, "
        "edited_at, device_id) VALUES ('mem-1', 2, 'v1', 'kang', 't1', 'dev-editor')"
    )
    captured = conn.execute(
        "SELECT revision, device_id FROM change_log WHERE entity = 'memory_revision' "
        "ORDER BY seq"
    ).fetchall()
    assert captured[-1] == (2, "dev-editor")

    conn.execute("DELETE FROM memory_record WHERE id = 'mem-1'")
    remaining = conn.execute("SELECT COUNT(*) FROM memory_revision").fetchone()[0]
    assert remaining == 0  # ON DELETE CASCADE survived the rebuild
    conn.close()
