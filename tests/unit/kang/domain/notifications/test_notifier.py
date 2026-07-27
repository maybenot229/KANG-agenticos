"""The notifier — ladder decisions, the 24h duplicate rule, and the two
handler roles (enqueue on a fact, drain on the accelerant).

The two deliberate M5 simplifications are asserted here *as simplifications*
(see the RESERVED markers in notification_service.py): the ladder is tested
against the Idle-state assumption, and duplicate-detection against the
narrow same-refs-same-priority reading. These tests are the thing that must
change when M6's product-state machine and the dedup ADR land — they pin
current behaviour rather than claiming it is final.
"""

from __future__ import annotations

import itertools
from datetime import timedelta

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.fakes.notification_store import FakeNotificationStore
from kang.domain.notifications import (
    NotificationValidationError,
    decide_state,
    is_duplicate,
    make_deadline_enqueue_handler,
    make_drain_handler,
)
from kang.domain.ports.eventlog import EventEnvelope
from kang.domain.ports.notification_store import Notification

REFS = ({"kind": "deadline", "id": "dl-0001"},)


class _RecordingPublisher:
    """Captures what the enqueue half hands to the bus."""

    def __init__(self) -> None:
        self.published: list[Notification] = []
        self.caused_by: list[str] = []

    def publish_requested(self, notification: Notification, caused_by: str) -> None:
        self.published.append(notification)
        self.caused_by.append(caused_by)


def _approaching_envelope(deadline_id: str = "dl-0001") -> EventEnvelope:
    return EventEnvelope(
        event_id="ev-1",
        type="deadline.approaching",
        occurred_at="2026-01-01T00:00:00+00:00",
        principal="kernel:deadlines",
        correlation_id="corr-1",
        device_id="device-test",
        payload={
            "deadline_id": deadline_id,
            "title": "Submit entry",
            "at": "2026-01-05T09:00:00+00:00",
        },
        recovery_grade=False,
        entity_refs=({"kind": "deadline", "id": deadline_id},),
    )


@pytest.fixture
def wiring():
    clock = FakeClock()
    ids = (f"ntf-{n:04d}" for n in itertools.count())
    store = FakeNotificationStore()
    publisher = _RecordingPublisher()
    return {
        "clock": clock,
        "store": store,
        "publisher": publisher,
        "enqueue": make_deadline_enqueue_handler(
            store, publisher, clock, lambda: next(ids)
        ),
        "drain": make_drain_handler(store, clock),
    }


def _requested_envelope(notification: Notification) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"ev-req-{notification.id}",
        type="notification.requested",
        occurred_at="2026-01-01T00:00:00+00:00",
        principal="kernel:notifier",
        correlation_id=notification.correlation_id,
        device_id="device-test",
        payload={
            "notification_id": notification.id,
            "priority": notification.priority,
        },
        recovery_grade=False,
        entity_refs=notification.entity_refs,
    )


class TestLadder:
    @pytest.mark.parametrize(
        "priority,expected",
        [
            ("critical", "delivered"),
            ("attention", "delivered"),  # Idle assumption — RESERVED(M6)
            ("digest", "batched"),
            ("silent", "suppressed"),
        ],
    )
    def test_ladder_decision(self, priority, expected):
        assert decide_state(priority) == expected

    def test_unknown_priority_raises_rather_than_defaulting(self):
        # a silent default would mean a notification quietly not delivered
        with pytest.raises(NotificationValidationError):
            decide_state("urgent")


class TestDuplicateRule:
    def _existing(self, priority="attention", refs=REFS, state="delivered"):
        return Notification(
            id="ntf-old",
            priority=priority,
            principal="kernel:deadlines",
            correlation_id="corr-0",
            entity_refs=refs,
            payload={},
            state=state,
            created_at=FakeClock().now(),
        )

    def test_same_refs_same_priority_is_a_duplicate(self):
        assert is_duplicate(REFS, "attention", [self._existing()]) is True

    def test_different_priority_is_not_a_duplicate(self):
        # RESERVED: escalation attention -> critical currently delivers.
        assert is_duplicate(REFS, "critical", [self._existing()]) is False

    def test_different_entity_is_not_a_duplicate(self):
        other = ({"kind": "deadline", "id": "dl-9999"},)
        assert is_duplicate(other, "attention", [self._existing()]) is False

    def test_empty_history_is_not_a_duplicate(self):
        assert is_duplicate(REFS, "attention", []) is False


