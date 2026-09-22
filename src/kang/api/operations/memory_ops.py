"""memory.propose / .approve / .edit_approve / .reject, candidate.list /
.expire handlers — the write gate's API surface (ADR-051 D2-D4, D7, D9;
ADR-052 D1-D3).

Layer: api. Handlers orchestrate: authorize, build the proposal, call the pure
gate (`domain/memory/write_gate.py`), act on its decision. No admission
policy lives here.
Constitutional home: 06_MEMORY Part IV, **M-003** (AI proposals never
auto-commit), 12_API §10 ("the API physically has no operation that writes an
active memory except `memory.approve` of an existing candidate by a
first-party session, or Kang-principal explicit saves which auto-pass the
gate"), 15_EVENT_BUS EB-004, ADR-051.

THE ONE DOOR. `_land_record` is the only function in `src/` that hands a new
record to `MemoryStore.insert_record`. Kang's auto-pass and `memory.approve`
both call it — a structural test pins that, so a second insert path cannot be
added by accident. The record row commits only inside `bus.publish` (EB-004,
07 DB-001's event-before-commit pairing), exactly as `deadline.create` does.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Any

from kang.api.dispatch import Handler, HandlerContext
from kang.api.errors import ApiError
from kang.api.schemas.memory import DEFAULT_LIMIT, MAX_LIMIT
from kang.domain.memory import (
    GateDecision,
    GateProbes,
    Proposal,
    Writer,
    authorize_resolution,
    build_record,
    candidate_to_proposal,
    decide,
    memory_event_payload,
    merged_record,
    proposal_payload,
    validate_proposal,
)
from kang.domain.ports.candidate_queue_store import Candidate, CandidateQueueStore
from kang.domain.ports.clock import Clock
from kang.domain.ports.eventlog import EventEnvelope
from kang.domain.ports.memory_config import MemoryConfig
from kang.domain.ports.memory_store import (
    MEMORY_TYPES,
    MemoryRecord,
    MemoryStore,
    content_fingerprint,
)
from kang.domain.ports.unit_of_work import UnitOfWork
from kang.kernel.audit.service import AuditService
from kang.kernel.bus.bus import EventBus
from kang.kernel.permissions.engine import PermissionDenied, PermissionEngine

__all__ = [
    "MEMORY_PRINCIPAL",
    "MemoryOpsDeps",
    "make_candidate_list_handler",
    "make_memory_handlers",
]

MEMORY_PRINCIPAL = "kernel:memory"  # owns memory truth (EB-010)

# Gate codes that are a caller's authority problem vs. a malformed request.
_AUTHORITY_CODES = (
    "writer_refused",
    "type_restricted",
    "approval_restricted",
    "tier_restricted",  # ADR-052 D2
)


@dataclass(frozen=True)
class MemoryOpsDeps:
    """Everything the memory handlers are built from (11 §4). `config` is
    None when `memory.toml` is absent or malformed: the record-creating
    operations then refuse (ADR-051 D8, fail-closed) — they never fall back
    to a built-in expiry window."""

    bus: EventBus
    memory: MemoryStore
    queue: CandidateQueueStore
    unit_of_work: UnitOfWork
    permissions: PermissionEngine
    audit: AuditService
    clock: Clock
    new_id: Callable[[], str]
    device_id: str
    config: MemoryConfig | None


def _writer(context: HandlerContext) -> Writer:
    return Writer(context.principal, context.first_party)


def _require_config(deps: MemoryOpsDeps) -> MemoryConfig:
    if deps.config is None:
        raise ApiError(
            "internal",
            "the memory gate is unavailable: memory.toml is absent or invalid "
            "(ADR-051 D8 — it fails closed and never defaults)",
        )
    return deps.config


def _audit(
    deps: MemoryOpsDeps, context: HandlerContext, action: str, **details: Any
) -> None:
    """Audited: every gate decision, rejections included (06 §12.3). Never the
    content — ids, type, outcome and code only (payloads contain lives)."""
    deps.audit.record(
        context.principal, action, details, correlation_id=context.correlation_id
    )


def _refuse(deps: MemoryOpsDeps, context: HandlerContext, decision: GateDecision):
    _audit(deps, context, "memory.gate.rejected", code=decision.code)
    if decision.code == "duplicate":
        # ADR-052 D1: an existing-resource conflict, not an authority
        # problem — reuses the existing `conflict` code (CLAUDE.md §4: no
        # new error code without an ADR); its message names neither the
        # incumbent's id nor its content.
        api_code = "conflict"
    elif decision.code in _AUTHORITY_CODES:
        api_code = "permission_denied"
    else:
        api_code = "invalid_request"
    raise ApiError(api_code, decision.reason, details={"code": decision.code})


def _saved_envelope(
    deps: MemoryOpsDeps, context: HandlerContext, record: MemoryRecord, provenance: str
) -> EventEnvelope:
    return EventEnvelope(
        event_id=deps.new_id(),
        type="memory.saved",
        occurred_at=record.updated_at,
        principal=MEMORY_PRINCIPAL,
        correlation_id=context.correlation_id,
        device_id=deps.device_id,
        payload=memory_event_payload(record),
        provenance=provenance,
        recovery_grade=True,
        entity_refs=({"kind": "memory", "id": record.id},),
    )


def _land_record(
    deps: MemoryOpsDeps,
    context: HandlerContext,
    record: MemoryRecord,
    also: Callable[[], None] | None = None,
) -> None:
    """THE ONE DOOR to a new `memory_record` row (see the module docstring).
    The insert — and, for an approval, the queue row's resolution — commit
    together inside `bus.publish`'s `commit_state` (EB-004)."""

    def commit() -> None:
        deps.unit_of_work.run(lambda: _insert_and(deps.memory, record, also))

    deps.bus.publish(
        _saved_envelope(deps, context, record, "kang"), commit_state=commit
    )


