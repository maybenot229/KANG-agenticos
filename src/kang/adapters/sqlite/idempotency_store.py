"""SqliteIdempotencyStore — return the original outcome (API-004).

Layer: adapters/sqlite (SQL confined here — DB-002).
Constitutional home: 12_API API-004 (return the original outcome for a
repeated key, never re-execute; 7-day retention). The first outcome for a
key is authoritative — a second put MUST NOT overwrite it.
"""

from __future__ import annotations

import sqlite3

__all__ = ["SqliteIdempotencyStore"]


class SqliteIdempotencyStore:
    """IdempotencyStore over kang.db."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT outcome_json FROM idempotency_key WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row is not None else None

    def put(self, key: str, outcome_json: str, at: str) -> None:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            # First write wins: a repeat key is ignored (the original outcome
            # is authoritative — API-004).
            self._conn.execute(
                "INSERT INTO idempotency_key (key, outcome_json, created_at) "
                "VALUES (?, ?, ?) ON CONFLICT(key) DO NOTHING",
                (key, outcome_json, at),
            )
            self._conn.execute("COMMIT")
        except sqlite3.Error:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise

    def purge_before(self, cutoff: str) -> int:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = self._conn.execute(
                "DELETE FROM idempotency_key WHERE created_at < ?", (cutoff,)
            )
            self._conn.execute("COMMIT")
        except sqlite3.Error:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise
        return cursor.rowcount
