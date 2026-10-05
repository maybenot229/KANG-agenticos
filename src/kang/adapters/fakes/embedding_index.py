"""FakeEmbeddingIndex — in-memory EmbeddingIndex, contract-paired (13 §2.3).

Layer: adapters/fakes. Reads memory records from a `FakeMemoryStore`. The
real index loses a vector by trigger the moment its row's content,
sensitivity or retrievability changes, or the row is deleted (migration
`0022`); this fake mirrors those exact rules by listening to the fake
store's changes. Same observable behavior, checked by the same contract
suite.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Sequence

from kang.adapters.fakes.memory_store import FakeMemoryStore
from kang.domain.ports.embedding_index import (
    EMBEDDABLE_STATUSES,
    Coverage,
    EmbeddingIndexConflict,
    EmbeddingVersion,
    Neighbor,
    PendingRecord,
    VectorWrite,
)
from kang.domain.ports.memory_store import MemoryRecord

__all__ = ["FakeEmbeddingIndex"]


def _embeddable(record: MemoryRecord) -> bool:
    return record.status in EMBEDDABLE_STATUSES and record.sensitivity != "private"


def _cosine_distance(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norms = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return 1.0 - dot / norms if norms else 1.0


class FakeEmbeddingIndex:
    def __init__(
        self,
        memory: FakeMemoryStore,
        versions: Sequence[EmbeddingVersion] = (
            EmbeddingVersion(1, "nomic-embed-text", 768, "active"),
        ),
    ) -> None:
        self._memory = memory
        self._versions = {v.ver: v for v in versions}
        self._vectors: dict[int, dict[str, tuple[float, ...]]] = {
            v.ver: {} for v in versions
        }
        memory.listeners.append(self._invalidate)

    def _invalidate(self, before: MemoryRecord, after: MemoryRecord | None) -> None:
        """Migration 0022's triggers, mirrored."""
        if (
            after is None
            or after.content != before.content
            or after.sensitivity != before.sensitivity
            or after.status not in EMBEDDABLE_STATUSES
        ):
            for vectors in self._vectors.values():
                vectors.pop(before.id, None)

    # Test support (not part of the port): what a future migration does.
    def add_version(self, version: EmbeddingVersion) -> None:
        self._versions[version.ver] = version
        self._vectors[version.ver] = {}

    def _current(self, ver: int, record: MemoryRecord) -> bool:
        return record.id in self._vectors[ver] and _embeddable(record)

    def versions_to_fill(self) -> tuple[EmbeddingVersion, ...]:
        ordered = sorted(
            (v for v in self._versions.values() if v.status != "retired"),
            key=lambda v: (v.status != "active", v.ver),
        )
        return tuple(ordered)

    def pending_memory(self, ver: int, limit: int) -> tuple[PendingRecord, ...]:
        records = [
            r
            for r in self._memory.snapshot().values()
            if _embeddable(r) and not self._current(ver, r)
        ]
        records.sort(key=lambda r: r.id)
        records.sort(key=lambda r: r.updated_at, reverse=True)
        return tuple(
            PendingRecord(r.id, r.content, r.revision, r.sensitivity)
            for r in records[:limit]
        )

    def store_memory_vectors(self, ver: int, writes: Sequence[VectorWrite]) -> int:
        stored = 0
        for write in writes:
            record = self._memory.get(write.record.record_id)
            if (
                record is None
                or record.revision != write.record.revision
                or not _embeddable(record)
                or self._current(ver, record)
            ):
                continue
            self._vectors[ver][record.id] = tuple(write.vector)
            stored += 1
        return stored

    def memory_coverage(self, ver: int) -> Coverage:
        records = [r for r in self._memory.snapshot().values() if _embeddable(r)]
        embedded = sum(1 for r in records if self._current(ver, r))
        return Coverage(embedded=embedded, embeddable=len(records))

    def cut_over(self, ver: int) -> None:
        version = self._versions.get(ver)
        if version is None or version.status != "migrating":
            raise EmbeddingIndexConflict(
                f"embedding version {ver} is not 'migrating' — nothing to cut over"
            )
        if not self.memory_coverage(ver).is_complete:
            raise EmbeddingIndexConflict(
                f"embedding version {ver} is not fully covered — refusing to "
                "cut over to an incomplete space (DB-004)"
            )
        for other in list(self._versions.values()):
            if other.status == "active":
                self._versions[other.ver] = replace(other, status="retired")
        self._versions[ver] = replace(version, status="active")

    def nearest_memory(
        self, ver: int, vector: Sequence[float], k: int
    ) -> tuple[Neighbor, ...]:
        candidates = [
            Neighbor(r.id, _cosine_distance(vector, self._vectors[ver][r.id]))
            for r in self._memory.snapshot().values()
            if self._current(ver, r)
        ]
        candidates.sort(key=lambda n: (n.distance, n.record_id))
        return tuple(candidates[:k])
