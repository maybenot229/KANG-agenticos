"""SqliteMemoryStore — the MemoryStore port over kang.db (ADR-051 D10).

Layer: adapters/sqlite (the only home of SQL — DB-002; no SELECT *, 11 §13).
Constitutional home: 07_DATABASE §5.1 (`memory_record`, migrations
`0020`/`0021`), ADR-048 D2 (the integer `rowid` alias is used by the FTS
triggers and by nothing here — it never appears in a query result or a
returned datatype).

`INSERT INTO memory_record` appears exactly once in `src/` outside the
recovery applier's redo of a gate-published event: `insert_record`. The change
capture and FTS sync triggers fire from the schema, not from this module.
"""

from __future__ import annotations

import sqlite3

from kang.adapters.sqlite.transaction import writing
from kang.domain.ports.memory_store import (
    ContentEdit,
    MemoryConflict,
    MemoryRecord,
    content_fingerprint,
)

__all__ = ["SqliteMemoryStore"]

_COLUMNS = (
    "id, type, status, content, trust_tier, confidence, sensitivity, "
    "content_enc, source_kind, source_detail, source_quote, reason, "
    "created_by, created_at, updated_at, device_id, revision, importance, "
    "pinned, last_accessed, access_count, embedding_ver"
)


def _row_to_record(row: tuple) -> MemoryRecord:
    (
        record_id,
        mtype,
        status,
        content,
        trust_tier,
        confidence,
        sensitivity,
        content_enc,
        source_kind,
        source_detail,
        source_quote,
        reason,
        created_by,
        created_at,
        updated_at,
        device_id,
        revision,
        importance,
        pinned,
        last_accessed,
        access_count,
        embedding_ver,
    ) = row
    return MemoryRecord(
        id=record_id,
        type=mtype,
        status=status,
        content=content,
        trust_tier=trust_tier,
        confidence=confidence,
        sensitivity=sensitivity,
        content_enc=content_enc,
        source_kind=source_kind,
        source_detail=source_detail,
        source_quote=source_quote,
        reason=reason,
        created_by=created_by,
        created_at=created_at,
        updated_at=updated_at,
        device_id=device_id,
        revision=revision,
        importance=importance,
        pinned=bool(pinned),
        last_accessed=last_accessed,
        access_count=access_count,
        embedding_ver=embedding_ver,
    )


