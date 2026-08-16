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
DECIDED = "2026-01-01T12:00:00+00:00"  # inside the window
KANG = "kang"  # ADR-025: the deciding principal for approve/cancel
SWEEP = "kernel:scheduler"  # ADR-025: the expiry job's own principal


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
        approved = store.approve(
            "held-0000", now="2026-01-01T12:00:00+00:00", decided_by=KANG
        )
        assert approved.status == "approved"
        assert store.get("held-0000").status == "approved"

    def test_approve_past_expiry_is_refused(self, store):
        store.create(_held(0))
        with pytest.raises(HeldActionExpired):
            store.approve("held-0000", now="2026-01-03T09:00:00+00:00", decided_by=KANG)
        current = store.get("held-0000")
        assert current.status == "pending"  # unchanged
        # ADR-025: a refused transition stamps no provenance either.
        assert current.decided_at is None
        assert current.decided_by is None

    def test_cancel_transitions_to_cancelled(self, store):
        store.create(_held(0))
        cancelled = store.cancel("held-0000", now=DECIDED, decided_by=KANG)
        assert cancelled.status == "cancelled"

    def test_cannot_approve_a_cancelled_action(self, store):
        store.create(_held(0))
        store.cancel("held-0000", now=DECIDED, decided_by=KANG)
        with pytest.raises(HeldActionNotFound):
            store.approve("held-0000", now="2026-01-01T12:00:00+00:00", decided_by=KANG)

    def test_mark_executed_after_approve(self, store):
        store.create(_held(0))
        store.approve("held-0000", now="2026-01-01T12:00:00+00:00", decided_by=KANG)
        executed = store.mark_executed("held-0000")
        assert executed.status == "executed"
        assert store.get("held-0000").status == "executed"

    def test_cannot_mark_executed_before_approval(self, store):
        store.create(_held(0))
        with pytest.raises(HeldActionNotFound):
            store.mark_executed("held-0000")

    def test_cannot_mark_executed_twice(self, store):
        store.create(_held(0))
        store.approve("held-0000", now="2026-01-01T12:00:00+00:00", decided_by=KANG)
        store.mark_executed("held-0000")
        with pytest.raises(HeldActionNotFound):
            store.mark_executed("held-0000")

    def test_approved_not_executed_excludes_other_states(self, store):
        store.create(_held(0))
        store.create(_held(1))
        store.create(_held(2))
        store.approve("held-0000", now="2026-01-01T12:00:00+00:00", decided_by=KANG)
        store.approve("held-0001", now="2026-01-01T12:00:00+00:00", decided_by=KANG)
        store.mark_executed("held-0001")
        # held-0002 stays pending
        assert [h.id for h in store.approved_not_executed()] == ["held-0000"]

    def test_expire_due_expires_only_past_pending(self, store):
        store.create(_held(0, expires="2026-01-02T00:00:00+00:00"))
        store.create(_held(1, expires="2026-01-05T00:00:00+00:00"))
        expired = store.expire_due(now="2026-01-03T00:00:00+00:00", decided_by=SWEEP)
        assert expired == 1
        # 'expired' (ADR-024), not 'cancelled' — distinct from Kang
        # explicitly declining via cancel().
        assert store.get("held-0000").status == "expired"
        assert store.get("held-0001").status == "pending"

    def test_pending_lists_oldest_first(self, store):
        store.create(_held(1, created="2026-01-01T10:00:00+00:00"))
        store.create(_held(0, created="2026-01-01T09:00:00+00:00"))
        assert [h.id for h in store.pending()] == ["held-0000", "held-0001"]

    def test_create_persists_params(self, store):
        held = _held(0)
        held.params.update({"job_id": "morning_plan"})
        store.create(held)
        assert store.get("held-0000").params == {"job_id": "morning_plan"}

    def test_approve_in_txn_follows_the_same_guards_as_approve(self, store):
        # ADR-021: approve_in_txn is the transaction-participating variant
        # held_action.approve's handler uses for transactional commit_mode
        # — same guard contract as approve(), just without its own
        # BEGIN/COMMIT (the caller owns that boundary).
        store.create(_held(0))
        approved = store.approve_in_txn("held-0000", now=DECIDED, decided_by=KANG)
        assert approved.status == "approved"
        assert store.get("held-0000").status == "approved"

    def test_approve_in_txn_past_expiry_is_refused(self, store):
        store.create(_held(0))
        with pytest.raises(HeldActionExpired):
            store.approve_in_txn(
                "held-0000", now="2026-01-03T09:00:00+00:00", decided_by=KANG
            )
        assert store.get("held-0000").status == "pending"

    def test_mark_executed_in_txn_follows_the_same_guards_as_mark_executed(self, store):
        store.create(_held(0))
        store.approve_in_txn("held-0000", now=DECIDED, decided_by=KANG)
        executed = store.mark_executed_in_txn("held-0000")
        assert executed.status == "executed"
        assert store.get("held-0000").status == "executed"

    def test_mark_executed_in_txn_before_approval_raises(self, store):
        store.create(_held(0))
        with pytest.raises(HeldActionNotFound):
            store.mark_executed_in_txn("held-0000")

    # ---- ADR-025: transition provenance ---------------------------------

    def test_a_new_held_action_has_no_provenance(self, store):
        """`pending` means undecided — the columns are nullable for
        exactly this state, and NULL here means "not decided yet"."""
        store.create(_held(0))
        current = store.get("held-0000")
        assert current.decided_at is None
        assert current.decided_by is None

    def test_approve_records_who_and_when(self, store):
        store.create(_held(0))
        approved = store.approve("held-0000", now=DECIDED, decided_by=KANG)
        assert (approved.decided_at, approved.decided_by) == (DECIDED, KANG)
        # Durable, not just on the returned object.
        reread = store.get("held-0000")
        assert (reread.decided_at, reread.decided_by) == (DECIDED, KANG)

    def test_cancel_records_who_and_when(self, store):
        store.create(_held(0))
        cancelled = store.cancel("held-0000", now=DECIDED, decided_by=KANG)
        assert (cancelled.decided_at, cancelled.decided_by) == (DECIDED, KANG)
        assert store.get("held-0000").decided_by == KANG

    def test_expire_records_the_sweep_as_the_decider(self, store):
        """The whole point of ADR-024+025 together: an expired row is
        distinguishable from a declined one BOTH by status and by who
        effected it — `kernel:scheduler`, never a human."""
        store.create(_held(0, expires="2026-01-02T00:00:00+00:00"))
        store.expire_due(now="2026-01-03T00:00:00+00:00", decided_by=SWEEP)
        expired = store.get("held-0000")
        assert expired.status == "expired"
        assert expired.decided_at == "2026-01-03T00:00:00+00:00"
        assert expired.decided_by == SWEEP

    def test_mark_executed_preserves_the_approve_steps_provenance(self, store):
        """ADR-025's central design call: approved → executed is NOT a
        transition out of `pending`, so it must not overwrite who
        approved. The decision was the approval; execution is the effect
        landing."""
        store.create(_held(0))
        store.approve("held-0000", now=DECIDED, decided_by=KANG)
        executed = store.mark_executed("held-0000")
        assert executed.status == "executed"
        assert (executed.decided_at, executed.decided_by) == (DECIDED, KANG)

    def test_mark_executed_in_txn_also_preserves_provenance(self, store):
        store.create(_held(0))
        store.approve_in_txn("held-0000", now=DECIDED, decided_by=KANG)
        executed = store.mark_executed_in_txn("held-0000")
        assert (executed.decided_at, executed.decided_by) == (DECIDED, KANG)

    def test_the_expiry_sweep_only_stamps_rows_it_actually_expires(self, store):
        """A still-fresh pending row keeps NULL provenance — the sweep's
        WHERE clause and its provenance write are the same statement, so
        they cannot drift apart."""
        store.create(_held(0, expires="2026-01-02T00:00:00+00:00"))
        store.create(_held(1, expires="2026-01-05T00:00:00+00:00"))
        store.expire_due(now="2026-01-03T00:00:00+00:00", decided_by=SWEEP)
        untouched = store.get("held-0001")
        assert untouched.status == "pending"
        assert untouched.decided_at is None
        assert untouched.decided_by is None
