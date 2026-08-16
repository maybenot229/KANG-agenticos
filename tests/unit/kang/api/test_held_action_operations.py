"""held_action.approve / held_action.cancel — the confirmed-open gap this
session closes (session-handoff-2026-08-05.md).

The claim under test: the two handlers correctly drive the ALREADY-BUILT
`HeldActionStore` port through its `pending -> approved | cancelled`
transitions (ADR-001 Decision #2), map its typed failures to the right
API-006 error codes, and enforce nothing beyond what the store itself
enforces (the dispatcher's first_party_only channel check and the
permission engine are out of this handler's scope entirely — ADR-002).

Deliberately NOT under test here: driving an approved action to
`executed` for `commit_mode="transactional"` (ADR-021) — every held
action this file seeds names an unregistered operation, so the handler's
flip-only fallback is what's exercised. The transactional effect-driving
path (BEGIN/approve_in_txn/effect/mark_executed_in_txn/COMMIT, sharing
one real transaction) needs a real connection to mean anything and is
proven in
`tests/integration/sqlite/test_held_action_transactional_effect.py`
instead.
"""

from __future__ import annotations

import itertools

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.fakes.held_action_store import FakeHeldActionStore
from kang.api.dispatch import HandlerContext
from kang.api.errors import ApiError
from kang.api.operations import (
    make_held_action_approve_handler,
    make_held_action_cancel_handler,
    make_held_action_expire_handler,
    make_held_action_list_handler,
)
from kang.domain.ports.held_action import HeldAction

CONTEXT = HandlerContext(
    principal="kang", correlation_id="corr-1", trigger="cli", first_party=True
)


@pytest.fixture
def wiring():
    clock = FakeClock()
    ids = (f"ha-{n:04d}" for n in itertools.count())
    store = FakeHeldActionStore()
    return {"clock": clock, "store": store, "new_id": lambda: next(ids)}


def _seed_pending(wiring, *, expires_in_hours: float = 24, **overrides) -> HeldAction:
    from datetime import timedelta

    created = wiring["clock"].now()
    action = HeldAction(
        id=overrides.pop("id", wiring["new_id"]()),
        operation=overrides.pop("operation", "memory.delete"),
        action=overrides.pop("action", "delete memory record mem-1"),
        principal=overrides.pop("principal", "kang"),
        reason=overrides.pop("reason", "duplicate of mem-2"),
        reversibility=overrides.pop("reversibility", "30-day recovery window"),
        correlation_id=overrides.pop("correlation_id", "corr-origin"),
        created_at=created.isoformat(),
        expires_at=(created + timedelta(hours=expires_in_hours)).isoformat(),
        **overrides,
    )
    wiring["store"].create(action)
    return action


def _approve(wiring, held_action_id: str) -> dict:
    # `connection`/`transactional_effects` are only touched by the
    # commit_mode="transactional" branch (ADR-021) — every held action
    # this file seeds names an operation with no registry entry
    # (`memory.delete` isn't registered yet), so `commit_mode` resolves to
    # None and the flip-only fallback runs, never touching either. The
    # transactional path is proven by
    # tests/integration/sqlite/test_held_action_transactional_effect.py
    # against a real connection instead.
    handler = make_held_action_approve_handler(
        wiring["store"], wiring["clock"], connection=None, transactional_effects={}
    )
    return handler(CONTEXT, {"id": held_action_id})


def _cancel(wiring, held_action_id: str) -> dict:
    handler = make_held_action_cancel_handler(wiring["store"])
    return handler(CONTEXT, {"id": held_action_id})


def _list(wiring) -> dict:
    handler = make_held_action_list_handler(wiring["store"])
    return handler(CONTEXT, {})


class TestApprove:
    def test_approves_a_pending_action(self, wiring):
        seeded = _seed_pending(wiring)
        result = _approve(wiring, seeded.id)
        assert result == {"id": seeded.id, "status": "approved"}
        assert wiring["store"].get(seeded.id).status == "approved"

    def test_missing_id_is_invalid_request(self, wiring):
        handler = make_held_action_approve_handler(
            wiring["store"], wiring["clock"], connection=None, transactional_effects={}
        )
        with pytest.raises(ApiError) as exc:
            handler(CONTEXT, {})
        assert exc.value.code == "invalid_request"

    def test_unknown_id_is_not_found(self, wiring):
        with pytest.raises(ApiError) as exc:
            _approve(wiring, "no-such-id")
        assert exc.value.code == "not_found"

    def test_already_approved_cannot_be_approved_again(self, wiring):
        seeded = _seed_pending(wiring)
        _approve(wiring, seeded.id)
        with pytest.raises(ApiError) as exc:
            _approve(wiring, seeded.id)
        assert exc.value.code == "not_found"

    def test_expired_action_refuses_approval_as_conflict(self, wiring):
        seeded = _seed_pending(wiring, expires_in_hours=1)
        wiring["clock"].advance(2 * 3600)  # past the 24h-style window
        with pytest.raises(ApiError) as exc:
            _approve(wiring, seeded.id)
        assert exc.value.code == "conflict"
        # The store's own guard, not this handler's — still pending, since
        # expiry-on-approve-attempt does not itself transition the row
        # (that's expire_due()'s sweep, a separate, not-yet-wired job).
        assert wiring["store"].get(seeded.id).status == "pending"


