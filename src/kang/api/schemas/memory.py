"""Request/response schemas for `memory.*` and `candidate.*` operations
(ADR-051 D3; ADR-052 D3; ADR-010 Ruling 1).

Layer: api.
Constitutional home: 12_API §2/§10, 06_MEMORY §4.2 (the gate's required
metadata), ADR-051. No schema here carries the storage-local integer rowid
(ADR-048 D2) — a structural test sweeps every model in this package.

The writer's identity is deliberately NOT a request field: `created_by` is the
authenticated session's principal, never a claim in the body. Unknown body
keys are ignored, so a caller cannot smuggle one in.
"""

from __future__ import annotations

from pydantic import BaseModel

from kang.api.schemas.conversation import DEFAULT_LIMIT, MAX_LIMIT

__all__ = [
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "CandidateExpireRequest",
    "CandidateExpireResponse",
    "CandidateListItem",
    "CandidateListRequest",
    "CandidateListResponse",
    "MemoryApproveRequest",
    "MemoryApproveResponse",
    "MemoryArchiveRequest",
    "MemoryArchiveResponse",
    "MemoryDeleteRequest",
    "MemoryEditApproveRequest",
    "MemoryPinRequest",
    "MemoryPinResponse",
    "MemoryProposeRequest",
    "MemoryProposeResponse",
    "MemoryRejectRequest",
    "MemoryRejectResponse",
    "MemoryRestoreFromSnapshotRequest",
    "MemoryRestoreFromSnapshotResponse",
    "MemoryRestoreRequest",
    "MemoryRestoreResponse",
    "MemoryUpdateRequest",
    "MemoryUpdateResponse",
]


class MemoryProposeRequest(BaseModel):
    """`memory.propose` params: 06 §4.2's required metadata. The gate, not
    this schema, owns validity (so its typed rejections are the one error
    surface); `confidence` orders the queue and nothing else (M-003)."""

    type: str
    content: str
    trust_tier: int
    source_kind: str
    source_detail: str
    reason: str
    confidence: float = 1.0
    sensitivity: str = "normal"
    source_quote: str | None = None


class MemoryProposeResponse(BaseModel):
    """`outcome` is `admitted` (Kang's first-party save: `id` is the new
    record), `merged` (an exact duplicate: `id` is the incumbent), or
    `queued` (everyone else: `id` is the candidate, `expires_at` its veto
    deadline)."""

    outcome: str
    id: str
    revision: int | None = None
    expires_at: str | None = None


class MemoryApproveRequest(BaseModel):
    candidate_id: str


class MemoryApproveResponse(BaseModel):
    """`id` is the queue row's id, which is the record's id (ADR-048 D1)."""

    id: str
    revision: int


class MemoryEditApproveRequest(BaseModel):
    """Approve with Kang's edited content; the edit is the resolution, not a
    revision (revision 1 is what lands). `trust_tier` is optional (ADR-052
    D3): present, the landed record carries it — the one path by which a
    non-Kang-originated record reaches Tier 2, an explicit Kang act; absent,
    the proposal's own tier lands unchanged, exactly as before this ADR."""

    candidate_id: str
    content: str
    trust_tier: int | None = None


class MemoryRejectRequest(BaseModel):
    candidate_id: str


class MemoryRejectResponse(BaseModel):
    id: str
    resolved: str


class CandidateListRequest(BaseModel):
    limit: int | None = None


class CandidateListItem(BaseModel):
    id: str
    type: str
    content: str
    trust_tier: int
    source_kind: str
    source_detail: str
    reason: str
    confidence: float
    sensitivity: str
    created_by: str
    proposed_at: str
    expires_at: str
    resolved: str | None
    resolved_at: str | None
    flags: list[str]


class CandidateListResponse(BaseModel):
    """The approval queue: pending first, oldest first, then resolved."""

    candidates: list[CandidateListItem]


class CandidateExpireRequest(BaseModel):
    """The handler ignores `params`, like `conversation.purge`."""


class CandidateExpireResponse(BaseModel):
    """`count` is legitimately zero on most runs — a normal outcome."""

    expired: list[str]
    count: int


# ---- the lifecycle operations (ADR-053 D3) --------------------------------


class MemoryUpdateRequest(BaseModel):
    """`memory.update`: edits `content`/`reason` of an `active` record.
    `expected_revision` is the optimistic-concurrency guard (06 §8.2) — a
    stale value refuses with `conflict`."""

    id: str
    content: str
    reason: str
    expected_revision: int


class MemoryUpdateResponse(BaseModel):
    id: str
    revision: int


class MemoryPinRequest(BaseModel):
    """`memory.pin`: states the desired end state directly, so it is its
    own inverse and idempotent (06 §5.2) — no `expected_revision`."""

    id: str
    pinned: bool


class MemoryPinResponse(BaseModel):
    id: str
    revision: int
    pinned: bool


class MemoryArchiveRequest(BaseModel):
    id: str


class MemoryArchiveResponse(BaseModel):
    id: str
    revision: int
    status: str


class MemoryRestoreRequest(BaseModel):
    """`memory.restore`: `archived` → `active` (ADR-053 D1 — distinct from
    `memory.restore_from_snapshot`, the undelete)."""

    id: str


class MemoryRestoreResponse(BaseModel):
    id: str
    revision: int
    status: str


class MemoryDeleteRequest(BaseModel):
    """`memory.delete`: consequential (ADR-053 D4) — this request only
    ever produces a `confirmation_required` envelope; there is no success
    response shape for the gating call itself (mirrors `job.disable`'s own
    schema, `schemas/job.py`)."""

    id: str
    reason: str


class MemoryRestoreFromSnapshotRequest(BaseModel):
    """`memory.restore_from_snapshot`: the undelete (ADR-053 D5)."""

    id: str


class MemoryRestoreFromSnapshotResponse(BaseModel):
    id: str
    revision: int
    snapshot: str
