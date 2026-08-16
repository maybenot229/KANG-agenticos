"""SqliteHeldActionStore — held actions over kang.db.

Layer: adapters/sqlite (SQL confined here — DB-002).
Constitutional home: 12_API §7 (held_action lifecycle), 07 §5.5-style
transactional writes (BEGIN IMMEDIATE, DB-003). Status transitions are
guarded: only a pending action approves/cancels, only an approved action
executes; approval past expiry is refused (the window closed). Lifecycle
(pending → approved → executed | pending → cancelled | pending → expired)
is ADR 001's, with `cancelled`/`expired` split by ADR-024 — the former is
Kang explicitly declining, the latter is the 24h sweep finding no
decision was made; both collapsed into `cancelled` before ADR-024.

`params` (ADR-021): the original request's params, JSON-serialized — same
pattern `notification_store.py`'s `payload` column already uses, no new
idiom invented.

`_in_txn` methods (ADR-021): `held_action.approve`'s handler drives a
`transactional`-commit_mode effect in one `BEGIN`/`COMMIT` spanning this
store's write AND the target operation's own effect write — so the
approve-flip and mark-executed steps need variants that neither open nor
close a transaction, trusting the caller to own that boundary. `_status_
in_txn` is the shared inner helper; the public methods wrap it in their
own BEGIN/COMMIT exactly as before, so every existing caller is unchanged.
"""

from __future__ import annotations

import json
import sqlite3

from kang.domain.ports.held_action import (
    HeldAction,
    HeldActionExpired,
    HeldActionNotFound,
)

__all__ = ["SqliteHeldActionStore"]

_COLUMNS = (
    "id, operation, action, principal, reason, reversibility, "
    "correlation_id, created_at, expires_at, status, params"
)


def _row_to_held_action(row: tuple) -> HeldAction:
    return HeldAction(
        id=row[0],
        operation=row[1],
        action=row[2],
        principal=row[3],
        reason=row[4],
        reversibility=row[5],
        correlation_id=row[6],
        created_at=row[7],
        expires_at=row[8],
        status=row[9],
        params=json.loads(row[10]),
    )


class SqliteHeldActionStore:
    """HeldActionStore over kang.db."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, held_action: HeldAction) -> None:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._conn.execute(
                f"INSERT INTO held_action ({_COLUMNS}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    held_action.id,
                    held_action.operation,
                    held_action.action,
                    held_action.principal,
                    held_action.reason,
                    held_action.reversibility,
                    held_action.correlation_id,
                    held_action.created_at,
                    held_action.expires_at,
                    held_action.status,
                    json.dumps(held_action.params),
                ),
            )
            self._conn.execute("COMMIT")
        except sqlite3.Error:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise

    def get(self, held_action_id: str) -> HeldAction:
        row = self._conn.execute(
            f"SELECT {_COLUMNS} FROM held_action WHERE id = ?", (held_action_id,)
        ).fetchone()
        if row is None:
            raise HeldActionNotFound(held_action_id)
        return _row_to_held_action(row)

    def approve(self, held_action_id: str, now: str) -> HeldAction:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            result = self._approve_checked(held_action_id, now)
            self._conn.execute("COMMIT")
        except (sqlite3.Error, HeldActionNotFound, HeldActionExpired):
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise
        return result

    def approve_in_txn(self, held_action_id: str, now: str) -> HeldAction:
        return self._approve_checked(held_action_id, now)

    def _approve_checked(self, held_action_id: str, now: str) -> HeldAction:
        current = self.get(held_action_id)
        if current.status != "pending":
            raise HeldActionNotFound(
                f"{held_action_id} is {current.status}, not pending"
            )
        if now >= current.expires_at:
            raise HeldActionExpired(held_action_id)
        return self._status_in_txn(held_action_id, "approved")

    def cancel(self, held_action_id: str) -> HeldAction:
        current = self.get(held_action_id)
        if current.status != "pending":
            raise HeldActionNotFound(
                f"{held_action_id} is {current.status}, not pending"
            )
        return self._set_status(held_action_id, "cancelled")

    def mark_executed(self, held_action_id: str) -> HeldAction:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            result = self._mark_executed_checked(held_action_id)
            self._conn.execute("COMMIT")
        except (sqlite3.Error, HeldActionNotFound):
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise
        return result

    def mark_executed_in_txn(self, held_action_id: str) -> HeldAction:
        return self._mark_executed_checked(held_action_id)

    def _mark_executed_checked(self, held_action_id: str) -> HeldAction:
        current = self.get(held_action_id)
        if current.status != "approved":
            raise HeldActionNotFound(
                f"{held_action_id} is {current.status}, not approved"
            )
        return self._status_in_txn(held_action_id, "executed")

    def approved_not_executed(self) -> list[HeldAction]:
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM held_action WHERE status = 'approved' "
            "ORDER BY created_at, id"
        ).fetchall()
        return [_row_to_held_action(row) for row in rows]

    def expire_due(self, now: str) -> int:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = self._conn.execute(
                "UPDATE held_action SET status = 'expired' "
                "WHERE status = 'pending' AND expires_at <= ?",
                (now,),
            )
            self._conn.execute("COMMIT")
        except sqlite3.Error:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise
        return cursor.rowcount

    def pending(self) -> list[HeldAction]:
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM held_action WHERE status = 'pending' "
            "ORDER BY created_at, id"
        ).fetchall()
        return [_row_to_held_action(row) for row in rows]

    def _set_status(self, held_action_id: str, status: str) -> HeldAction:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            result = self._status_in_txn(held_action_id, status)
            self._conn.execute("COMMIT")
        except sqlite3.Error:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise
        return result

    def _status_in_txn(self, held_action_id: str, status: str) -> HeldAction:
        """The bare UPDATE, no transaction of its own — every public path
        above wraps this in BEGIN/COMMIT; `approve_in_txn`/`mark_executed_
        in_txn` let the caller's own transaction own it instead (ADR-021)."""
        self._conn.execute(
            "UPDATE held_action SET status = ? WHERE id = ?",
            (status, held_action_id),
        )
        return self.get(held_action_id)
