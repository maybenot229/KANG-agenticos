"""Request/response schemas for held_action.* operations (ADR-010 Ruling 1).

Layer: api.
Constitutional home: 12_API §7 (held_action lifecycle), ADR-001 (crash
semantics; commit_mode as registry metadata), ADR-002 (first_party_only
channel control — enforced by the dispatcher, not expressed here).

Added 2026-08-05 alongside `operations.py::make_held_action_approve_handler`/
`make_held_action_cancel_handler` — the handlers were the confirmed-open
gap (registered in `kang.api.registry.OPERATIONS` since ADR-001/002, never
wired). Both operations take the same shape (an id in, the transitioned
row's id + status out), so one pair of classes each rather than four
near-duplicates would be tempting — kept separate anyway, matching every
other operation pair in this package (`TaskCreateRequest`/
`DeadlineCreateRequest` are shaped identically too): a shared base class
here would save a few lines today and cost a real seam the moment approve
and cancel's contracts diverge (approve already carries ADR-001's
`commit_mode`-adjacent semantics cancel does not).
"""

from __future__ import annotations

from pydantic import BaseModel

__all__ = [
    "HeldActionApproveRequest",
    "HeldActionApproveResponse",
    "HeldActionCancelRequest",
    "HeldActionCancelResponse",
]


class HeldActionApproveRequest(BaseModel):
    """`held_action.approve` params
    (operations.py::make_held_action_approve_handler)."""

    id: str


class HeldActionApproveResponse(BaseModel):
    """`held_action.approve` result — the row's id and its new status
    (always `approved` on success; failure paths raise instead)."""

    id: str
    status: str


class HeldActionCancelRequest(BaseModel):
    """`held_action.cancel` params
    (operations.py::make_held_action_cancel_handler)."""

    id: str


class HeldActionCancelResponse(BaseModel):
    """`held_action.cancel` result — the row's id and its new status
    (always `cancelled` on success; failure paths raise instead)."""

    id: str
    status: str
