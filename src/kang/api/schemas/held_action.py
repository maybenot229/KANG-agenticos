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
    "HeldActionExpireRequest",
    "HeldActionExpireResponse",
    "HeldActionListItem",
    "HeldActionListRequest",
    "HeldActionListResponse",
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


class HeldActionListRequest(BaseModel):
    """`held_action.list` params
    (operations.py::make_held_action_list_handler). No fields: the
    handler takes none, mirroring `DeadlineSweepRequest`."""


class HeldActionListItem(BaseModel):
    """One pending held action — exactly the 09_UI §7 confirm-dialog
    fields (what/who/why/reversibility), plus the identifiers the dialog
    and the approve/cancel calls need. Not the full `deadline_event_
    payload`-style replay shape; `HeldAction`'s own fields already are
    the dialog contents (12_API §7), so this mirrors the dataclass
    directly rather than hand-picking a subset."""

    id: str
    operation: str
    action: str
    principal: str
    reason: str
    reversibility: str
    correlation_id: str
    created_at: str
    expires_at: str
    status: str


class HeldActionListResponse(BaseModel):
    """`held_action.list` result: every `pending` held action, oldest
    first — `HeldActionStore.pending()`'s existing contract
    (`domain/ports/held_action.py`), exposed through the API for the
    first time. Added 2026-08-05 for the dashboard's Zone 2 (09_UI §4:
    "approval queue count"; §7: "Held actions... appear in Zone 2 with
    age; they expire visibly, never silently") and the confirm dialog
    that reads one entry to render. No new domain logic — `pending()`
    already existed."""

    held_actions: list[HeldActionListItem]


class HeldActionExpireRequest(BaseModel):
    """`held_action.expire` params (operations.py::make_held_action_expire_
    handler). No fields — mirrors `DeadlineSweepRequest`'s exact shape."""


class HeldActionExpireResponse(BaseModel):
    """`held_action.expire` result — `HeldActionStore.expire_due()`'s own
    return value (a count, not the expired ids; ADR-022 exposes the
    existing store contract verbatim rather than expanding it)."""

    count: int
