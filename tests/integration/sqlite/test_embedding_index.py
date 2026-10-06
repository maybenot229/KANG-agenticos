"""SqliteEmbeddingIndex against the real, migrated kang.db (ADR-055 D3/D4/D6):
the shared contract, plus what only the real schema can show — that the
invalidation is the triggers' (any writer, including a raw UPDATE like the
recovery applier's), that `memory_record.embedding_ver` is never written
(D5), and that no vector row outlives its record."""

from __future__ import annotations

from pathlib import Path

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.fakes.model_provider import fake_vector
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.embedding_index import SqliteEmbeddingIndex
from kang.adapters.sqlite.memory_store import SqliteMemoryStore
from kang.adapters.sqlite.migrations import apply_migrations
from kang.domain.ports.embedding_index import VectorWrite
from tests.fixtures.embedding_index_contract import EmbeddingIndexContract
from tests.fixtures.memory_store_contract import record

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "migrations"


@pytest.fixture
def conn(tmp_path):
    connection = open_connection(tmp_path / "kang.db")
    apply_migrations(connection, MIGRATIONS_DIR, FakeClock())
    yield connection
    connection.close()


class TestSqliteEmbeddingIndex(EmbeddingIndexContract):
    @pytest.fixture
    def memory(self, conn):
        return SqliteMemoryStore(conn)

    @pytest.fixture
    def index(self, conn):
        return SqliteEmbeddingIndex(conn)

    @pytest.fixture
    def add_version(self, conn):
        def add(ver: int, model: str, dim: int, status: str) -> None:
            # What a future model-change migration does (ADR-055 D4): the
            # float table and its int8 companion (ADR-057 D3).
            conn.execute(
                "INSERT INTO embedding_version VALUES (?, ?, ?, ?, ?)",
                (ver, model, dim, "2026-10-05T00:00:00.000Z", status),
            )
            for table, kind in (
                (f"vec_memory_v{ver}", "float"),
                (f"vec_memory_v{ver}_i8", "int8"),
            ):
                conn.execute(
                    f"CREATE VIRTUAL TABLE {table} USING vec0("
                    f"record_rowid INTEGER PRIMARY KEY, "
                    f"embedding {kind}[{dim}] distance_metric=cosine)"
                )

        return add


def _embed(conn, record_id: str) -> None:
    index = SqliteEmbeddingIndex(conn)
    (pending,) = [p for p in index.pending_memory(1, 100) if p.record_id == record_id]
    stored = index.store_memory_vectors(
        1, [VectorWrite(pending, fake_vector(pending.content, 768))]
    )
    assert stored == 1


def _vector_rows(conn) -> int:
    return conn.execute("SELECT count(*) FROM vec_memory_v1").fetchone()[0]


def test_a_raw_update_of_content_drops_the_vector_like_any_writer(conn):
    # The recovery applier replays memory.updated with a raw UPDATE of every
    # field (recovery.py) — no store method in the path. The trigger still
    # sees it; that is why invalidation is a trigger (ADR-055 Finding 3).
    SqliteMemoryStore(conn).insert_record(record())
    _embed(conn, "mem-1")
    assert _vector_rows(conn) == 1
    conn.execute(
        "UPDATE memory_record SET content = 'replayed', revision = 2 WHERE id = 'mem-1'"
    )
    assert _vector_rows(conn) == 0


def test_a_raw_delete_drops_the_vector(conn):
    SqliteMemoryStore(conn).insert_record(record())
    _embed(conn, "mem-1")
    conn.execute("DELETE FROM memory_record WHERE id = 'mem-1'")
    assert _vector_rows(conn) == 0


def test_embedding_never_writes_the_embedding_ver_column_or_the_change_log(conn):
    SqliteMemoryStore(conn).insert_record(record())
    before = conn.execute("SELECT count(*) FROM change_log").fetchone()[0]
    _embed(conn, "mem-1")
    assert conn.execute(
        "SELECT embedding_ver FROM memory_record WHERE id = 'mem-1'"
    ).fetchone() == (None,)
    assert conn.execute("SELECT count(*) FROM change_log").fetchone()[0] == before


def test_episode_and_chunk_vectors_follow_their_rows_too(conn):
    # D4: all three v1 tables carry the same invalidation discipline, even
    # though only memory has a producer in this slice.
    for table in ("vec_episode_v1", "vec_chunk_v1"):
        assert conn.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)
    names = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")
    }
    assert {
        "trg_vec_episode_v1_delete",
        "trg_vec_episode_v1_invalidate",
        "trg_vec_chunk_v1_delete",
        "trg_vec_chunk_v1_invalidate",
    } <= names


def test_version_one_is_registered_by_the_migration(conn):
    assert conn.execute(
        "SELECT ver, model, dim, status FROM embedding_version"
    ).fetchall() == [(1, "nomic-embed-text", 768, "active")]


def test_every_connection_loads_sqlite_vec_and_then_closes_the_door(tmp_path):
    # ADR-055 D3: vec0 is present and verified at open, and extension
    # loading is switched back off — nothing else may load native code
    # through a kang.db connection.
    import sqlite3

    connection = open_connection(tmp_path / "probe.db")
    try:
        assert (
            connection.execute("SELECT vec_version()").fetchone()[0].startswith("v0.")
        )
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("SELECT load_extension('anything')")
    finally:
        connection.close()
