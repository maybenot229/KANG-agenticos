"""The notifier — turns facts into queue rows, then drains the queue.

Layer: domain/notifications. It imports only `domain/ports` (legal per
17 §4.2) and returns plain callables; the composition root wraps them as bus
`Subscriber`s. This is why the notifier needs no `kernel/notifier` package —
17 §2's kernel tree does not contain one, and adding a kernel subpackage
would require an ADR (17 §17.1). Policy here, wiring at the root.

Constitutional home: 05_AGENTS Appendix F (the notifier subscribes to
`deadline.approaching` *and* `notification.requested`), 15_EVENT_BUS §6.2
(the queue row is the durable work item; the event is an accelerant),
12_API §14 ("notifications originate exclusively from core
`notification.requested` events; clients render, ack, and deep-link — they
MUST NOT mint notifications").

**Two roles, one module, one seam.** `enqueue_*` decides a notification
became due, writes the queue row, and publishes `notification.requested`.
`drain` consumes that event and applies the ladder. At M5 both run in the
same process, which makes the event look like ceremony — it is not: it is
the seam that lets the drain half become a sidecar later (15 §15.1) without
the enqueue half changing. Collapsing them now would weld two roles that
the constitution separates.
"""

from __future__ import annotations

from typing import Callable, Protocol

from kang.domain.notifications.notification_service import (
    decide_state,
    dedup_window_start,
    is_duplicate,
)
from kang.domain.ports.clock import Clock
from kang.domain.ports.eventlog import EventEnvelope
from kang.domain.ports.notification_store import Notification, NotificationStore

__all__ = [
    "NotificationPublisher",
    "make_deadline_enqueue_handler",
    "make_drain_handler",
]

# 05_AGENTS §13's ladder table names "Approaching deadlines" under
# `attention` explicitly. Escalation to `critical` for a deadline "in danger
# today" is also named there, but "in danger" is undefined — see the report
# accompanying this increment; not guessed here.
DEADLINE_APPROACHING_PRIORITY = "attention"


class NotificationPublisher(Protocol):
    """The one thing the notifier needs from the bus, expressed as a port so
    `domain/` never imports `kernel/` (17 §4.3 rule 1). The composition root
    supplies an implementation that publishes `notification.requested`.

    `caused_by` is the event_id this notification reacts to. It is REQUIRED,
    not optional: a publisher that drops it makes the chain look like a
    series of root causes, which silently disables EB-011.2's causation-depth
    guard for this path (`causation_depth(None)` is 0).
    """

    def publish_requested(self, notification: Notification, caused_by: str) -> None: ...


def make_deadline_enqueue_handler(
    store: NotificationStore,
    publisher: NotificationPublisher,
    clock: Clock,
    new_id: Callable[[], str],
) -> Callable[[EventEnvelope], None]:
    """`deadline.approaching` → a queued notification + the accelerant event.

    The row is written first and the event published second, for the same
    reason the deadline sweep commits before announcing: the durable work
    item must exist before anything is told to go look for it. A crash
    between them leaves a `queued` row that the notifier's own drain sweep
    finds — which is exactly the resilience 15 §6.2 claims for this design.
    """

    def handle(envelope: EventEnvelope) -> None:
        # Subscribers receive the whole stream — EB-007 delivers every event
        # past the cursor and the bus does no per-type routing — so each
        # handler filters for its own type.
        if envelope.type != "deadline.approaching":
            return
        notification = Notification(
            id=new_id(),
            priority=DEADLINE_APPROACHING_PRIORITY,
            principal=envelope.principal,
            correlation_id=envelope.correlation_id,
            entity_refs=envelope.entity_refs,
            payload={
                "kind": "deadline.approaching",
                "title": envelope.payload.get("title"),
                "at": envelope.payload.get("at"),
            },
            state="queued",
            created_at=clock.now(),
        )
        store.create(notification)
        publisher.publish_requested(notification, caused_by=envelope.event_id)

    return handle


def make_drain_handler(
    store: NotificationStore, clock: Clock
) -> Callable[[EventEnvelope], None]:
    """`notification.requested` → apply the ladder to the queued row.

    Idempotent on redelivery (D006 is at-least-once): a row that is no
    longer `queued` has already been decided, and re-deciding it would let a
    duplicate delivery re-surface something Kang already acked.
    """

    def handle(envelope: EventEnvelope) -> None:
        if envelope.type != "notification.requested":  # see enqueue's note
            return
        notification_id = envelope.payload["notification_id"]
        notification = store.get(notification_id)
        if notification.state != "queued":
            return  # already decided — at-least-once delivery, decided once
        now = clock.now()
        recent = store.recent_matching(
            notification.entity_refs, notification.priority, dedup_window_start(now)
        )
        others = [n for n in recent if n.id != notification.id]
        if is_duplicate(notification.entity_refs, notification.priority, others):
            store.set_state(notification.id, "suppressed", now)
            return
        store.set_state(notification.id, decide_state(notification.priority), now)

    return handle
