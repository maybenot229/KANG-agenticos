"""MemoryStore port — the `memory_record` table (ADR-051 D10; ADR-048).

Layer: domain/ports. Ports own their datatypes (17 §7).
Constitutional home: 07_DATABASE §5.1 (`memory_record`, as migrated by
`0020`/`0021`), 06_MEMORY Part II (the closed taxonomy), M-002 (this port is
the *lifecycle* half; admission is the write gate's), ADR-048 D2 (the integer
`rowid` alias is storage-local: no datatype in this module carries it).

There is exactly ONE method that brings a `memory_record` row into existence
via the write gate, `insert_record`. Kang's auto-pass and `memory.approve`
both reach it through the same API-layer helper — two insert paths is how a
second door gets built by accident (ADR-051 D3/D10; a structural test pins
it). `memory.restore_from_snapshot` (ADR-053 D5) is a deliberately separate
mechanism — reviving a row the gate never admitted this session, from a
backup file, entirely inside `BackupService` (ADR-053's own Consequences:
the backup adapter gains direct knowledge of this schema) — so it does not
call `insert_record` and is not a second door to the gate's `active` state
(a restored row's status is whatever it was when deleted, never `active`
by construction: `memory.delete` only ever accepts an `archived` row).

ADR-053 D3 adds the lifecycle half proper: `update_content` (revision-
checked edits, with history), `set_pinned` (idempotent), `transition_status`
(archive/restore), `delete_and_tombstone_in_txn` (the one irreversible op,
run inside an already-open transaction — ADR-021's `transactional_effects`
shape). Every guarded write here follows `merge_provenance`'s own precedent:
one exception, `MemoryConflict`, for "the row did not match what the caller
expected" — existence is the caller's own `get()` check first (12 §7's
handlers already fetch-then-act), so a guard failing here is always a
genuine race, never a disguised not-found.
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
    "ContentEdit",
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
class ContentEdit:
    """`update_content`'s parameters, bundled (11 §4 — beyond a few
    parameters, a dataclass). `edited_by` is the editing principal;
    `device_id` is the editing device (ADR-048's amendment — never the
    record's own)."""

    record_id: str
    content: str
    reason: str
    expected_revision: int
    edited_by: str
    device_id: str
    now: str


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

    def update_content(self, edit: ContentEdit) -> MemoryRecord:
        """`memory.update` (ADR-053 D3): writes the record's *current*
        content into `memory_revision` at its current revision (06 §8.2 —
        edits never overwrite silently), stamped with the editing
        `device_id` (ADR-048's amendment: NOT the record's own), then sets
        `content`/`reason`, bumps `revision`, stamps `updated_at`. Only
        `content`/`reason` change — never `type`/`trust_tier`/`sensitivity`/
        `status`. Guarded on `edit.expected_revision`; raises
        `MemoryConflict` if the row moved."""
        ...

    def set_pinned(
        self, record_id: str, pinned: bool, device_id: str, now: str
    ) -> MemoryRecord:
        """`memory.pin` (ADR-053 D3): sets `pinned` to the given state —
        takes the desired value, so calling it twice with the same value is
        a no-op in effect (06 §5.2). Still bumps `revision`/`updated_at` (so
        `memory.updated`'s recovery replay, keyed on revision, is never a
        false no-op) but carries no optimistic-concurrency guard: there is
        nothing to conflict over when the caller states the end state
        directly. Raises `MemoryConflict` only if the id does not exist."""
        ...

    def transition_status(
        self,
        record_id: str,
        expected_status: str,
        new_status: str,
        device_id: str,
        now: str,
    ) -> MemoryRecord:
        """`memory.archive` (`active` → `archived`) / `memory.restore`
        (`archived` → `active`) (ADR-053 D3): guarded on `expected_status`,
        not just existence — the guard IS the safety property (M-002 has no
        `active` → `deleted` edge; this method is how `archive`/`restore`
        stay confined to the edges the table actually has). Raises
        `MemoryConflict` if the row is not at `expected_status`."""
        ...

    def delete_and_tombstone_in_txn(
        self, record_id: str, deleted_by: str, now: str
    ) -> None:
        """`memory.delete` (ADR-053 D4): the one irreversible write. No
        transaction of its own — `held_action.approve`'s transactional
        driver calls this on its own already-open transaction (mirrors
        `SqliteJobStore.set_enabled_in_txn`'s shape). Deletes the row only
        when it is currently `archived` (M-002 has no `active` → `deleted`
        edge — enforced here, not only by the handler that requested
        confirmation, since state can move between request and approval);
        the delete cascades `memory_revision` (`ON DELETE CASCADE`) and
        fires the FTS and change-capture delete triggers. Inserts the
        content-free `tombstone` row (`policy_ref='kang:explicit'`, 06
        §1.5 covenant 3). Raises `MemoryConflict` if the row is not
        `archived` (including: gone already)."""
        ...
