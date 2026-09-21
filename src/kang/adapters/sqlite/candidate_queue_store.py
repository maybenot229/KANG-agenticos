"""SqliteCandidateQueueStore — the CandidateQueueStore port over kang.db
(ADR-051 D10; ADR-048 D1).

Layer: adapters/sqlite (DB-002; no SELECT *, 11 §13).
Constitutional home: 07_DATABASE §5.1 (`memory_candidate_queue`: no sync
quartet, no change capture — operational, never synchronized), 06_MEMORY
§4.3 (the queue's contract; silence is a veto at `expires_at`).
"""

from __future__ import annotations

import json
import sqlite3

from kang.adapters.sqlite.transaction import writing
from kang.domain.ports.candidate_queue_store import CANDIDATE_RESOLUTIONS, Candidate

__all__ = ["SqliteCandidateQueueStore"]

_COLUMNS = (
    "id, payload, flags, flag_context, proposed_at, expires_at, resolved, resolved_at"
)


def _row_to_candidate(row: tuple) -> Candidate:
    (
        candidate_id,
        payload,
        flags,
        flag_context,
        proposed_at,
        expires_at,
        resolved,
        resolved_at,
    ) = row
    return Candidate(
        id=candidate_id,
        payload=json.loads(payload),
        flags=tuple(json.loads(flags)),
        flag_context=flag_context,
        proposed_at=proposed_at,
        expires_at=expires_at,
        resolved=resolved,
        resolved_at=resolved_at,
    )


class SqliteCandidateQueueStore:
    """CandidateQueueStore implementation."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def enqueue(self, candidate: Candidate) -> None:
        with writing(self._conn):
            self._conn.execute(
                f"INSERT INTO memory_candidate_queue ({_COLUMNS}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    candidate.id,
                    json.dumps(candidate.payload, sort_keys=True),
                    json.dumps(list(candidate.flags)),
                    candidate.flag_context,
                    candidate.proposed_at,
                    candidate.expires_at,
                    candidate.resolved,
                    candidate.resolved_at,
                ),
            )

    def get(self, candidate_id: str) -> Candidate | None:
        row = self._conn.execute(
            f"SELECT {_COLUMNS} FROM memory_candidate_queue WHERE id = ?",
            (candidate_id,),
        ).fetchone()
        return _row_to_candidate(row) if row is not None else None

    def list_queue(self, limit: int) -> tuple[Candidate, ...]:
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM memory_candidate_queue "
            "ORDER BY (resolved IS NOT NULL), proposed_at, "
            "json_extract(payload, '$.confidence') DESC, id LIMIT ?",
            (limit,),
        ).fetchall()
        return tuple(_row_to_candidate(row) for row in rows)

    def resolve(self, candidate_id: str, resolution: str, at: str) -> bool:
        if resolution not in CANDIDATE_RESOLUTIONS:
            raise ValueError(f"resolution must be one of {CANDIDATE_RESOLUTIONS}")
        with writing(self._conn):
            cursor = self._conn.execute(
                "UPDATE memory_candidate_queue SET resolved = ?, resolved_at = ? "
                "WHERE id = ? AND resolved IS NULL",
                (resolution, at, candidate_id),
            )
        return cursor.rowcount > 0

    def expire_due(self, now: str) -> tuple[str, ...]:
        with writing(self._conn):
            due = [
                row[0]
                for row in self._conn.execute(
                    "SELECT id FROM memory_candidate_queue "
                    "WHERE resolved IS NULL AND expires_at < ? "
                    "ORDER BY expires_at, id",
                    (now,),
                )
            ]
            for candidate_id in due:
                self._conn.execute(
                    "UPDATE memory_candidate_queue SET resolved = 'expired', "
                    "resolved_at = ? WHERE id = ?",
                    (now, candidate_id),
                )
        return tuple(due)
