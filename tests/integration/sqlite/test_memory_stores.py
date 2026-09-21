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
