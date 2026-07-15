"""SqliteInvocationStore — the execution ledger `explain` reads (12 §12).

Layer: adapters/sqlite (SQL confined here — DB-002).
Constitutional home: 12_API §4/§12 (invocation resource; explain reads from
permanent storage by correlation_id). kang.db is permanent (unlike the
90-day event log) — which is why explain reads here, never eventlog.db
(15 §8.3).
"""

from __future__ import annotations

import sqlite3

from kang.domain.ports.invocation import Invocation, InvocationNotFound

__all__ = ["SqliteInvocationStore"]

_COLUMNS = (
    "id, correlation_id, kind, operation, principal, trigger, started, "
    "finished, outcome, manifest"
)


def _row_to_invocation(row: tuple) -> Invocation:
    return Invocation(
        id=row[0],
        correlation_id=row[1],
        kind=row[2],
        operation=row[3],
        principal=row[4],
        trigger=row[5],
        started=row[6],
        finished=row[7],
        outcome=row[8],
        manifest=row[9],
    )


class SqliteInvocationStore:
    """InvocationStore over kang.db."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def start(self, invocation: Invocation) -> None:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._conn.execute(
                f"INSERT INTO invocation ({_COLUMNS}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    invocation.id,
                    invocation.correlation_id,
                    invocation.kind,
                    invocation.operation,
                    invocation.principal,
                    invocation.trigger,
                    invocation.started,
                    invocation.finished,
                    invocation.outcome,
                    invocation.manifest,
                ),
            )
            self._conn.execute("COMMIT")
        except sqlite3.Error:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise

    def finish(self, invocation_id: str, outcome: str, finished: str) -> None:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._conn.execute(
                "UPDATE invocation SET outcome = ?, finished = ? WHERE id = ?",
                (outcome, finished, invocation_id),
            )
            self._conn.execute("COMMIT")
        except sqlite3.Error:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise

    def by_correlation(self, correlation_id: str) -> Invocation:
        row = self._conn.execute(
            f"SELECT {_COLUMNS} FROM invocation WHERE correlation_id = ? "
            "ORDER BY started LIMIT 1",
            (correlation_id,),
        ).fetchone()
        if row is None:
            raise InvocationNotFound(correlation_id)
        return _row_to_invocation(row)
