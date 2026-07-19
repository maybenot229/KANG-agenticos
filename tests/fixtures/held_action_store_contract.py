"""HeldActionStore port-contract suite — fake and sqlite (13 §2.3).
Subclasses provide ``store``. Times are ISO strings (the store compares
them lexically, which is correct for ISO-8601 — the injected clock's shape).
"""

from __future__ import annotations

import pytest

from kang.domain.ports.held_action import (
    HeldAction,
    HeldActionExpired,
    HeldActionNotFound,
)

CREATED = "2026-01-01T09:00:00+00:00"
EXPIRES = "2026-01-02T09:00:00+00:00"  # +24h (12 §7)


def _held(index: int = 0, created: str = CREATED, expires: str = EXPIRES) -> HeldAction:
    return HeldAction(
        id=f"held-{index:04d}",
        operation="task.delete",
        action=f"task.delete task-{index:04d}",
        principal="agent:planner",
        reason="the plan no longer needs it",
        reversibility="reversible for 30 days via restore-from-snapshot",
        correlation_id=f"corr-{index:04d}",
        created_at=created,
        expires_at=expires,
    )


class HeldActionStoreContract:
    def test_create_then_get_roundtrips(self, store):
        held = _held(0)
        store.create(held)
        assert store.get(held.id) == held

    def test_new_held_action_is_pending(self, store):
        store.create(_held(0))
        assert store.get("held-0000").status == "pending"

    def test_get_unknown_raises(self, store):
        with pytest.raises(HeldActionNotFound):
            store.get("held-none")

    def test_approve_within_window(self, store):
        store.create(_held(0))
        approved = store.approve("held-0000", now="2026-01-01T12:00:00+00:00")
        assert approved.status == "approved"
        assert store.get("held-0000").status == "approved"

    def test_approve_past_expiry_is_refused(self, store):
        store.create(_held(0))
        with pytest.raises(HeldActionExpired):
            store.approve("held-0000", now="2026-01-03T09:00:00+00:00")
        assert store.get("held-0000").status == "pending"  # unchanged

    def test_cancel_transitions_to_cancelled(self, store):
        store.create(_held(0))
        assert store.cancel("held-0000").status == "cancelled"

    def test_cannot_approve_a_cancelled_action(self, store):
        store.create(_held(0))
        store.cancel("held-0000")
        with pytest.raises(HeldActionNotFound):
            store.approve("held-0000", now="2026-01-01T12:00:00+00:00")

    def test_mark_executed_after_approve(self, store):
        store.create(_held(0))
        store.approve("held-0000", now="2026-01-01T12:00:00+00:00")
        executed = store.mark_executed("held-0000")
        assert executed.status == "executed"
        assert store.get("held-0000").status == "executed"

    def test_cannot_mark_executed_before_approval(self, store):
        store.create(_held(0))
        with pytest.raises(HeldActionNotFound):
            store.mark_executed("held-0000")

    def test_cannot_mark_executed_twice(self, store):
        store.create(_held(0))
        store.approve("held-0000", now="2026-01-01T12:00:00+00:00")
        store.mark_executed("held-0000")
        with pytest.raises(HeldActionNotFound):
            store.mark_executed("held-0000")

    def test_approved_not_executed_excludes_other_states(self, store):
        store.create(_held(0))
        store.create(_held(1))
        store.create(_held(2))
        store.approve("held-0000", now="2026-01-01T12:00:00+00:00")
        store.approve("held-0001", now="2026-01-01T12:00:00+00:00")
        store.mark_executed("held-0001")
        # held-0002 stays pending
        assert [h.id for h in store.approved_not_executed()] == ["held-0000"]

    def test_expire_due_cancels_only_past_pending(self, store):
        store.create(_held(0, expires="2026-01-02T00:00:00+00:00"))
        store.create(_held(1, expires="2026-01-05T00:00:00+00:00"))
        expired = store.expire_due(now="2026-01-03T00:00:00+00:00")
        assert expired == 1
        assert store.get("held-0000").status == "cancelled"
        assert store.get("held-0001").status == "pending"

    def test_pending_lists_oldest_first(self, store):
        store.create(_held(1, created="2026-01-01T10:00:00+00:00"))
        store.create(_held(0, created="2026-01-01T09:00:00+00:00"))
        assert [h.id for h in store.pending()] == ["held-0000", "held-0001"]
