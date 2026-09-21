"""Request/response schemas for `memory.*` and `candidate.*` operations
(ADR-051 D3; ADR-010 Ruling 1).

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
    "MemoryEditApproveRequest",
    "MemoryProposeRequest",
    "MemoryProposeResponse",
    "MemoryRejectRequest",
    "MemoryRejectResponse",
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
    revision (revision 1 is what lands)."""

    candidate_id: str
    content: str


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
