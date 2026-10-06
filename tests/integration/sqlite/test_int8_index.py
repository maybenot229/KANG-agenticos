"""The int8 kNN companion (ADR-057): written with the float vector, deleted
with it, searched instead of it, and backfilled by migration 0023 from vectors
that existed before it — in SQL, identical to the Python path."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.fakes.model_provider import fake_vector
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.embedding_index import SqliteEmbeddingIndex
from kang.adapters.sqlite.memory_store import SqliteMemoryStore
from kang.adapters.sqlite.migrations import apply_migrations
from kang.domain.ports.embedding_index import VectorWrite
from kang.domain.ports.memory_store import ContentEdit
from tests.fixtures.memory_store_contract import record

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "migrations"
NOW = "2026-10-06T01:00:00+00:00"


@pytest.fixture
def conn(tmp_path):
    connection = open_connection(tmp_path / "kang.db")
    apply_migrations(connection, MIGRATIONS_DIR, FakeClock())
    yield connection
    connection.close()


def _embed_all(conn) -> None:
    index = SqliteEmbeddingIndex(conn)
    pending = index.pending_memory(1, 100)
    index.store_memory_vectors(
        1, [VectorWrite(p, fake_vector(p.content, 768)) for p in pending]
    )


def _counts(conn) -> tuple[int, int]:
    return (
        conn.execute("SELECT count(*) FROM vec_memory_v1").fetchone()[0],
        conn.execute("SELECT count(*) FROM vec_memory_v1_i8").fetchone()[0],
    )


def test_both_tables_are_written_together(conn):
    store = SqliteMemoryStore(conn)
    for i in range(3):
        store.insert_record(record(id=f"m{i}", content=f"fact {i}"))
    _embed_all(conn)
    assert _counts(conn) == (3, 3)


def test_a_skipped_stale_write_writes_neither_table(conn):
    store = SqliteMemoryStore(conn)
    store.insert_record(record())
    index = SqliteEmbeddingIndex(conn)
    (pending,) = index.pending_memory(1, 10)
    store.update_content(ContentEdit("mem-1", "edited", "fix", 1, "kang", "d", NOW))
    stored = index.store_memory_vectors(
        1, [VectorWrite(pending, fake_vector(pending.content, 768))]
    )
    assert stored == 0 and _counts(conn) == (0, 0)


@pytest.mark.parametrize("change", ["edit", "archive", "delete"])
def test_both_tables_are_invalidated_together(conn, change):
    store = SqliteMemoryStore(conn)
    store.insert_record(record())
    _embed_all(conn)
    if change == "edit":
        store.update_content(ContentEdit("mem-1", "new", "fix", 1, "kang", "d", NOW))
    else:
        store.transition_status("mem-1", "active", "archived", "d", NOW)
    if change == "delete":
        store.delete_and_tombstone_in_txn("mem-1", "kang", NOW)
    assert _counts(conn) == (0, 0)


def test_search_reads_the_int8_table_and_finds_the_identical_vector_first(conn):
    store = SqliteMemoryStore(conn)
    for i, text in enumerate(("robotics team", "school term", "deep work")):
        store.insert_record(record(id=f"m{i}", content=text))
    _embed_all(conn)
    conn.execute("DELETE FROM vec_memory_v1")  # prove kNN does not read floats
    (top, *_) = SqliteEmbeddingIndex(conn).nearest_memory(
        1, fake_vector("school term", 768), 3
    )
    assert top.record_id == "m1" and top.distance == pytest.approx(0.0, abs=1e-6)


def test_migration_0023_backfills_existing_vectors_exactly_as_the_index_would(
    tmp_path,
):
    # A database at 0022 with float vectors already stored...
    upto_22 = tmp_path / "migrations"
    upto_22.mkdir()
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if int(path.name[:4]) <= 22:
            shutil.copy(path, upto_22 / path.name)
    db = open_connection(tmp_path / "kang.db")
    try:
        apply_migrations(db, upto_22, FakeClock())
        store = SqliteMemoryStore(db)
        for i in range(4):
            store.insert_record(record(id=f"m{i}", content=f"backfilled fact {i}"))
        for p in SqliteEmbeddingIndex(db).pending_memory(1, 10):
            db.execute(
                "INSERT INTO vec_memory_v1 (record_rowid, embedding) "
                "SELECT rowid, ? FROM memory_record WHERE id = ?",
                (_float32(fake_vector(p.content, 768)), p.record_id),
            )
        # ...then 0023 runs.
        assert apply_migrations(db, MIGRATIONS_DIR, FakeClock()) == [23]
        backfilled = dict(
            db.execute(
                "SELECT record_rowid, vec_to_json(embedding) FROM vec_memory_v1_i8"
            ).fetchall()
        )
        assert len(backfilled) == 4
        by_content = dict(
            db.execute(
                "SELECT m.content, vec_to_json(i.embedding) FROM vec_memory_v1_i8 i "
                "JOIN memory_record m ON m.rowid = i.record_rowid"
            ).fetchall()
        )
    finally:
        db.close()
    # The same records, embedded through the public index at HEAD, get the
    # same int8 bytes: the SQL backfill and the Python path agree.
    fresh = open_connection(tmp_path / "fresh.db")
    try:
        apply_migrations(fresh, MIGRATIONS_DIR, FakeClock())
        store = SqliteMemoryStore(fresh)
        for i in range(4):
            store.insert_record(record(id=f"m{i}", content=f"backfilled fact {i}"))
        _embed_all(fresh)
        assert by_content == dict(
            fresh.execute(
                "SELECT m.content, vec_to_json(i.embedding) FROM vec_memory_v1_i8 i "
                "JOIN memory_record m ON m.rowid = i.record_rowid"
            ).fetchall()
        )
    finally:
        fresh.close()


def _float32(vector) -> bytes:
    import sqlite_vec

    return sqlite_vec.serialize_float32(list(vector))
