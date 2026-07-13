"""SqliteEventLog — the EventLog port over eventlog.db.

Layer: adapters/eventlog (SQL sanctioned here with adapters/sqlite —
DB-002's store-layer confinement covers both truth files).
Constitutional home: 15_EVENT_BUS §4 (pending → confirmed | orphaned),
§5.1/§5.2 (envelope ↔ row mapping), EB-003 (recovery_grade denormalized
per row). Delivery (cursors, dead letters) is M2's subject — the tables
exist per the DDL; no code touches them yet.
"""

from __future__ import annotations

import json
import sqlite3

from kang.domain.ports.clock import Clock
from kang.domain.ports.eventlog import (
    EventEnvelope,
    EventNotFoundError,
    StoredEvent,
    validate_envelope,
)

__all__ = ["SqliteEventLog"]

_COLUMNS = (
    "seq, event_id, type, type_version, occurred_at, recorded_at, principal, "
    "correlation_id, causation_id, entity_refs, payload, provenance, "
    "recovery_grade, device_id, state"
)


def _row_to_stored(row: tuple) -> StoredEvent:
    (
        seq,
        event_id,
        type_,
        type_version,
        occurred_at,
        recorded_at,
        principal,
        correlation_id,
        causation_id,
        entity_refs,
        payload,
        provenance,
        recovery_grade,
        device_id,
        state,
    ) = row
    envelope = EventEnvelope(
        event_id=event_id,
        type=type_,
        type_version=type_version,
        occurred_at=occurred_at,
        principal=principal,
        correlation_id=correlation_id,
        causation_id=causation_id,
        entity_refs=tuple(json.loads(entity_refs)),
        payload=json.loads(payload),
        provenance=provenance,
        recovery_grade=bool(recovery_grade),
        device_id=device_id,
    )
    return StoredEvent(seq=seq, envelope=envelope, recorded_at=recorded_at, state=state)


class SqliteEventLog:
    """EventLog implementation. Every append is validated (nothing invalid
    ever enters the log — 15 §13) and durable before return."""

    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self._conn = conn
        self._clock = clock

    def append(self, envelope: EventEnvelope) -> int:
        validate_envelope(envelope)
        cursor = self._conn.execute(
            "INSERT INTO event (event_id, type, type_version, occurred_at, "
            "recorded_at, principal, correlation_id, causation_id, "
            "entity_refs, payload, provenance, recovery_grade, device_id, "
            "state) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
            (
                envelope.event_id,
                envelope.type,
                envelope.type_version,
                envelope.occurred_at,
                self._clock.now().isoformat(),
                envelope.principal,
                envelope.correlation_id,
                envelope.causation_id,
                json.dumps(list(envelope.entity_refs)),
                json.dumps(envelope.payload, sort_keys=True),
                envelope.provenance,
                int(envelope.recovery_grade),
                envelope.device_id,
            ),
        )
        return int(cursor.lastrowid)

    def _set_state(self, seq: int, state: str) -> None:
        cursor = self._conn.execute(
            "UPDATE event SET state = ? WHERE seq = ?", (state, seq)
        )
        if cursor.rowcount == 0:
            raise EventNotFoundError(str(seq))

    def confirm(self, seq: int) -> None:
        self._set_state(seq, "confirmed")

    def mark_orphaned(self, seq: int) -> None:
        self._set_state(seq, "orphaned")

    def pending(self) -> list[StoredEvent]:
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM event WHERE state = 'pending' ORDER BY seq"
        ).fetchall()
        return [_row_to_stored(row) for row in rows]

    def read_from(self, seq_exclusive: int) -> list[StoredEvent]:
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM event WHERE seq > ? ORDER BY seq",
            (seq_exclusive,),
        ).fetchall()
        return [_row_to_stored(row) for row in rows]

    def find_by_event_id(self, event_id: str) -> StoredEvent | None:
        row = self._conn.execute(
            f"SELECT {_COLUMNS} FROM event WHERE event_id = ?", (event_id,)
        ).fetchone()
        return _row_to_stored(row) if row is not None else None

    def last_seq(self) -> int:
        row = self._conn.execute("SELECT MAX(seq) FROM event").fetchone()
        return int(row[0]) if row[0] is not None else 0
