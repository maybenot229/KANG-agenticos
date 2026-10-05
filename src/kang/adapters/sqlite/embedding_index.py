"""SqliteEmbeddingIndex — the EmbeddingIndex port over kang.db's
`embedding_version` and `vec_*` tables (ADR-055 D6).

Layer: adapters/sqlite (the only home of SQL — DB-002; no SELECT *, 11 §13).
Constitutional home: 07_DATABASE Part VIII DB-004, §6.2; DB-003's dated
clarification — the integer rowid is how a `vec_memory_v{n}` row names its
`memory_record`, and it never leaves this module.

A version's table name is built from its integer `ver` (`vec_memory_v1`).
Identifiers cannot be bound as parameters; `int()` on a value read from
`embedding_version`'s INTEGER primary key is what keeps that safe.
"""

from __future__ import annotations

import sqlite3
from typing import Sequence

import sqlite_vec

from kang.adapters.sqlite.transaction import writing
from kang.domain.ports.embedding_index import (
    Coverage,
    EmbeddingIndexConflict,
    EmbeddingVersion,
    Neighbor,
    PendingRecord,
    VectorWrite,
)

__all__ = ["SqliteEmbeddingIndex"]

_EMBEDDABLE = "m.status IN ('active', 'under_review') AND m.sensitivity <> 'private'"


def _memory_table(ver: int) -> str:
    return f"vec_memory_v{int(ver)}"


class SqliteEmbeddingIndex:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def versions_to_fill(self) -> tuple[EmbeddingVersion, ...]:
        rows = self._conn.execute(
            "SELECT ver, model, dim, status FROM embedding_version "
            "WHERE status IN ('active', 'migrating') "
            "ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END, ver"
        ).fetchall()
        return tuple(EmbeddingVersion(*row) for row in rows)

    def pending_memory(self, ver: int, limit: int) -> tuple[PendingRecord, ...]:
        # `NOT IN (SELECT record_rowid ...)`, never a correlated NOT EXISTS:
        # SQLite materializes the rowid set once, where a per-row vec0 lookup
        # costs ~1 ms each — measured 2026-10-05 on the year1 corpus, 3 s vs
        # 6 ms, which at the 10-year ceiling is a minute of writer time.
        rows = self._conn.execute(
            "SELECT m.id, m.content, m.revision, m.sensitivity "
            f"FROM memory_record m WHERE {_EMBEDDABLE} AND m.rowid NOT IN ("
            f"SELECT record_rowid FROM {_memory_table(ver)}) "
            "ORDER BY m.updated_at DESC, m.id LIMIT ?",
            (limit,),
        ).fetchall()
        return tuple(PendingRecord(*row) for row in rows)

    def store_memory_vectors(self, ver: int, writes: Sequence[VectorWrite]) -> int:
        table = _memory_table(ver)
        stored = 0
        with writing(self._conn):
            for write in writes:
                cursor = self._conn.execute(
                    f"INSERT INTO {table} (record_rowid, embedding) "
                    f"SELECT m.rowid, ? FROM memory_record m WHERE m.id = ? "
                    f"AND m.revision = ? AND {_EMBEDDABLE} AND NOT EXISTS ("
                    f"SELECT 1 FROM {table} v WHERE v.record_rowid = m.rowid)",
                    (
                        sqlite_vec.serialize_float32(list(write.vector)),
                        write.record.record_id,
                        write.record.revision,
                    ),
                )
                stored += max(cursor.rowcount, 0)
        return stored

    def memory_coverage(self, ver: int) -> Coverage:
        embeddable, embedded = self._conn.execute(
            "SELECT count(*), coalesce(sum(m.rowid IN ("
            f"SELECT record_rowid FROM {_memory_table(ver)})), 0) "
            f"FROM memory_record m WHERE {_EMBEDDABLE}"
        ).fetchone()
        return Coverage(embedded=embedded, embeddable=embeddable)

    def cut_over(self, ver: int) -> None:
        with writing(self._conn):
            row = self._conn.execute(
                "SELECT status FROM embedding_version WHERE ver = ?", (ver,)
            ).fetchone()
            if row is None or row[0] != "migrating":
                raise EmbeddingIndexConflict(
                    f"embedding version {ver} is not 'migrating' — nothing to cut over"
                )
            if not self.memory_coverage(ver).is_complete:
                raise EmbeddingIndexConflict(
                    f"embedding version {ver} is not fully covered — refusing to "
                    "cut over to an incomplete space (DB-004)"
                )
            self._conn.execute(
                "UPDATE embedding_version SET status = 'retired' "
                "WHERE status = 'active'"
            )
            self._conn.execute(
                "UPDATE embedding_version SET status = 'active' WHERE ver = ?", (ver,)
            )

    def nearest_memory(
        self, ver: int, vector: Sequence[float], k: int
    ) -> tuple[Neighbor, ...]:
        rows = self._conn.execute(
            "WITH knn AS (SELECT record_rowid, distance "
            f"FROM {_memory_table(ver)} WHERE embedding MATCH ? AND k = ?) "
            "SELECT m.id, knn.distance FROM knn "
            "JOIN memory_record m ON m.rowid = knn.record_rowid "
            "ORDER BY knn.distance, m.id",
            (sqlite_vec.serialize_float32(list(vector)), k),
        ).fetchall()
        return tuple(Neighbor(record_id, distance) for record_id, distance in rows)
