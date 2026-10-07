"""SqliteMemorySearchStore — the MemorySearchStore port over `fts_memory` and
`memory_record` (ADR-056 D1).

Layer: adapters/sqlite (the only home of SQL — DB-002; no SELECT *, 11 §13).
Constitutional home: 07_DATABASE §6.1 (FTS5 external content, `porter
unicode61`), DB-003's dated clarification (the FTS rowid never leaves this
module).

Kang's query text is never passed to FTS5 as syntax: it is split into words
and each word is quoted, so `AND`, `NEAR`, `*`, `"` and the rest are just
text (a syntax error in a search box is a bug, not a user mistake).
"""

from __future__ import annotations

import re
import sqlite3
from typing import Sequence

from kang.adapters.sqlite.memory_store import _COLUMNS, _row_to_record
from kang.domain.ports.memory_search import LexicalHit
from kang.domain.ports.memory_store import MemoryRecord

__all__ = ["SqliteMemorySearchStore", "fts_query"]

_WORD = re.compile(r"\w+", re.UNICODE)


def fts_query(text: str) -> str:
    """Kang's words as an FTS5 OR-query of quoted terms; '' when none."""
    words = _WORD.findall(text)
    return " OR ".join('"' + word.replace('"', '""') + '"' for word in words)


def _placeholders(values: Sequence[object]) -> str:
    return ", ".join("?" for _ in values)


class SqliteMemorySearchStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def lexical(
        self,
        query: str,
        statuses: Sequence[str],
        types: Sequence[str] | None,
        k: int,
    ) -> tuple[LexicalHit, ...]:
        match = fts_query(query)
        if not match or not statuses:
            return ()
        type_clause = ""
        params: list[object] = [match, *statuses]
        if types is not None:
            if not types:
                return ()
            type_clause = f" AND m.type IN ({_placeholders(types)})"
            params.extend(types)
        params.append(k)
        rows = self._conn.execute(
            "SELECT m.id, bm25(fts_memory) FROM fts_memory "
            "JOIN memory_record m ON m.rowid = fts_memory.rowid "
            f"WHERE fts_memory MATCH ? AND m.status IN ({_placeholders(statuses)}) "
            f"AND m.sensitivity <> 'private'{type_clause} "
            "ORDER BY bm25(fts_memory), m.id LIMIT ?",
            params,
        ).fetchall()
        return tuple(LexicalHit(record_id, score) for record_id, score in rows)

    def records(self, record_ids: Sequence[str]) -> tuple[MemoryRecord, ...]:
        if not record_ids:
            return ()
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM memory_record "
            f"WHERE id IN ({_placeholders(record_ids)}) ORDER BY id",
            list(record_ids),
        ).fetchall()
        return tuple(_row_to_record(row) for row in rows)

    def standing(self, statuses: Sequence[str]) -> tuple[MemoryRecord, ...]:
        if not statuses:
            return ()
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM memory_record "
            f"WHERE status IN ({_placeholders(statuses)}) "
            "AND sensitivity <> 'private' "
            "AND (type IN ('rule', 'profile', 'preference') OR pinned = 1) "
            "ORDER BY id",
            list(statuses),
        ).fetchall()
        return tuple(_row_to_record(row) for row in rows)
