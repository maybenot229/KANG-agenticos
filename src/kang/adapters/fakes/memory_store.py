"""FakeMemoryStore — in-memory MemoryStore, contract-paired (13 §2.3).

Layer: adapters/fakes. The same contract suite runs against this and
SqliteMemoryStore, so the fingerprint probe, the duplicate-id refusal, and the
revision guard are mirrored here rather than approximated.
"""

from __future__ import annotations

from kang.domain.ports.memory_store import (
    MemoryConflict,
    MemoryRecord,
    content_fingerprint,
)

__all__ = ["FakeMemoryStore"]


class FakeMemoryStore:
    def __init__(self) -> None:
        self._records: dict[str, MemoryRecord] = {}

    def insert_record(self, record: MemoryRecord) -> None:
        if record.id in self._records:
            raise ValueError(f"duplicate memory record {record.id}")
        self._records[record.id] = record

    def get(self, record_id: str) -> MemoryRecord | None:
        return self._records.get(record_id)

    def find_active_duplicate(self, memory_type: str, fingerprint: str) -> str | None:
        ordered = sorted(self._records.values(), key=lambda r: (r.created_at, r.id))
        for record in ordered:
            if (
                record.type == memory_type
                and record.status == "active"
                and record.sensitivity != "private"
                and content_fingerprint(record.content) == fingerprint
            ):
                return record.id
        return None

    def merge_provenance(self, merged: MemoryRecord, expected_revision: int) -> None:
        current = self._records.get(merged.id)
        if current is None or current.revision != expected_revision:
            raise MemoryConflict(
                f"memory record {merged.id} is not at revision {expected_revision}"
            )
        self._records[merged.id] = merged

    # Test/UoW support (not part of the port).
    def snapshot(self) -> dict[str, MemoryRecord]:
        return dict(self._records)

    def restore(self, state: dict[str, MemoryRecord]) -> None:
        self._records = dict(state)