class TestEnqueueRole:
    def test_queues_a_row_and_publishes_the_accelerant(self, wiring):
        wiring["enqueue"](_approaching_envelope())
        queued = wiring["store"].queued()
        assert [n.state for n in queued] == ["queued"]
        assert queued[0].priority == "attention"  # 05 §13's ladder table
        # the row exists before the event — 15 §6.2's resilience claim
        assert [n.id for n in wiring["publisher"].published] == [queued[0].id]

    def test_carries_the_deadline_refs_for_deep_linking(self, wiring):
        wiring["enqueue"](_approaching_envelope())
        assert wiring["store"].queued()[0].entity_refs == REFS

    def test_threads_the_correlation_id(self, wiring):
        wiring["enqueue"](_approaching_envelope())
        assert wiring["store"].queued()[0].correlation_id == "corr-1"

    def test_threads_causation_so_the_depth_guard_stays_live(self, wiring):
        # Dropping this would make the chain look like a root cause and
        # silently disable EB-011.2 for the notifier path.
        wiring["enqueue"](_approaching_envelope())
        assert wiring["publisher"].caused_by == ["ev-1"]


class TestDrainRole:
    def test_drains_a_queued_row_to_delivered(self, wiring):
        wiring["enqueue"](_approaching_envelope())
        notification = wiring["store"].queued()[0]
        wiring["drain"](_requested_envelope(notification))
        assert wiring["store"].get(notification.id).state == "delivered"

    def test_delivery_stamps_delivered_at(self, wiring):
        wiring["enqueue"](_approaching_envelope())
        notification = wiring["store"].queued()[0]
        wiring["drain"](_requested_envelope(notification))
        assert wiring["store"].get(notification.id).delivered_at is not None

    def test_redelivery_of_the_event_does_not_re_decide(self, wiring):
        # D006 is at-least-once; deciding twice could re-surface an acked item
        wiring["enqueue"](_approaching_envelope())
        notification = wiring["store"].queued()[0]
        wiring["drain"](_requested_envelope(notification))
        wiring["store"].ack(notification.id, wiring["clock"].now())
        wiring["drain"](_requested_envelope(notification))  # duplicate delivery
        assert wiring["store"].get(notification.id).state == "acked"

    def test_second_notification_for_the_same_item_is_suppressed(self, wiring):
        for _ in range(2):
            wiring["enqueue"](_approaching_envelope())
        first, second = wiring["store"].queued()
        wiring["drain"](_requested_envelope(first))
        wiring["drain"](_requested_envelope(second))
        assert wiring["store"].get(first.id).state == "delivered"
        assert wiring["store"].get(second.id).state == "suppressed"

    def test_a_different_deadline_is_not_suppressed(self, wiring):
        wiring["enqueue"](_approaching_envelope("dl-0001"))
        wiring["enqueue"](_approaching_envelope("dl-0002"))
        for notification in list(wiring["store"].queued()):
            wiring["drain"](_requested_envelope(notification))
        assert [n.state for n in wiring["store"]._notifications.values()] == [
            "delivered",
            "delivered",
        ]

    def test_outside_the_24h_window_is_not_suppressed(self, wiring):
        wiring["enqueue"](_approaching_envelope())
        first = wiring["store"].queued()[0]
        wiring["drain"](_requested_envelope(first))
        wiring["clock"].advance(timedelta(hours=25).total_seconds())
        wiring["enqueue"](_approaching_envelope())
        second = wiring["store"].queued()[0]
        wiring["drain"](_requested_envelope(second))
        assert wiring["store"].get(second.id).state == "delivered"
