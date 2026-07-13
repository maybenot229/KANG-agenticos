"""SqliteDeliveryStore — cursors + dead letters over eventlog.db.

Layer: adapters/eventlog (SQL; the subscription_cursor and dead_letter
tables live in eventlog.db — 15 §5.2).
Constitutional home: 15_EVENT_BUS EB-007 (per-subscriber cursors are
delivery truth; cursor advance is the delivery acknowledgment; dead letters
are never auto-resolved). Shares the eventlog connection with SqliteEventLog
— they are one recovery domain (07 §1.2).
"""

from __future__ import annotations

import sqlite3

from kang.domain.ports.clock import Clock
from kang.domain.ports.delivery import DeadLetter

__all__ = ["SqliteDeliveryStore"]


class SqliteDeliveryStore:
    """DeliveryStore implementation over eventlog.db."""

    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self._conn = conn
        self._clock = clock

    def cursor(self, subscriber: str) -> int:
        row = self._conn.execute(
            "SELECT last_seq FROM subscription_cursor WHERE subscriber = ?",
            (subscriber,),
        ).fetchone()
        return int(row[0]) if row is not None else 0

    def advance_cursor(self, subscriber: str, seq: int) -> None:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._conn.execute(
                "INSERT INTO subscription_cursor (subscriber, last_seq, updated_at) "
                "VALUES (?, ?, ?) ON CONFLICT(subscriber) DO UPDATE SET "
                "last_seq = excluded.last_seq, updated_at = excluded.updated_at "
                "WHERE excluded.last_seq > subscription_cursor.last_seq",
                (subscriber, seq, self._clock.now().isoformat()),
            )
            self._conn.execute("COMMIT")
        except sqlite3.Error:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise

    def record_dead_letter(
        self,
        dead_letter_id: str,
        event_seq: int,
        subscriber: str,
        attempts: int,
        last_error: str,
    ) -> DeadLetter:
        created_at = self._clock.now().isoformat()
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._conn.execute(
                "INSERT INTO dead_letter (id, event_seq, subscriber, attempts, "
                "last_error, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    dead_letter_id,
                    event_seq,
                    subscriber,
                    attempts,
                    last_error,
                    created_at,
                ),
            )
            self._conn.execute("COMMIT")
        except sqlite3.Error:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise
        return DeadLetter(
            id=dead_letter_id,
            event_seq=event_seq,
            subscriber=subscriber,
            attempts=attempts,
            last_error=last_error,
            created_at=created_at,
        )

    def dead_letters(self) -> list[DeadLetter]:
        rows = self._conn.execute(
            "SELECT id, event_seq, subscriber, attempts, last_error, created_at "
            "FROM dead_letter WHERE resolved IS NULL ORDER BY created_at, id"
        ).fetchall()
        return [
            DeadLetter(
                id=row[0],
                event_seq=row[1],
                subscriber=row[2],
                attempts=row[3],
                last_error=row[4],
                created_at=row[5],
            )
            for row in rows
        ]
