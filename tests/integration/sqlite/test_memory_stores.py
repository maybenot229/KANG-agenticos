"""SqliteMemoryStore / SqliteCandidateQueueStore / SqliteUnitOfWork against the
real, migrated kang.db (ADR-051 D10; ADR-048's owed rowid claim)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.sqlite.candidate_queue_store import SqliteCandidateQueueStore
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.memory_store import SqliteMemoryStore
from kang.adapters.sqlite.migrations import apply_migrations
from kang.adapters.sqlite.transaction import SqliteUnitOfWork
from kang.domain.ports.memory_store import MemoryConflict
from tests.fixtures.candidate_queue_store_contract import (
    CandidateQueueStoreContract,
    candidate,
)
from tests.fixtures.memory_store_contract import MemoryStoreContract, record

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "migrations"


@pytest.fixture
def conn(tmp_path):
    connection = open_connection(tmp_path / "kang.db")
    apply_migrations(connection, MIGRATIONS_DIR, FakeClock())
    yield connection
    connection.close()


class TestSqliteMemoryStore(MemoryStoreContract):
    @pytest.fixture
    def store(self, conn):
        return SqliteMemoryStore(conn)

    def test_insert_fires_change_capture_and_fts_from_the_schema(self, conn, store):
        store.insert_record(record())
        ops = conn.execute(
            "SELECT op FROM change_log WHERE entity = 'memory_record'"
        ).fetchall()
        assert ops == [("insert",)]
        hits = conn.execute(
            "SELECT rowid FROM fts_memory WHERE fts_memory MATCH 'term'"
        ).fetchall()
        assert len(hits) == 1

    def test_the_schema_still_refuses_a_candidate_status_row(self, store):
        with pytest.raises(sqlite3.IntegrityError):
            store.insert_record(record(status="candidate"))

    def test_the_schema_still_refuses_a_bad_provenance_row(self, store):
        """Defence in depth: even a caller that skipped the gate cannot land
        an empty reason (07 §5.1 CHECK, 06 §8.1)."""
        with pytest.raises(sqlite3.IntegrityError):
            store.insert_record(record(reason=""))

    # ---- ADR-053 D4: delete_and_tombstone_in_txn, called the way
    # held_action.approve's transactional driver actually calls it — inside
    # an already-open transaction, never its own.

    def test_delete_and_tombstone_removes_an_archived_record_and_cascades(
        self, conn, store
    ):
        store.insert_record(record(status="archived"))
        conn.execute(
            "INSERT INTO memory_revision (record_id, revision, content, "
            "edited_by, edited_at, device_id) VALUES (?, ?, ?, ?, ?, ?)",
            ("mem-1", 1, "old content", "kang", "2026-09-24T09:00:00+00:00", "dev-1"),
        )
        conn.execute("BEGIN IMMEDIATE")
        store.delete_and_tombstone_in_txn("mem-1", "kang", "2026-09-24T10:00:00+00:00")
        conn.execute("COMMIT")

        assert store.get("mem-1") is None
        revisions = conn.execute(
            "SELECT COUNT(*) FROM memory_revision WHERE record_id = 'mem-1'"
        ).fetchone()[0]
        assert revisions == 0  # ON DELETE CASCADE
        fts_hits = conn.execute(
            "SELECT COUNT(*) FROM fts_memory WHERE rowid IN "
            "(SELECT rowid FROM memory_record WHERE id = 'mem-1')"
        ).fetchone()[0]
        assert fts_hits == 0
        delete_ops = conn.execute(
            "SELECT COUNT(*) FROM change_log WHERE entity = 'memory_record' "
            "AND entity_id = 'mem-1' AND op = 'delete'"
        ).fetchone()[0]
        assert delete_ops == 1
        tombstone = conn.execute(
            "SELECT entity, deleted_by, policy_ref FROM tombstone WHERE id = 'mem-1'"
        ).fetchone()
        assert tombstone == ("memory_record", "kang", "kang:explicit")

    def test_delete_and_tombstone_refuses_an_active_record(self, conn, store):
        """M-002 has no `active -> deleted` edge (ADR-053 D3) — enforced by
        the store itself, not only by the handler that requests
        confirmation."""
        store.insert_record(record(status="active"))
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(MemoryConflict):
            store.delete_and_tombstone_in_txn(
                "mem-1", "kang", "2026-09-24T10:00:00+00:00"
            )
        conn.execute("ROLLBACK")
        assert store.get("mem-1") is not None


class TestSqliteCandidateQueueStore(CandidateQueueStoreContract):
    @pytest.fixture
    def store(self, conn):
        return SqliteCandidateQueueStore(conn)

    def test_the_queue_is_never_change_captured(self, conn, store):
        store.enqueue(candidate())
        store.resolve("cand-1", "rejected", "2026-09-22T10:00:00+00:00")
        count = conn.execute(
            "SELECT COUNT(*) FROM change_log WHERE entity = 'memory_candidate_queue'"
        ).fetchone()[0]
        assert count == 0


def test_the_unit_of_work_commits_both_writes_together(conn):
    memory, queue = SqliteMemoryStore(conn), SqliteCandidateQueueStore(conn)
    queue.enqueue(candidate())
    SqliteUnitOfWork(conn).run(
        lambda: (
            memory.insert_record(record(id="cand-1")),
            queue.resolve("cand-1", "approved", "2026-09-22T10:00:00+00:00"),
        )
    )
    assert memory.get("cand-1") is not None
    assert queue.get("cand-1").resolved == "approved"
    assert not conn.in_transaction


def test_the_unit_of_work_rolls_both_writes_back_on_failure(conn):
    memory, queue = SqliteMemoryStore(conn), SqliteCandidateQueueStore(conn)
    queue.enqueue(candidate())

    def work():
        memory.insert_record(record(id="cand-1"))
        queue.resolve("cand-1", "approved", "2026-09-22T10:00:00+00:00")
        raise RuntimeError("crash before commit")

    with pytest.raises(RuntimeError):
        SqliteUnitOfWork(conn).run(work)
    assert memory.get("cand-1") is None
    assert queue.get("cand-1").pending
    assert not conn.in_transaction


def test_a_store_write_alone_opens_and_closes_its_own_transaction(conn):
    SqliteMemoryStore(conn).insert_record(record())
    assert not conn.in_transaction