class SqliteMemoryStore:
    """MemoryStore implementation. Writes join an open transaction or run
    their own (`transaction.writing`)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def insert_record(self, record: MemoryRecord) -> None:
        with writing(self._conn):
            self._conn.execute(
                f"INSERT INTO memory_record ({_COLUMNS}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                "?, ?, ?, ?)",
                (
                    record.id,
                    record.type,
                    record.status,
                    record.content,
                    record.trust_tier,
                    record.confidence,
                    record.sensitivity,
                    record.content_enc,
                    record.source_kind,
                    record.source_detail,
                    record.source_quote,
                    record.reason,
                    record.created_by,
                    record.created_at,
                    record.updated_at,
                    record.device_id,
                    record.revision,
                    record.importance,
                    int(record.pinned),
                    record.last_accessed,
                    record.access_count,
                    record.embedding_ver,
                ),
            )

    def get(self, record_id: str) -> MemoryRecord | None:
        row = self._conn.execute(
            f"SELECT {_COLUMNS} FROM memory_record WHERE id = ?", (record_id,)
        ).fetchone()
        return _row_to_record(row) if row is not None else None

    def find_active_duplicate(self, memory_type: str, fingerprint: str) -> str | None:
        # No content-hash column exists (ADR-048 landed none, and this slice
        # adds no migration): fold-and-compare in Python over the same-type
        # active rows. `private` rows hold only the '[encrypted]' placeholder
        # and are never candidates.
        rows = self._conn.execute(
            "SELECT id, content FROM memory_record WHERE type = ? "
            "AND status = 'active' AND sensitivity <> 'private' "
            "ORDER BY created_at, id",
            (memory_type,),
        )
        for record_id, content in rows:
            if content_fingerprint(content) == fingerprint:
                return record_id
        return None

    def merge_provenance(self, merged: MemoryRecord, expected_revision: int) -> None:
        with writing(self._conn):
            cursor = self._conn.execute(
                "UPDATE memory_record SET source_detail = ?, revision = ?, "
                "updated_at = ?, device_id = ? WHERE id = ? AND revision = ?",
                (
                    merged.source_detail,
                    merged.revision,
                    merged.updated_at,
                    merged.device_id,
                    merged.id,
                    expected_revision,
                ),
            )
            if cursor.rowcount == 0:
                raise MemoryConflict(
                    f"memory record {merged.id} is not at revision {expected_revision}"
                )

    def update_content(self, edit: ContentEdit) -> MemoryRecord:
        with writing(self._conn):
            current = self._conn.execute(
                "SELECT content FROM memory_record WHERE id = ? AND revision = ?",
                (edit.record_id, edit.expected_revision),
            ).fetchone()
            if current is None:
                raise MemoryConflict(
                    f"memory record {edit.record_id} is not at revision "
                    f"{edit.expected_revision}"
                )
            self._conn.execute(
                "INSERT INTO memory_revision "
                "(record_id, revision, content, edited_by, edited_at, device_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    edit.record_id,
                    edit.expected_revision,
                    current[0],
                    edit.edited_by,
                    edit.now,
                    edit.device_id,
                ),
            )
            self._conn.execute(
                "UPDATE memory_record SET content = ?, reason = ?, "
                "revision = revision + 1, updated_at = ?, device_id = ? "
                "WHERE id = ? AND revision = ?",
                (
                    edit.content,
                    edit.reason,
                    edit.now,
                    edit.device_id,
                    edit.record_id,
                    edit.expected_revision,
                ),
            )
        return self.get(edit.record_id)  # type: ignore[return-value]

    def set_pinned(
        self, record_id: str, pinned: bool, device_id: str, now: str
    ) -> MemoryRecord:
        with writing(self._conn):
            cursor = self._conn.execute(
                "UPDATE memory_record SET pinned = ?, revision = revision + 1, "
                "updated_at = ?, device_id = ? WHERE id = ?",
                (int(pinned), now, device_id, record_id),
            )
            if cursor.rowcount == 0:
                raise MemoryConflict(f"no memory record {record_id}")
        return self.get(record_id)  # type: ignore[return-value]

    def transition_status(
        self,
        record_id: str,
        expected_status: str,
        new_status: str,
        device_id: str,
        now: str,
    ) -> MemoryRecord:
        with writing(self._conn):
            cursor = self._conn.execute(
                "UPDATE memory_record SET status = ?, revision = revision + 1, "
                "updated_at = ?, device_id = ? WHERE id = ? AND status = ?",
                (new_status, now, device_id, record_id, expected_status),
            )
            if cursor.rowcount == 0:
                raise MemoryConflict(
                    f"memory record {record_id} is not {expected_status!r}"
                )
        return self.get(record_id)  # type: ignore[return-value]

    def delete_and_tombstone_in_txn(
        self, record_id: str, deleted_by: str, now: str
    ) -> None:
        # No `writing()` wrapper (no transaction of its own — see the port's
        # docstring): the caller (`held_action.approve`'s transactional
        # driver) already holds `BEGIN IMMEDIATE`.
        cursor = self._conn.execute(
            "DELETE FROM memory_record WHERE id = ? AND status = 'archived'",
            (record_id,),
        )
        if cursor.rowcount == 0:
            raise MemoryConflict(
                f"memory record {record_id} is not 'archived' (or does not "
                "exist) — memory.delete refuses every edge but archived -> "
                "deleted (M-002)"
            )
        self._conn.execute(
            "INSERT INTO tombstone (id, entity, deleted_at, deleted_by, policy_ref) "
            "VALUES (?, 'memory_record', ?, ?, 'kang:explicit')",
            (record_id, now, deleted_by),
        )
