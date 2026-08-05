"""held_action.approve / .cancel / .list handlers.

Layer: api.
Constitutional home: 12_API §7, ADR-001 (crash semantics), ADR-002
(first_party_only channel control).
"""

from __future__ import annotations

from typing import Any

from kang.api.dispatch import Handler, HandlerContext
from kang.api.errors import ApiError
from kang.domain.ports.clock import Clock
from kang.domain.ports.held_action import (
    HeldActionExpired,
    HeldActionNotFound,
    HeldActionStore,
)

__all__ = [
    "make_held_action_approve_handler",
    "make_held_action_cancel_handler",
    "make_held_action_list_handler",
]


def make_held_action_approve_handler(
    held_actions: HeldActionStore, clock: Clock
) -> Handler:
    """`held_action.approve` (ADR-001 Decision #5: itself idempotent —
    double-approval returns the cached outcome via API-004, already covered
    generically by the dispatcher's idempotency store, not repeated here;
    ADR-002: `first_party_only`, enforced by the dispatcher's channel check
    before this handler ever runs — a plugin session cannot reach this
    code path at all).

    Transitions `pending -> approved` only. Driving the approved effect to
    `executed` (ADR-001 Decision #3) needs the held operation's original
    params to replay it — `held_action`'s schema carries `operation` (the
    registry name) and `action` (a free-text description), never the
    params themselves (`migrations/0005_held_action_lifecycle.sql`,
    `domain/ports/held_action.py`). That's a real, named gap — ADR-001's
    own Consequences section calls the schema delta "owed... applied by
    the follow-through PR", not something to invent here. It is also
    moot today: no operation currently registered is on 05_AGENTS
    Appendix D's closed list, so nothing live produces a held action to
    drive in the first place. This handler serves the transition that IS
    buildable now; `approved_not_executed()`'s redrive sweep and the
    effect-driving half remain open, not silently completed.
    """

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        held_action_id = params.get("id")
        if not isinstance(held_action_id, str) or not held_action_id:
            raise ApiError("invalid_request", "held_action.approve requires an 'id'")
        try:
            approved = held_actions.approve(held_action_id, clock.now().isoformat())
        except HeldActionExpired as exc:
            raise ApiError(
                "conflict", f"held action {held_action_id} has expired"
            ) from exc
        except HeldActionNotFound as exc:
            # The store raises this both for a genuinely absent id and for
            # one not currently `pending` (its message names which) — the
            # real contract, not tightened into two distinct codes here.
            raise ApiError("not_found", str(exc)) from exc
        return {"id": approved.id, "status": approved.status}

    return handler


def make_held_action_cancel_handler(held_actions: HeldActionStore) -> Handler:
    """`held_action.cancel` (ADR-002: `first_party_only`, dispatcher-enforced
    before this handler runs). Transitions `pending -> cancelled` — Kang
    declining is final, the same terminal state the 24h expiry sweep
    (`HeldActionStore.expire_due`, not wired to a job yet) would also
    produce."""

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        held_action_id = params.get("id")
        if not isinstance(held_action_id, str) or not held_action_id:
            raise ApiError("invalid_request", "held_action.cancel requires an 'id'")
        try:
            cancelled = held_actions.cancel(held_action_id)
        except HeldActionNotFound as exc:
            raise ApiError("not_found", str(exc)) from exc
        return {"id": cancelled.id, "status": cancelled.status}

    return handler


def make_held_action_list_handler(held_actions: HeldActionStore) -> Handler:
    """`held_action.list` (added 2026-08-05, dashboard Zone 2's approval
    queue + the confirm dialog, 09_UI §4/§7): every `pending` held action,
    oldest first — `HeldActionStore.pending()`'s existing contract,
    exposed through the API for the first time. Mirrors the dataclass
    directly (id/operation/action/principal/reason/reversibility/
    correlation_id/created_at/expires_at/status): unlike `deadline.list`,
    there is no separate "full replay payload" to distinguish from here —
    `HeldAction`'s fields already are exactly 12_API §7's dialog
    contents, nothing more to trim."""

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "held_actions": [
                {
                    "id": a.id,
                    "operation": a.operation,
                    "action": a.action,
                    "principal": a.principal,
                    "reason": a.reason,
                    "reversibility": a.reversibility,
                    "correlation_id": a.correlation_id,
                    "created_at": a.created_at,
                    "expires_at": a.expires_at,
                    "status": a.status,
                }
                for a in held_actions.pending()
            ]
        }

    return handler
