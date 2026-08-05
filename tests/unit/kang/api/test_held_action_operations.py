"""held_action.approve / held_action.cancel — the confirmed-open gap this
session closes (session-handoff-2026-08-05.md).

The claim under test: the two handlers correctly drive the ALREADY-BUILT
`HeldActionStore` port through its `pending -> approved | cancelled`
transitions (ADR-001 Decision #2), map its typed failures to the right
API-006 error codes, and enforce nothing beyond what the store itself
enforces (the dispatcher's first_party_only channel check and the
permission engine are out of this handler's scope entirely — ADR-002).

Deliberately NOT under test here: driving an approved action to
`executed`. No live operation is on 05_AGENTS Appendix D's closed list
today, so nothing produces a held action outside a test fixture, and the
row has no stored params to replay against (see
`operations.py::make_held_action_approve_handler`'s own docstring) — a
real, named gap, not a silent one.
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
    handler = make_held_action_approve_handler(wiring["store"], wiring["clock"])
    return handler(CONTEXT, {"id": held_action_id})


def _cancel(wiring, held_action_id: str) -> dict:
    handler = make_held_action_cancel_handler(wiring["store"])
    return handler(CONTEXT, {"id": held_action_id})


class TestApprove:
    def test_approves_a_pending_action(self, wiring):
        seeded = _seed_pending(wiring)
        result = _approve(wiring, seeded.id)
        assert result == {"id": seeded.id, "status": "approved"}
        assert wiring["store"].get(seeded.id).status == "approved"

    def test_missing_id_is_invalid_request(self, wiring):
        handler = make_held_action_approve_handler(wiring["store"], wiring["clock"])
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