def _insert_and(
    memory: MemoryStore, record: MemoryRecord, also: Callable[[], None] | None
) -> None:
    memory.insert_record(record)
    if also is not None:
        also()


def _proposal_from_params(params: dict[str, Any]) -> Proposal:
    return Proposal(
        type=params["type"],
        content=params["content"],
        trust_tier=params["trust_tier"],
        source_kind=params["source_kind"],
        source_detail=params["source_detail"],
        reason=params["reason"],
        confidence=params.get("confidence", 1.0),
        sensitivity=params.get("sensitivity", "normal"),
        source_quote=params.get("source_quote"),
    )


def _check_type_scope(
    deps: MemoryOpsDeps, context: HandlerContext, memory_type: str
) -> None:
    """ADR-051 D2's second engine check: the dispatcher already required the
    coarse `memory.propose`; this asks the same engine about the type. (A
    grant of `memory.propose:lesson` does not cover the bare scope and vice
    versa — `Scope.covers` — which is why both grants exist.)"""
    if memory_type not in MEMORY_TYPES:
        return  # the gate rejects it as invalid; nothing to authorize
    scope = f"memory.propose:{memory_type}"
    try:
        deps.permissions.check(context.principal, scope)
    except PermissionDenied as denied:
        _audit(deps, context, "memory.gate.rejected", code="scope_denied", scope=scope)
        raise ApiError(
            "permission_denied", f"missing scope {scope}", details={"scope": scope}
        ) from denied


def _propose(
    deps: MemoryOpsDeps, context: HandlerContext, params: dict[str, Any]
) -> dict[str, Any]:
    config = _require_config(deps)
    proposal = _proposal_from_params(params)
    _check_type_scope(deps, context, proposal.type)
    duplicate = None
    if validate_proposal(proposal) is None:
        duplicate = deps.memory.find_active_duplicate(
            proposal.type, content_fingerprint(proposal.content)
        )
    decision = decide(proposal, _writer(context), GateProbes(duplicate))
    now = deps.clock.now()
    if decision.outcome == "reject":
        _refuse(deps, context, decision)
    if decision.outcome == "admit":
        record = build_record(
            proposal, deps.new_id(), context.principal, now.isoformat(), deps.device_id
        )
        _land_record(deps, context, record)
        _audit(deps, context, "memory.gate.admitted", id=record.id, type=record.type)
        return {"outcome": "admitted", "id": record.id, "revision": 1}
    if decision.outcome == "merge":
        return _merge(deps, context, proposal, decision, now.isoformat())
    expires = (now + timedelta(days=config.candidate_expiry_days)).isoformat()
    candidate = Candidate(
        id=deps.new_id(),
        payload=proposal_payload(proposal, context.principal, deps.device_id),
        proposed_at=now.isoformat(),
        expires_at=expires,
    )
    deps.queue.enqueue(candidate)
    _audit(deps, context, "memory.gate.queued", id=candidate.id, type=proposal.type)
    return {"outcome": "queued", "id": candidate.id, "expires_at": expires}


def _merge(
    deps: MemoryOpsDeps,
    context: HandlerContext,
    proposal: Proposal,
    decision: GateDecision,
    now: str,
) -> dict[str, Any]:
    """06 §4.2's silent merge: provenance appended, revision bumped, audited.
    Content never changes — an exact-hash duplicate by definition."""
    incumbent = deps.memory.get(decision.merge_into or "")
    if incumbent is None:
        raise ApiError("conflict", "the duplicate record vanished before the merge")
    merged = merged_record(incumbent, context.principal, proposal, now, deps.device_id)
    deps.bus.publish(
        _saved_envelope(deps, context, merged, "derived"),
        commit_state=lambda: deps.memory.merge_provenance(merged, incumbent.revision),
    )
    _audit(deps, context, "memory.gate.merged", id=merged.id, revision=merged.revision)
    return {"outcome": "merged", "id": merged.id, "revision": merged.revision}


