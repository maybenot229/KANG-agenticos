"""held_action.approve / .cancel / .list handlers.

Layer: api.
Constitutional home: 12_API §7, ADR-001 (crash semantics), ADR-002
(first_party_only channel control), ADR-021 (the transactional effect
driver — the first real instance of "approval drives an effect").
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Callable

from kang.api.dispatch import Handler, HandlerContext
from kang.api.errors import ApiError
from kang.api.registry import operation as registry_operation
from kang.domain.ports.clock import Clock
from kang.domain.ports.held_action import (
    HeldAction,
    HeldActionExpired,
    HeldActionNotFound,
    HeldActionStore,
)

__all__ = [
    "make_held_action_approve_handler",
    "make_held_action_cancel_handler",
    "make_held_action_expire_handler",
    "make_held_action_list_handler",
]

TransactionalEffect = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class _ApproveWiring:
    """What the transactional approve driver needs, bundled to keep
    `_approve_transactional` under the size lint's parameter hard limit
    (11 §4 — it sat at exactly 6 before ADR-025 added the decider, and
    `tools/lint_sizes.py` fails at 7). Same fix ADR-021's own amendment
    applied to `require_confirmation`/`_make_gate_handler`; the limit is
    never relaxed, the unit is split. Constructed once per handler, in
    the factory's closure — not rebuilt per request."""

    held_actions: HeldActionStore
    connection: sqlite3.Connection
    transactional_effects: dict[str, TransactionalEffect]
    clock: Clock


def make_held_action_approve_handler(
    held_actions: HeldActionStore,
    clock: Clock,
    connection: sqlite3.Connection,
    transactional_effects: dict[str, TransactionalEffect],
) -> Handler:
    """`held_action.approve` (ADR-001 Decision #5: itself idempotent —
    double-approval returns the cached outcome via API-004, already covered
    generically by the dispatcher's idempotency store, not repeated here;
    ADR-002: `first_party_only`, enforced by the dispatcher's channel check
    before this handler ever runs — a plugin session cannot reach this
    code path at all).

    For `transactional` commit_mode (ADR-021), drives the effect all the
    way to `executed` in one `BEGIN`/`COMMIT`: the approve-flip, the
    target operation's own effect (looked up in `transactional_effects`
    by the held action's `operation` name — the composition root's own
    table, same shape `JOB_OPERATIONS` already established), and
    `mark_executed`, sharing one transaction so a crash before commit is
    indistinguishable from still-`pending` (ADR-001 Amendment's own
    promise, finally made real). Any failure anywhere in that sequence
    rolls the whole thing back — the row never durably leaves `pending`.

    `redrive` commit_mode (or no operation registered — the pre-ADR-021,
    still-real gap) falls back to a plain `pending -> approved` flip only;
    driving a `redrive` effect remains open, ADR-021's own named
    out-of-scope (needs a proven adapter idempotency contract first,
    per ADR-001 Amendment).

    ADR-025: the approving principal is `context.principal` — read at
    call time, never threaded through this factory. That is deliberate:
    it keeps this signature stable (the ADR-021 crash-kill worker
    constructs this handler directly), and it is already the correct
    value, since the dispatcher derives it from the session and ADR-002's
    channel check has already refused any non-first-party approval."""

    wiring = _ApproveWiring(
        held_actions=held_actions,
        connection=connection,
        transactional_effects=transactional_effects,
        clock=clock,
    )

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        held_action_id = params.get("id")
        if not isinstance(held_action_id, str) or not held_action_id:
            raise ApiError("invalid_request", "held_action.approve requires an 'id'")
        try:
            current = held_actions.get(held_action_id)
        except HeldActionNotFound as exc:
            raise ApiError("not_found", str(exc)) from exc

        entry = registry_operation(current.operation)
        commit_mode = entry["commit_mode"] if entry else None
        if commit_mode == "transactional":
            return _approve_transactional(wiring, current, context.principal)
        return _approve_flip_only(
            held_actions, held_action_id, clock, context.principal
        )

    return handler


