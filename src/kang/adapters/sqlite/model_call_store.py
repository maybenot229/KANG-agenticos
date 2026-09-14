"""SqliteModelCallStore — the usage & cost ledger (D010, AG-008).

Layer: adapters/sqlite (SQL confined here — DB-002).
Constitutional home: 07_DATABASE §5.5 (`model_call`'s schema, migration
0018), 05_AGENTS AG-008 ("every call lands in `model_call`"). Append-only
— no update/delete method exists, matching the port's own contract.
"""

from __future__ import annotations

import sqlite3

from kang.domain.ports.model_call import ModelCall

__all__ = ["SqliteModelCallStore"]

_COLUMNS = (
    "provider, model, task_class, tokens_in, tokens_out, cost_usd, "
    "latency_ms, outcome, at"
)


class SqliteModelCallStore:
    """ModelCallStore over kang.db."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def record(self, call: ModelCall) -> None:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._conn.execute(
                f"INSERT INTO model_call ({_COLUMNS}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    call.provider,
                    call.model,
                    call.task_class,
                    call.tokens_in,
                    call.tokens_out,
                    call.cost_usd,
                    call.latency_ms,
                    call.outcome,
                    call.at,
                ),
            )
            self._conn.execute("COMMIT")
        except sqlite3.Error:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise
