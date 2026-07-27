"""NotificationStore port-contract suite — fake and sqlite (13 §2.3).
Subclasses provide ``store``. The same suite runs against both so the fake
cannot drift from the real store.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from kang.domain.ports.notification_store import (
    Notification,
    NotificationNotFoundError,
)

CREATED = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
REFS = ({"kind": "deadline", "id": "dl-0001"},)


def _notification(
    index: int = 0,
    priority: str = "attention",
    state: str = "queued",
    created_at: datetime = CREATED,
    entity_refs: tuple[dict[str, str], ...] = REFS,
) -> Notification:
    return Notification(
        id=f"ntf-{index:04d}",
        priority=priority,
        principal="kernel:deadlines",
        correlation_id=f"corr-{index:04d}",
        entity_refs=entity_refs,
        payload={"kind": "deadline.approaching", "title": "Submit entry"},
        state=state,
        created_at=created_at,
    )


class NotificationStoreContract:
    def test_create_then_get_roundtrips(self, store):
        notification = _notification(0)
        store.create(notification)
        assert store.get(notification.id) == notification

    def test_get_unknown_raises(self, store):
        with pytest.raises(NotificationNotFoundError):
            store.get("ntf-none")

    def test_entity_refs_and_payload_survive_the_roundtrip(self, store):
        store.create(_notification(0))
        loaded = store.get("ntf-0000")
        assert loaded.entity_refs == REFS
        assert loaded.payload["title"] == "Submit entry"

    def test_queued_returns_only_queued_oldest_first(self, store):
        store.create(_notification(1, created_at=CREATED + timedelta(hours=1)))
        store.create(_notification(0))
        store.create(_notification(2, state="delivered"))
        assert [n.id for n in store.queued()] == ["ntf-0000", "ntf-0001"]

    def test_set_state_delivered_stamps_delivered_at(self, store):
        store.create(_notification(0))
        at = CREATED + timedelta(minutes=5)
        updated = store.set_state("ntf-0000", "delivered", at)
        assert updated.state == "delivered"
        assert updated.delivered_at == at

    def test_set_state_suppressed_does_not_stamp_delivered_at(self, store):
        store.create(_notification(0))
        updated = store.set_state("ntf-0000", "suppressed", CREATED)
        assert updated.state == "suppressed"
        assert updated.delivered_at is None

    def test_set_state_unknown_raises(self, store):
        with pytest.raises(NotificationNotFoundError):
            store.set_state("ntf-none", "delivered", CREATED)

    def test_ack_is_additive_and_preserves_the_row(self, store):
        # 12 §13: "acking is a command … acks never delete history"
        store.create(_notification(0))
        at = CREATED + timedelta(hours=2)
        acked = store.ack("ntf-0000", at)
        assert acked.state == "acked"
        assert acked.acked_at == at
        # the record survives in full — nothing cleared
        assert acked.payload["title"] == "Submit entry"
        assert acked.entity_refs == REFS
        assert store.get("ntf-0000") == acked

    def test_ack_unknown_raises(self, store):
        with pytest.raises(NotificationNotFoundError):
            store.ack("ntf-none", CREATED)

    def test_recent_matching_finds_same_refs_and_priority(self, store):
        store.create(_notification(0, state="delivered"))
        found = store.recent_matching(REFS, "attention", CREATED - timedelta(hours=1))
        assert [n.id for n in found] == ["ntf-0000"]

    def test_recent_matching_excludes_other_priorities(self, store):
        store.create(_notification(0, priority="critical", state="delivered"))
        found = store.recent_matching(REFS, "attention", CREATED - timedelta(hours=1))
        assert found == []

    def test_recent_matching_excludes_other_entities(self, store):
        store.create(_notification(0, state="delivered"))
        other = ({"kind": "deadline", "id": "dl-9999"},)
        found = store.recent_matching(other, "attention", CREATED - timedelta(hours=1))
        assert found == []

    def test_recent_matching_excludes_rows_outside_the_window(self, store):
        store.create(_notification(0, state="delivered"))
        found = store.recent_matching(REFS, "attention", CREATED + timedelta(hours=1))
        assert found == []

    def test_recent_matching_excludes_suppressed_rows(self, store):
        # a suppressed duplicate must not itself become the reason a later
        # notification is suppressed — otherwise one suppression cascades
        store.create(_notification(0, state="suppressed"))
        found = store.recent_matching(REFS, "attention", CREATED - timedelta(hours=1))
        assert found == []

    def test_recent_matching_excludes_queued_rows(self, store):
        # a queued row is UNDECIDED, not a prior notification. If it counted,
        # two simultaneous enqueues would suppress each other and Kang would
        # be told nothing at all — the failure this rule must not cause.
        store.create(_notification(0, state="queued"))
        found = store.recent_matching(REFS, "attention", CREATED - timedelta(hours=1))
        assert found == []

    @pytest.mark.parametrize("surfaced", ["delivered", "batched", "acked"])
    def test_recent_matching_counts_every_surfaced_state(self, store, surfaced):
        store.create(_notification(0, state=surfaced))
        found = store.recent_matching(REFS, "attention", CREATED - timedelta(hours=1))
        assert [n.id for n in found] == ["ntf-0000"]
