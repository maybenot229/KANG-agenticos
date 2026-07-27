"""Ladder policy, queue semantics.

Layer: domain.
Constitutional home: 09_UI_DESIGN §9; 15_EVENT_BUS §6.2 (built at M5 — 18 §3);
docs/adr/005-notification-queue-schema.md.
"""

from kang.domain.notifications.notification_service import (
    DEDUP_WINDOW,
    NotificationValidationError,
    decide_state,
    dedup_window_start,
    is_duplicate,
    notification_requested_payload,
)
from kang.domain.notifications.notifier import (
    DEADLINE_APPROACHING_PRIORITY,
    NotificationPublisher,
    make_deadline_enqueue_handler,
    make_drain_handler,
)

__all__ = [
    "DEADLINE_APPROACHING_PRIORITY",
    "DEDUP_WINDOW",
    "NotificationPublisher",
    "NotificationValidationError",
    "decide_state",
    "dedup_window_start",
    "is_duplicate",
    "make_deadline_enqueue_handler",
    "make_drain_handler",
    "notification_requested_payload",
]
