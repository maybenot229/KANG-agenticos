"""SqliteConversationStore — chat transcript persistence over kang.db
(ADR-046).

Layer: adapters/sqlite (SQL confined here — DB-002).
Constitutional home: 07_DATABASE §5.5 (`conversation`/`message` schema,
migration 0019), docs/adr/046-chat-conversation-history.md. `append_
message` bumps the parent conversation's `message_count`/`last_message`
in the SAME transaction as the insert — never a separate caller-driven
step that could leave the two out of sync.
"""

from __future__ import annotations

import sqlite3

from kang.domain.ports.conversation_store import (
    Conversation,
    ConversationNotFound,
    Message,
)

__all__ = ["SqliteConversationStore"]

_CONVERSATION_COLUMNS = "id, started, last_message, title, message_count, purged"
_MESSAGE_COLUMNS = "id, conversation_id, role, content, at"


def _row_to_conversation(row: sqlite3.Row | tuple) -> Conversation:
    return Conversation(
        id=row[0],
        started=row[1],
        last_message=row[2],
        title=row[3],
        message_count=row[4],
        purged=bool(row[5]),
    )


def _row_to_message(row: sqlite3.Row | tuple) -> Message:
    return Message(
        id=row[0],
        conversation_id=row[1],
        role=row[2],
        content=row[3],
        at=row[4],
    )


class SqliteConversationStore:
    """ConversationStore over kang.db."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def start(self, conversation_id: str, started_at: str) -> Conversation:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._conn.execute(
                f"INSERT INTO conversation ({_CONVERSATION_COLUMNS}) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (conversation_id, started_at, started_at, None, 0, 0),
            )
            self._conn.execute("COMMIT")
        except sqlite3.Error:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise
        return Conversation(
            id=conversation_id,
            started=started_at,
            last_message=started_at,
            title=None,
            message_count=0,
            purged=False,
        )

    def get(self, conversation_id: str) -> Conversation | None:
        row = self._conn.execute(
            f"SELECT {_CONVERSATION_COLUMNS} FROM conversation WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        return _row_to_conversation(row) if row else None

    def append_message(
        self, conversation_id: str, message_id: str, role: str, content: str, at: str
    ) -> Message:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            updated = self._conn.execute(
                "UPDATE conversation SET last_message = ?, "
                "message_count = message_count + 1 WHERE id = ?",
                (at, conversation_id),
            )
            if updated.rowcount == 0:
                self._conn.execute("ROLLBACK")
                raise ConversationNotFound(
                    f"no conversation {conversation_id!r} to append a message to"
                )
            self._conn.execute(
                f"INSERT INTO message ({_MESSAGE_COLUMNS}) VALUES (?, ?, ?, ?, ?)",
                (message_id, conversation_id, role, content, at),
            )
            self._conn.execute("COMMIT")
        except sqlite3.Error:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise
        return Message(
            id=message_id,
            conversation_id=conversation_id,
            role=role,
            content=content,
            at=at,
        )

    def recent_messages(self, conversation_id: str, limit: int) -> tuple[Message, ...]:
        rows = self._conn.execute(
            f"SELECT {_MESSAGE_COLUMNS} FROM message WHERE conversation_id = ? "
            "ORDER BY at DESC, id DESC LIMIT ?",
            (conversation_id, limit),
        ).fetchall()
        return tuple(_row_to_message(row) for row in reversed(rows))
