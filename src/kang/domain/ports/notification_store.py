"""Notification store port — the durable queue the notifier drains.

Layer: domain/ports. Ports own their datatypes (17 §7).
Constitutional home: docs/adr/005-notification-queue-schema.md (the row
shape), 15_EVENT_BUS §6.2 (the queue row is the durable work item;
`notification.requested` is only an accelerant — so a lost event costs
latency, never a notification), 09_UI §9 / 05_AGENTS §13 (the priority
ladder), 12_API §13 (`notification.list/ack`: acking is a command, and acks
never delete history — hence `acked_at` is an additive stamp, never a
deletion or an overwrite of the record).

Per-device operational state: no sync quartet (ADR-005 Option B), matching
`held_action` and `invocation`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

__all__ = [
    "NOTIFICATION_PRIORITIES",
    "NOTIFICATION_STATES",
    "Notification",
    "NotificationNotFoundError",
    "NotificationStore",
    "NotificationStoreError",
]

# 05_AGENTS §13's interruption ladder, most-interrupting first. Order is
# meaningful: the notifier's decision table walks it, and `explain` renders
# it, so it is a tuple rather than a set.
NOTIFICATION_PRIORITIES = ("critical", "attention", "digest", "silent")

# queued    — written, not yet decided on
# delivered — surfaced now (OS notification / beacon)
# batched   — held for a digest surface (morning plan, dashboard zones 3/4)
# suppressed— deliberately not surfaced; the row survives as honest history
# acked     — Kang acknowledged it
NOTIFICATION_STATES = ("queued", "delivered", "batched", "suppressed", "acked")


@dataclass(frozen=True)
class Notification:
    """One notification queue row (ADR-005).

    Immutable snapshot: transitions go through the store, which returns the
    new snapshot. `entity_refs` is the deep-link target set (09_UI §9: every
    beacon item deep-links) and doubles as the duplicate-identity key.
    """

    id: str
    priority: str
    principal: str
    correlation_id: str
    entity_refs: tuple[dict[str, str], ...]
    payload: dict
    state: str
    created_at: datetime
    delivered_at: datetime | None = None
    acked_at: datetime | None = None


class NotificationStoreError(Exception):
    """Base of the notification-store failure hierarchy (11 §9)."""


class NotificationNotFoundError(NotificationStoreError):
    """No notification with the given id exists."""


class NotificationStore(Protocol):
    """Persistence for the notification queue."""

    def create(self, notification: Notification) -> None:
        """Persist a new queue row."""
        ...

    def get(self, notification_id: str) -> Notification:
        """Return the notification or raise NotificationNotFoundError."""
        ...

    def queued(self) -> list[Notification]:
        """Every `queued` row, oldest first — the notifier's drain sweep
        (15 §6.2's catch-up path, which is what makes the event an
        accelerant rather than the work item). Deterministic total order:
        (created_at, id)."""
        ...

    def set_state(self, notification_id: str, state: str, at: datetime) -> Notification:
        """Transition to `delivered` | `batched` | `suppressed`, stamping
        `delivered_at` when the state is `delivered`. Raises
        NotificationNotFoundError if absent."""
        ...

    def ack(self, notification_id: str, at: datetime) -> Notification:
        """Stamp `acked_at` and move to `acked`. Additive: the row and its
        history survive (12 §13 — "acks never delete history")."""
        ...

    def recent_matching(
        self, entity_refs: tuple[dict[str, str], ...], priority: str, since: datetime
    ) -> list[Notification]:
        """Rows with the same entity refs and priority created at or after
        `since` that were **actually surfaced** to Kang — the
        duplicate-suppression lookup (09_UI §9's 24h no-re-notification
        rule, whose subject is *re*-notification).

        Surfaced means `delivered`, `batched`, or `acked`. Deliberately
        excluded:

        - `queued` — undecided. Including it would let a notification be
          suppressed by a *later* one that has not been surfaced yet, so
          two simultaneous enqueues could suppress each other and Kang
          would be told nothing at all.
        - `suppressed` — never reached Kang, so it cannot be the thing a
          later notification would be repeating; including it would let one
          suppression cascade into permanent silence for that item.
        """
        ...
