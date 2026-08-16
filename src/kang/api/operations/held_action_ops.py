"""held_action.approve / .cancel / .list handlers.

Layer: api.
Constitutional home: 12_API §7, ADR-001 (crash semantics), ADR-002
(first_party_only channel control), ADR-021 (the transactional effect
driver — the first real instance of "approval drives an effect").
"""

from __future__ import annotations

import sqlite3
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
    per ADR-001 Amendment)."""

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
            return _approve_transactional(
                held_actions,
                connection,
                transactional_effects,
                held_action_id,
                current,
                clock,
            )
        return _approve_flip_only(held_actions, held_action_id, clock)

    return handler


def _approve_flip_only(
    held_actions: HeldActionStore, held_action_id: str, clock: Clock
) -> dict[str, Any]:
    try:
        approved = held_actions.approve(held_action_id, clock.now().isoformat())
    except HeldActionExpired as exc:
        raise ApiError("conflict", f"held action {held_action_id} has expired") from exc
    except HeldActionNotFound as exc:
        # The store raises this both for a genuinely absent id and for
        # one not currently `pending` (its message names which) — the
        # real contract, not tightened into two distinct codes here.
        raise ApiError("not_found", str(exc)) from exc
    return {"id": approved.id, "status": approved.status}


def _approve_transactional(
    held_actions: HeldActionStore,
    connection: sqlite3.Connection,
    transactional_effects: dict[str, TransactionalEffect],
    held_action_id: str,
    current: HeldAction,
    clock: Clock,
) -> dict[str, Any]:
    effect = transactional_effects.get(current.operation)
    if effect is None:
        raise ApiError(
            "internal",
            f"{current.operation} declares commit_mode=transactional but has "
            "no registered effect (composition.py::TRANSACTIONAL_EFFECTS)",
        )
    connection.execute("BEGIN IMMEDIATE")
    try:
        try:
            held_actions.approve_in_txn(held_action_id, clock.now().isoformat())
        except HeldActionExpired as exc:
            raise ApiError(
                "conflict", f"held action {held_action_id} has expired"
            ) from exc
        except HeldActionNotFound as exc:
            raise ApiError("not_found", str(exc)) from exc
        effect(current.params)
        executed = held_actions.mark_executed_in_txn(held_action_id)
        connection.execute("COMMIT")
    except Exception:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    return {"id": executed.id, "status": executed.status}


def make_held_action_cancel_handler(held_actions: HeldActionStore) -> Handler:
    """`held_action.cancel` (ADR-002: `first_party_only`, dispatcher-enforced
    before this handler runs). Transitions `pending -> cancelled` — Kang
    declining is final. Distinct from `expired` (ADR-024): the 24h expiry
    sweep (`HeldActionStore.expire_due`, wired as a scheduler job since
    ADR-022) finding no decision was made is a different event from Kang
    explicitly declining one, and writes a different terminal state."""

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
    it" anti-pattern ADR-021 already declined for `job.enable`/`.disable`."""

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        count = held_actions.expire_due(clock.now().isoformat())
        return {"count": count}

    return handler
