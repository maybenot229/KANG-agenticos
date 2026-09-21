"""MemoryStore port — the `memory_record` table (ADR-051 D10; ADR-048).

Layer: domain/ports. Ports own their datatypes (17 §7).
Constitutional home: 07_DATABASE §5.1 (`memory_record`, as migrated by
`0020`/`0021`), 06_MEMORY Part II (the closed taxonomy), M-002 (this port is
the *lifecycle* half; admission is the write gate's), ADR-048 D2 (the integer
`rowid` alias is storage-local: no datatype in this module carries it).

There is exactly ONE method that brings a `memory_record` row into existence,
`insert_record`. Kang's auto-pass and `memory.approve` both reach it through
the same API-layer helper — two insert paths is how a second door gets built
by accident (ADR-051 D3/D10; a structural test pins it).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

__all__ = [
    "MEMORY_STATUSES",
    "MEMORY_TYPES",
    "SENSITIVITIES",
    "SOURCE_KINDS",
    "TRUST_TIERS",
    "MemoryConflict",
    "MemoryRecord",
    "MemoryStore",
    "content_fingerprint",
]

# 06 §2.1A / 07 §5.1: the closed taxonomy the schema's CHECKs enforce.
MEMORY_TYPES = (
    "profile",
    "preference",
    "fact",
    "relationship",
    "lesson",
    "rule",
    "observation",
    "reflection",
)
# ADR-048 D1: `candidate`/`rejected` live only in the queue, never here.
MEMORY_STATUSES = ("active", "under_review", "superseded", "archived")
SENSITIVITIES = ("normal", "sensitive", "private")
SOURCE_KINDS = ("stated", "observed", "vault", "web", "rule", "consolidation")
TRUST_TIERS = (0, 1, 2)


def content_fingerprint(content: str) -> str:
    """06 §4.2's exact-duplicate probe: a hash of the case- and
    whitespace-folded content. One definition, shared by the gate's caller
    and the adapter, so the two can never disagree about "the same"."""
    folded = " ".join(content.casefold().split())
    return hashlib.sha256(folded.encode("utf-8")).hexdigest()


class MemoryConflict(Exception):
    """An optimistic revision check failed (the row moved under the writer)."""


@dataclass(frozen=True)
class MemoryRecord:
    """One `memory_record` row, every column but the storage-local rowid.
    Timestamps are ISO-8601 strings, mirroring the columns."""

    id: str
    type: str
    status: str
    content: str
    trust_tier: int
    confidence: float
    sensitivity: str
    source_kind: str
    source_detail: str
    reason: str
    created_by: str
    created_at: str
    updated_at: str
    device_id: str
    revision: int
    source_quote: str | None = None
    content_enc: bytes | None = None
    importance: float = 0.5
    pinned: bool = False
    last_accessed: str | None = None
    access_count: int = 0
    embedding_ver: int | None = None


class MemoryStore(Protocol):
    """Persistence port for memory records."""

    def insert_record(self, record: MemoryRecord) -> None:
        """Create the row — the only way one comes into existence. Joins an
        already-open transaction if the caller holds one (ADR-051 D3)."""
        ...

    def get(self, record_id: str) -> MemoryRecord | None: ...

    def find_active_duplicate(self, memory_type: str, fingerprint: str) -> str | None:
        """The id of an `active`, non-`private` record of `memory_type`
        whose `content_fingerprint` equals `fingerprint`, else None
        (06 §4.2's exact-hash probe; the semantic probes are D5's dated
        absence)."""
        ...

    def merge_provenance(self, merged: MemoryRecord, expected_revision: int) -> None:
        """Persist a silent merge (06 §4.2): the incumbent's provenance,
        revision, and stamps as `merged` states them, guarded on
        `expected_revision`. Raises `MemoryConflict` if the row moved."""
        ...
