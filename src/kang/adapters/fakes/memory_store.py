"""FakeMemoryStore — in-memory MemoryStore, contract-paired (13 §2.3).

Layer: adapters/fakes. The same contract suite runs against this and
SqliteMemoryStore, so the fingerprint probe, the duplicate-id refusal, and the
revision guard are mirrored here rather than approximated.
"""

from __future__ import annotations

from dataclasses import replace

from kang.domain.ports.memory_store import (
    ContentEdit,
    MemoryConflict,
    MemoryRecord,
    content_fingerprint,
)

__all__ = ["FakeMemoryStore"]


class FakeMemoryStore:
    def __init__(self) -> None:
        self._records: dict[str, MemoryRecord] = {}
        # Test/UoW support: (record_id, revision) -> prior content, mirroring
        # memory_revision's own primary key shape (ADR-053 D3).
        self._revisions: dict[tuple[str, int], dict] = {}
        self._tombstones: dict[str, dict] = {}

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

    def update_content(self, edit: ContentEdit) -> MemoryRecord:
        current = self._records.get(edit.record_id)
        if current is None or current.revision != edit.expected_revision:
            raise MemoryConflict(
                f"memory record {edit.record_id} is not at revision "
                f"{edit.expected_revision}"
            )
        self._revisions[(edit.record_id, edit.expected_revision)] = {
            "content": current.content,
            "edited_by": edit.edited_by,
            "edited_at": edit.now,
            "device_id": edit.device_id,
        }
        updated = replace(
            current,
            content=edit.content,
            reason=edit.reason,
            revision=edit.expected_revision + 1,
            updated_at=edit.now,
            device_id=edit.device_id,
        )
        self._records[edit.record_id] = updated
        return updated

    def set_pinned(
        self, record_id: str, pinned: bool, device_id: str, now: str
    ) -> MemoryRecord:
        current = self._records.get(record_id)
        if current is None:
            raise MemoryConflict(f"no memory record {record_id}")
        updated = replace(
            current,
            pinned=pinned,
            revision=current.revision + 1,
            updated_at=now,
            device_id=device_id,
        )
        self._records[record_id] = updated
        return updated

    def transition_status(
        self,
        record_id: str,
        expected_status: str,
        new_status: str,
        device_id: str,
        now: str,
    ) -> MemoryRecord:
        current = self._records.get(record_id)
        if current is None or current.status != expected_status:
            raise MemoryConflict(
                f"memory record {record_id} is not {expected_status!r}"
            )
        updated = replace(
            current,
            status=new_status,
            revision=current.revision + 1,
            updated_at=now,
            device_id=device_id,
        )
        self._records[record_id] = updated
        return updated

    def delete_and_tombstone_in_txn(
        self, record_id: str, deleted_by: str, now: str
    ) -> None:
        current = self._records.get(record_id)
        if current is None or current.status != "archived":
            raise MemoryConflict(
                f"memory record {record_id} is not 'archived' (or does not "
                "exist) — memory.delete refuses every edge but archived -> "
                "deleted (M-002)"
            )
        del self._records[record_id]
        self._tombstones[record_id] = {
            "entity": "memory_record",
            "deleted_at": now,
            "deleted_by": deleted_by,
            "policy_ref": "kang:explicit",
        }

    # Test/UoW support (not part of the port).
    def snapshot(self) -> dict[str, MemoryRecord]:
        return dict(self._records)

    def restore(self, state: dict[str, MemoryRecord]) -> None:
        self._records = dict(state)
