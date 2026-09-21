"""CandidateQueueStore port-contract suite — run identically against the fake
and the real adapter (13 §2.3).

Subclasses provide a `store` fixture (a fresh `CandidateQueueStore`).
"""

from __future__ import annotations

import pytest

from kang.domain.ports.candidate_queue_store import Candidate

T0 = "2026-09-21T10:00:00+00:00"
DAY = "2026-09-22T10:00:00+00:00"
LATER = "2026-10-06T10:00:00+00:00"  # 14 days after T0


def candidate(candidate_id="cand-1", proposed_at=T0, expires_at=LATER, **overrides):
    payload = {
        "type": "fact",
        "content": "the term ends june 12",
        "confidence": 0.5,
        "created_by": "agent:memory_steward",
    }
    payload.update(overrides)
    return Candidate(
        id=candidate_id,
        payload=payload,
        proposed_at=proposed_at,
        expires_at=expires_at,
    )


class CandidateQueueStoreContract:
    def test_enqueue_then_get_round_trips(self, store):
        original = candidate()
        store.enqueue(original)
        assert store.get("cand-1") == original

    def test_get_returns_none_for_an_unknown_id(self, store):
        assert store.get("never-proposed") is None

    def test_a_new_candidate_is_pending(self, store):
        store.enqueue(candidate())
        assert store.get("cand-1").pending

    def test_a_duplicate_id_is_refused(self, store):
        store.enqueue(candidate())
        with pytest.raises(Exception):
            store.enqueue(candidate())

    def test_resolve_marks_a_pending_row(self, store):
        store.enqueue(candidate())
        assert store.resolve("cand-1", "rejected", DAY) is True
        row = store.get("cand-1")
        assert (row.resolved, row.resolved_at, row.pending) == ("rejected", DAY, False)

    def test_resolve_never_touches_an_already_resolved_row(self, store):
        store.enqueue(candidate())
        store.resolve("cand-1", "rejected", DAY)
        assert store.resolve("cand-1", "approved", LATER) is False
        assert store.get("cand-1").resolved == "rejected"

    def test_resolve_of_an_unknown_id_is_false(self, store):
        assert store.resolve("ghost", "rejected", DAY) is False

    def test_resolve_refuses_a_resolution_outside_the_closed_set(self, store):
        store.enqueue(candidate())
        with pytest.raises(ValueError):
            store.resolve("cand-1", "maybe", DAY)

    def test_list_queue_puts_pending_first_oldest_first(self, store):
        store.enqueue(candidate("late", proposed_at="2026-09-21T12:00:00+00:00"))
        store.enqueue(candidate("early", proposed_at="2026-09-21T09:00:00+00:00"))
        store.enqueue(candidate("done", proposed_at="2026-09-21T08:00:00+00:00"))
        store.resolve("done", "rejected", DAY)
        assert [c.id for c in store.list_queue(10)] == ["early", "late", "done"]

    def test_list_queue_breaks_ties_by_confidence_then_id(self, store):
        store.enqueue(candidate("a-low", confidence=0.1))
        store.enqueue(candidate("b-high", confidence=0.9))
        store.enqueue(candidate("c-high", confidence=0.9))
        assert [c.id for c in store.list_queue(10)] == ["b-high", "c-high", "a-low"]

    def test_list_queue_respects_the_limit(self, store):
        for i in range(5):
            store.enqueue(
                candidate(f"c{i}", proposed_at=f"2026-09-21T10:0{i}:00+00:00")
            )
        assert len(store.list_queue(2)) == 2

    def test_expire_due_expires_only_pending_rows_past_their_window(self, store):
        store.enqueue(candidate("stale", expires_at="2026-10-01T00:00:00+00:00"))
        store.enqueue(candidate("fresh", expires_at="2026-11-01T00:00:00+00:00"))
        expired = store.expire_due("2026-10-15T00:00:00+00:00")
        assert expired == ("stale",)
        assert store.get("stale").resolved == "expired"
        assert store.get("stale").resolved_at == "2026-10-15T00:00:00+00:00"
        assert store.get("fresh").pending

    def test_expire_due_is_strictly_after_the_window(self, store):
        store.enqueue(candidate("edge", expires_at="2026-10-01T00:00:00+00:00"))
        assert store.expire_due("2026-10-01T00:00:00+00:00") == ()

    def test_expire_due_leaves_already_resolved_rows_alone(self, store):
        store.enqueue(candidate("done", expires_at="2026-10-01T00:00:00+00:00"))
        store.resolve("done", "approved", DAY)
        assert store.expire_due("2026-10-15T00:00:00+00:00") == ()
        assert store.get("done").resolved == "approved"

    def test_expire_due_is_idempotent(self, store):
        store.enqueue(candidate("stale", expires_at="2026-10-01T00:00:00+00:00"))
        store.expire_due("2026-10-15T00:00:00+00:00")
        assert store.expire_due("2026-10-16T00:00:00+00:00") == ()