def _approve_flip_only(
    held_actions: HeldActionStore,
    held_action_id: str,
    clock: Clock,
    decided_by: str,
) -> dict[str, Any]:
    try:
        approved = held_actions.approve(
            held_action_id, clock.now().isoformat(), decided_by
        )
    except HeldActionExpired as exc:
        raise ApiError("conflict", f"held action {held_action_id} has expired") from exc
    except HeldActionNotFound as exc:
        # The store raises this both for a genuinely absent id and for
        # one not currently `pending` (its message names which) — the
        # real contract, not tightened into two distinct codes here.
        raise ApiError("not_found", str(exc)) from exc
    return {"id": approved.id, "status": approved.status}


def _approve_transactional(
    wiring: _ApproveWiring, current: HeldAction, decided_by: str
) -> dict[str, Any]:
    held_action_id = current.id
    effect = wiring.transactional_effects.get(current.operation)
    if effect is None:
        raise ApiError(
            "internal",
            f"{current.operation} declares commit_mode=transactional but has "
            "no registered effect (composition.py::TRANSACTIONAL_EFFECTS)",
        )
    connection = wiring.connection
    connection.execute("BEGIN IMMEDIATE")
    try:
        try:
            wiring.held_actions.approve_in_txn(
                held_action_id, wiring.clock.now().isoformat(), decided_by
            )
        except HeldActionExpired as exc:
            raise ApiError(
                "conflict", f"held action {held_action_id} has expired"
            ) from exc
        except HeldActionNotFound as exc:
            raise ApiError("not_found", str(exc)) from exc
        effect(current.params)
        # No provenance here, deliberately (ADR-025): approved → executed
        # is not a transition out of `pending`, so the approve-flip's own
        # decided_at/decided_by — written microseconds ago in this same
        # transaction — must survive it.
        executed = wiring.held_actions.mark_executed_in_txn(held_action_id)
        connection.execute("COMMIT")
    except Exception:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    return {"id": executed.id, "status": executed.status}


def make_held_action_cancel_handler(
    held_actions: HeldActionStore, clock: Clock
) -> Handler:
    """`held_action.cancel` (ADR-002: `first_party_only`, dispatcher-enforced
    before this handler runs). Transitions `pending -> cancelled` — Kang
    declining is final. Distinct from `expired` (ADR-024): the 24h expiry
    sweep (`HeldActionStore.expire_due`, wired as a scheduler job since
    ADR-022) finding no decision was made is a different event from Kang
    explicitly declining one, and writes a different terminal state.

    Takes a `clock` as of ADR-025 — declining is a decision, so it stamps
    `decided_at`/`decided_by` like every other transition out of
    `pending`. This handler had no clock before, because nothing recorded
    when the decline happened."""

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        held_action_id = params.get("id")
        if not isinstance(held_action_id, str) or not held_action_id:
            raise ApiError("invalid_request", "held_action.cancel requires an 'id'")
        try:
            cancelled = held_actions.cancel(
                held_action_id, clock.now().isoformat(), context.principal
            )
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


def make_held_action_expire_handler(
    held_actions: HeldActionStore, clock: Clock
) -> Handler:
    """`held_action.expire` (ADR-022): pure exposure of `HeldActionStore.
    expire_due()` — expires every `pending` held action past its 24h
    window (12_API §7), writing `expired` (ADR-024), not `cancelled` —
    distinct from Kang explicitly declining via `held_action.cancel`.
    Wired as `deadline.sweep`'s own shape (no request fields, a plain
    count in the response); unlike that operation, this one publishes no
    event — no `held_action.*` event type is registered anywhere, and
    inventing one with no named consumer would repeat the "enum allows
    it" anti-pattern ADR-021 already declined for `job.enable`/`.disable`.

    ADR-025: stamps `decided_by = context.principal` on every row it
    expires. No sentinel and no hardcoded name — the dispatcher derives
    the principal from the session, and the scheduler mints this job's
    session as `kernel:scheduler` (`scheduler_wiring.py`), so the right
    value arrives structurally. A manual invocation correctly records
    `kang` instead."""

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        count = held_actions.expire_due(clock.now().isoformat(), context.principal)
        return {"count": count}

    return handler