class TestCancel:
    def test_cancels_a_pending_action(self, wiring):
        seeded = _seed_pending(wiring)
        result = _cancel(wiring, seeded.id)
        assert result == {"id": seeded.id, "status": "cancelled"}
        assert wiring["store"].get(seeded.id).status == "cancelled"

    def test_missing_id_is_invalid_request(self, wiring):
        handler = make_held_action_cancel_handler(wiring["store"])
        with pytest.raises(ApiError) as exc:
            handler(CONTEXT, {})
        assert exc.value.code == "invalid_request"

    def test_unknown_id_is_not_found(self, wiring):
        with pytest.raises(ApiError) as exc:
            _cancel(wiring, "no-such-id")
        assert exc.value.code == "not_found"

    def test_an_approved_action_cannot_be_cancelled(self, wiring):
        # Approve is final in one direction, cancel in the other — no
        # crossing back once a status has moved (ADR-001 Decision #2's
        # pending -> approved | cancelled, never approved -> cancelled).
        seeded = _seed_pending(wiring)
        _approve(wiring, seeded.id)
        with pytest.raises(ApiError) as exc:
            _cancel(wiring, seeded.id)
        assert exc.value.code == "not_found"

    def test_an_already_cancelled_action_cannot_be_cancelled_again(self, wiring):
        seeded = _seed_pending(wiring)
        _cancel(wiring, seeded.id)
        with pytest.raises(ApiError) as exc:
            _cancel(wiring, seeded.id)
        assert exc.value.code == "not_found"


class TestExpire:
    """`held_action.expire` (ADR-022) — pure exposure of `HeldActionStore.
    expire_due()`, wired as a job for the first time this session. Writes
    `expired`, not `cancelled` (ADR-024) — distinct from Kang explicitly
    declining via `held_action.cancel`."""

    def test_expires_only_past_pending_actions(self, wiring):
        # Expires within the hour, still-fresh, and already-approved all
        # coexist — only the first should move.
        past_due = _seed_pending(wiring, id="ha-0000", expires_in_hours=1)
        still_fresh = _seed_pending(wiring, id="ha-0001", expires_in_hours=48)
        wiring["clock"].advance(2 * 3600)  # past ha-0000's window, not ha-0001's

        handler = make_held_action_expire_handler(wiring["store"], wiring["clock"])
        result = handler(CONTEXT, {})

        assert result == {"count": 1}
        assert wiring["store"].get(past_due.id).status == "expired"
        assert wiring["store"].get(still_fresh.id).status == "pending"

    def test_nothing_to_expire_returns_zero(self, wiring):
        _seed_pending(wiring, expires_in_hours=48)
        handler = make_held_action_expire_handler(wiring["store"], wiring["clock"])
        assert handler(CONTEXT, {}) == {"count": 0}

    def test_running_twice_is_idempotent(self, wiring):
        _seed_pending(wiring, expires_in_hours=1)
        wiring["clock"].advance(2 * 3600)
        handler = make_held_action_expire_handler(wiring["store"], wiring["clock"])
        assert handler(CONTEXT, {}) == {"count": 1}
        assert handler(CONTEXT, {}) == {"count": 0}  # already expired, not re-swept


class TestList:
    """`held_action.list`, added 2026-08-05 for the dashboard's Zone 2
    approval queue and the confirm dialog (09_UI §4/§7). The claim: it
    exposes `HeldActionStore.pending()`'s existing contract verbatim —
    pending-only, oldest first — and every field the confirm dialog
    needs (what/who/why/reversibility)."""

    def test_empty_store_lists_nothing(self, wiring):
        assert _list(wiring) == {"held_actions": []}

    def test_lists_a_pending_action_with_every_dialog_field(self, wiring):
        seeded = _seed_pending(wiring)
        (item,) = _list(wiring)["held_actions"]
        assert item == {
            "id": seeded.id,
            "operation": seeded.operation,
            "action": seeded.action,
            "principal": seeded.principal,
            "reason": seeded.reason,
            "reversibility": seeded.reversibility,
            "correlation_id": seeded.correlation_id,
            "created_at": seeded.created_at,
            "expires_at": seeded.expires_at,
            "status": "pending",
        }

    def test_approved_actions_drop_off_the_pending_list(self, wiring):
        seeded = _seed_pending(wiring)
        _approve(wiring, seeded.id)
        assert _list(wiring) == {"held_actions": []}

    def test_cancelled_actions_drop_off_the_pending_list(self, wiring):
        seeded = _seed_pending(wiring)
        _cancel(wiring, seeded.id)
        assert _list(wiring) == {"held_actions": []}

    def test_oldest_first(self, wiring):
        first = _seed_pending(wiring, id="ha-a", action="first")
        wiring["clock"].advance(3600)
        _seed_pending(wiring, id="ha-b", action="second")
        ids = [a["id"] for a in _list(wiring)["held_actions"]]
        assert ids[0] == first.id
