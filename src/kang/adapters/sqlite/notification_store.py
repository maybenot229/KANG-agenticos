"""SqliteNotificationStore — the notification queue over kang.db.

Layer: adapters/sqlite (the only home of SQL — DB-002; no SELECT *, 11 §13).
Constitutional home: docs/adr/005-notification-queue-schema.md, 12_API §13
(acks are additive — `ack` stamps `acked_at` and never deletes), 15 §6.2
(`queued()` is the drain sweep that makes the event an accelerant).

`entity_refs` and `payload` are JSON in the column and structured data in
the domain; the translation is confined here, at the port line (17 §4.3.5).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from kang.domain.ports.notification_store import (
    Notification,
    NotificationNotFoundError,
)

__all__ = ["SqliteNotificationStore"]

_COLUMNS = (
    "id, priority, principal, correlation_id, entity_refs, payload, state, "
    "created_at, delivered_at, acked_at"
)


def _moment(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text is not None else None


def _row_to_notification(row: sqlite3.Row | tuple) -> Notification:
    (
        notification_id,
        priority,
        principal,
        correlation_id,
        entity_refs,
        payload,
        state,
        created_at,
        delivered_at,
        acked_at,
    ) = row
    return Notification(
        id=notification_id,
        priority=priority,
        principal=principal,
        correlation_id=correlation_id,
        entity_refs=tuple(json.loads(entity_refs)),
        payload=json.loads(payload),
        state=state,
        created_at=_moment(created_at),  # type: ignore[arg-type]
        delivered_at=_moment(delivered_at),
        acked_at=_moment(acked_at),
    )


class SqliteNotificationStore:
    """NotificationStore implementation. Writes are explicit transactions."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, notification: Notification) -> None:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._conn.execute(
                f"INSERT INTO notification ({_COLUMNS}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    notification.id,
                    notification.priority,
                    notification.principal,
                    notification.correlation_id,
                    json.dumps([dict(r) for r in notification.entity_refs]),
                    json.dumps(notification.payload),
                    notification.state,
                    notification.created_at.isoformat(),
                    notification.delivered_at.isoformat()
                    if notification.delivered_at
                    else None,
                    notification.acked_at.isoformat()
                    if notification.acked_at
                    else None,
                ),
            )
            self._conn.execute("COMMIT")
        except sqlite3.Error:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise

    def get(self, notification_id: str) -> Notification:
        row = self._conn.execute(
            f"SELECT {_COLUMNS} FROM notification WHERE id = ?", (notification_id,)
        ).fetchone()
        if row is None:
            raise NotificationNotFoundError(notification_id)
        return _row_to_notification(row)

    def queued(self) -> list[Notification]:
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM notification WHERE state = 'queued' "
            "ORDER BY created_at, id"
        ).fetchall()
        return [_row_to_notification(row) for row in rows]

    def set_state(self, notification_id: str, state: str, at: datetime) -> Notification:
        delivered = at.isoformat() if state == "delivered" else None
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = self._conn.execute(
                "UPDATE notification SET state = ?, "
                "delivered_at = COALESCE(?, delivered_at) WHERE id = ?",
                (state, delivered, notification_id),
            )
            if cursor.rowcount == 0:
                self._conn.execute("ROLLBACK")
                raise NotificationNotFoundError(notification_id)
            self._conn.execute("COMMIT")
        except sqlite3.Error:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise
        return self.get(notification_id)

    def ack(self, notification_id: str, at: datetime) -> Notification:
        # Additive: state moves to 'acked' and acked_at is stamped; nothing
        # is cleared, nothing is deleted (12 §13).
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = self._conn.execute(
                "UPDATE notification SET state = 'acked', acked_at = ? WHERE id = ?",
                (at.isoformat(), notification_id),
            )
            if cursor.rowcount == 0:
                self._conn.execute("ROLLBACK")
                raise NotificationNotFoundError(notification_id)
            self._conn.execute("COMMIT")
        except sqlite3.Error:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise
        return self.get(notification_id)

    def recent_matching(
        self, entity_refs: tuple[dict[str, str], ...], priority: str, since: datetime
    ) -> list[Notification]:
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM notification "
            "WHERE priority = ? AND entity_refs = ? AND created_at >= ? "
            # only rows that actually reached Kang can be re-notified (port
            # docstring): 'queued' is undecided, 'suppressed' never surfaced
            "AND state IN ('delivered', 'batched', 'acked') "
            "ORDER BY created_at, id",
            (
                priority,
                json.dumps([dict(r) for r in entity_refs]),
                since.isoformat(),
            ),
        ).fetchall()
        return [_row_to_notification(row) for row in rows]
