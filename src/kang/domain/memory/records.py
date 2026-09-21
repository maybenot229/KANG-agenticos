"""Building records from proposals, and the payload shapes (ADR-051 D3/D7).

Layer: domain/memory (pure). `build_record` is the only constructor of an
`active` `MemoryRecord`; the API layer's single record-landing helper is its
only caller (a structural test pins both).
"""

from __future__ import annotations

from dataclasses import asdict, replace
from typing import Any

from kang.domain.memory.write_gate import Proposal
from kang.domain.ports.candidate_queue_store import Candidate
from kang.domain.ports.memory_store import MemoryRecord

__all__ = [
    "MEMORY_EVENT_FIELDS",
    "PROVENANCE_LINE_LIMIT",
    "build_record",
    "candidate_to_proposal",
    "memory_event_payload",
    "merged_record",
    "proposal_payload",
]

# 07 §5.1's columns, without the storage-local rowid (ADR-048 D2) — the full
# row a recovery-grade `memory.saved` carries (EB-003).
MEMORY_EVENT_FIELDS = (
    "id",
    "type",
    "status",
    "content",
    "trust_tier",
    "confidence",
    "sensitivity",
    "content_enc",
    "source_kind",
    "source_detail",
    "source_quote",
    "reason",
    "created_by",
    "created_at",
    "updated_at",
    "device_id",
    "revision",
    "importance",
    "pinned",
    "last_accessed",
    "access_count",
    "embedding_ver",
)

# A merge appends a proposer-supplied source reference to the incumbent's
# provenance (never content); bounded so it cannot balloon the row.
PROVENANCE_LINE_LIMIT = 500


def build_record(
    proposal: Proposal, record_id: str, created_by: str, now: str, device_id: str
) -> MemoryRecord:
    """A new `active` record at revision 1 from a *gate-passed* proposal.
    Private content is refused upstream, so `content_enc` is always None."""
    return MemoryRecord(
        id=record_id,
        type=proposal.type,
        status="active",
        content=proposal.content,
        trust_tier=proposal.trust_tier,
        confidence=proposal.confidence,
        sensitivity=proposal.sensitivity,
        source_kind=proposal.source_kind,
        source_detail=proposal.source_detail,
        source_quote=proposal.source_quote,
        reason=proposal.reason,
        created_by=created_by,
        created_at=now,
        updated_at=now,
        device_id=device_id,
        revision=1,
    )


def merged_record(
    incumbent: MemoryRecord, writer: str, proposal: Proposal, now: str, device_id: str
) -> MemoryRecord:
    """06 §4.2's silent merge: same content, so nothing but provenance moves
    — the writer's source reference is appended (once), the revision bumps."""
    line = f"{writer} {proposal.source_kind}:{proposal.source_detail}"
    line = line[:PROVENANCE_LINE_LIMIT]
    detail = incumbent.source_detail
    if line not in detail.split("\n"):
        detail = f"{detail}\n{line}"
    return replace(
        incumbent,
        source_detail=detail,
        revision=incumbent.revision + 1,
        updated_at=now,
        device_id=device_id,
    )


def memory_event_payload(record: MemoryRecord) -> dict[str, Any]:
    """The self-sufficient `memory.saved` payload (EB-003): every column."""
    row = asdict(record)
    return {name: row[name] for name in MEMORY_EVENT_FIELDS}


def proposal_payload(
    proposal: Proposal, created_by: str, device_id: str
) -> dict[str, Any]:
    """The queue row's JSON payload: the full proposal plus who proposed it."""
    return {**asdict(proposal), "created_by": created_by, "device_id": device_id}


def candidate_to_proposal(candidate: Candidate) -> tuple[Proposal, str, str]:
    """Inverse of `proposal_payload`: (proposal, created_by, device_id)."""
    payload = candidate.payload
    proposal = Proposal(
        type=payload["type"],
        content=payload["content"],
        trust_tier=payload["trust_tier"],
        source_kind=payload["source_kind"],
        source_detail=payload["source_detail"],
        reason=payload["reason"],
        confidence=payload["confidence"],
        sensitivity=payload["sensitivity"],
        source_quote=payload.get("source_quote"),
    )
    return proposal, payload["created_by"], payload["device_id"]
