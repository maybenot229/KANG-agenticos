"""EmbeddingIndex port — the `embedding_version` table and the `vec_*` tables
(ADR-055 D6).

Layer: domain/ports. Ports own their datatypes (17 §7).
Constitutional home: 07_DATABASE Part VIII DB-004 (one vector table per
version, never mixed; the dual-index upgrade protocol), §6.2 (vector tables
are derived, built by the embedding worker), DB-003's dated clarification
(the vec tables bind to the storage-local rowid — no datatype here carries
one), 06_MEMORY Part III (which statuses are retrievable: `active` and
`under_review`), §12.1 (`private` is excluded from all retrieval).

Invalidation is not this port's job: migration `0022`'s triggers delete a
vector when its row's content, sensitivity or retrievability changes, or the
row is deleted (ADR-055 D4). This port only *creates* vectors, guarded, and
reads them. "Has a current vector in version n" means "has a row in that
version's vector table" — `memory_record.embedding_ver` is not written
(ADR-055 D5).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

__all__ = [
    "EMBEDDABLE_STATUSES",
    "Coverage",
    "EmbeddingIndex",
    "EmbeddingIndexConflict",
    "EmbeddingVersion",
    "Neighbor",
    "PendingRecord",
    "VectorWrite",
]

# 06 Part III: `under_review` is "still retrievable but marked contested";
# `superseded`/`archived` leave the vector index.
EMBEDDABLE_STATUSES = ("active", "under_review")


class EmbeddingIndexConflict(Exception):
    """A cutover was asked of a version that is not `migrating`, or is not
    yet fully covered — the protocol refuses rather than cutting over to an
    incomplete space (DB-004: no retrieval blackout)."""


@dataclass(frozen=True)
class EmbeddingVersion:
    """One `embedding_version` row."""

    ver: int
    model: str
    dim: int
    status: str  # 'active' | 'migrating' | 'retired'


@dataclass(frozen=True)
class PendingRecord:
    """A retrievable, non-private memory record with no vector yet in the
    version it was read for. `revision` is the guard a later write checks:
    a record edited, archived or re-sensitised in between is skipped, never
    stored stale."""

    record_id: str
    content: str
    revision: int
    sensitivity: str


@dataclass(frozen=True)
class VectorWrite:
    record: PendingRecord
    vector: tuple[float, ...]


@dataclass(frozen=True)
class Coverage:
    """How many currently-embeddable records a version holds a vector for."""

    embedded: int
    embeddable: int

    @property
    def is_complete(self) -> bool:
        return self.embedded >= self.embeddable


@dataclass(frozen=True)
class Neighbor:
    record_id: str
    distance: float  # cosine distance: 0 = identical direction


class EmbeddingIndex(Protocol):
    def versions_to_fill(self) -> tuple[EmbeddingVersion, ...]:
        """The `active` version first, then any `migrating` one (ADR-055 D8:
        new rows must become searchable before a migration progresses)."""
        ...

    def pending_memory(self, ver: int, limit: int) -> tuple[PendingRecord, ...]:
        """Up to `limit` retrievable, non-private records with no vector in
        `ver` — most recently updated first (DB-004: hot rows first)."""
        ...

    def store_memory_vectors(self, ver: int, writes: Sequence[VectorWrite]) -> int:
        """Store each vector only if its record is still at the read
        revision, still retrievable, still non-private, and still has no
        vector in `ver`; one transaction. Returns how many were stored —
        the rest were skipped as stale, never written."""
        ...

    def memory_coverage(self, ver: int) -> Coverage: ...

    def cut_over(self, ver: int) -> None:
        """`ver` (`migrating`) becomes `active`; the previous `active`
        becomes `retired`; one transaction. Raises `EmbeddingIndexConflict`
        if `ver` is not `migrating` or its coverage is incomplete."""
        ...

    def nearest_memory(
        self, ver: int, vector: Sequence[float], k: int
    ) -> tuple[Neighbor, ...]:
        """The `k` nearest records in `ver` by cosine distance, nearest
        first, ties broken by record id. Only records holding a vector in
        `ver` can appear."""
        ...