def _pending_candidate(
    deps: MemoryOpsDeps, context: HandlerContext, candidate_id: str
) -> Candidate:
    refusal = authorize_resolution(_writer(context))
    if refusal is not None:
        _refuse(deps, context, refusal)
    candidate = deps.queue.get(candidate_id)
    if candidate is None:
        raise ApiError("not_found", f"no such candidate {candidate_id!r}")
    if not candidate.pending:
        raise ApiError("conflict", f"candidate {candidate_id} is already resolved")
    return candidate


def _promote(
    deps: MemoryOpsDeps,
    context: HandlerContext,
    candidate: Candidate,
    edited_content: str | None,
    trust_tier: int | None = None,
) -> dict[str, Any]:
    """`memory.approve` / `.edit_approve`: the queue row's id becomes the
    record's id (ADR-048 D1). The stored proposal (with any edited content,
    but NOT yet Kang's `trust_tier` override) is re-run through the gate as
    its own proposer — so a candidate that could never have been queued
    cannot be approved either. `trust_tier`, when given, is applied only
    AFTER that recheck: it is this first-party Kang action's own explicit
    override (ADR-052 D3, 06 §1.4's "confirmed so"), not a re-assertion of
    the original writer's claim — re-running it as the proposer would wrongly
    trip D2's `tier_restricted` refusal on Kang's own promotion."""
    _require_config(deps)
    proposal, proposer, _device = candidate_to_proposal(candidate)
    if edited_content is not None:
        proposal = replace(proposal, content=edited_content)
    recheck = decide(proposal, Writer(proposer, False), GateProbes())
    if recheck.outcome != "queue":
        _refuse(deps, context, recheck)
    if trust_tier is not None:
        proposal = replace(proposal, trust_tier=trust_tier)
    resolution = "edited" if edited_content is not None else "approved"
    now = deps.clock.now().isoformat()
    record = build_record(proposal, candidate.id, proposer, now, deps.device_id)

    def resolve() -> None:
        if not deps.queue.resolve(candidate.id, resolution, now):
            raise RuntimeError(f"candidate {candidate.id} was resolved concurrently")

    _land_record(deps, context, record, also=resolve)
    _audit(deps, context, "memory.gate.approved", id=record.id, resolution=resolution)
    return {"id": record.id, "revision": record.revision}


def _reject(
    deps: MemoryOpsDeps, context: HandlerContext, candidate: Candidate
) -> dict[str, Any]:
    now = deps.clock.now().isoformat()
    deps.queue.resolve(candidate.id, "rejected", now)
    _audit(deps, context, "memory.gate.candidate_rejected", id=candidate.id)
    return {"id": candidate.id, "resolved": "rejected"}


def _expire(deps: MemoryOpsDeps, context: HandlerContext) -> dict[str, Any]:
    expired = deps.queue.expire_due(deps.clock.now().isoformat())
    if expired:
        _audit(deps, context, "memory.gate.expired", ids=list(expired))
    return {"expired": list(expired), "count": len(expired)}


def make_memory_handlers(deps: MemoryOpsDeps) -> dict[str, Handler]:
    """The five command handlers, keyed by operation name."""

    def propose(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        return _propose(deps, context, params)

    def approve(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        return _promote(
            deps,
            context,
            _pending_candidate(deps, context, params["candidate_id"]),
            None,
        )

    def edit_approve(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        candidate = _pending_candidate(deps, context, params["candidate_id"])
        return _promote(
            deps, context, candidate, params["content"], params.get("trust_tier")
        )

    def reject(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        candidate = _pending_candidate(deps, context, params["candidate_id"])
        return _reject(deps, context, candidate)

    def expire(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        return _expire(deps, context)

    return {
        "memory.propose": propose,
        "memory.approve": approve,
        "memory.edit_approve": edit_approve,
        "memory.reject": reject,
        "candidate.expire": expire,
    }


def make_candidate_list_handler(queue: CandidateQueueStore) -> Handler:
    """`candidate.list`: the approval queue — pending first, oldest first.
    `first_party_only` at the registry: content is shown to Kang alone."""

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        requested = params.get("limit")
        limit = (
            DEFAULT_LIMIT if requested is None else max(1, min(requested, MAX_LIMIT))
        )
        return {
            "candidates": [
                {
                    "id": c.id,
                    "type": c.payload["type"],
                    "content": c.payload["content"],
                    "trust_tier": c.payload["trust_tier"],
                    "source_kind": c.payload["source_kind"],
                    "source_detail": c.payload["source_detail"],
                    "reason": c.payload["reason"],
                    "confidence": c.payload["confidence"],
                    "sensitivity": c.payload["sensitivity"],
                    "created_by": c.payload["created_by"],
                    "proposed_at": c.proposed_at,
                    "expires_at": c.expires_at,
                    "resolved": c.resolved,
                    "resolved_at": c.resolved_at,
                    "flags": list(c.flags),
                }
                for c in queue.list_queue(limit)
            ]
        }

    return handler
