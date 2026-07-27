"""FakeNotificationStore — in-memory NotificationStore, contract-paired.

Layer: adapters/fakes.
Constitutional home: 11_CODING §5/§7 (every port has an in-memory fake);
13 §2.3 (a fake that lies is a red build — the same contract suite runs
against this and SqliteNotificationStore).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from kang.domain.ports.notification_store import (
    Notification,
    NotificationNotFoundError,
)

__all__ = ["FakeNotificationStore"]


class FakeNotificationStore:
    """NotificationStore over a dict, mirroring the real store's guards."""

    def __init__(self) -> None:
        self._notifications: dict[str, Notification] = {}

    def create(self, notification: Notification) -> None:
        if notification.id in self._notifications:
            raise ValueError(f"duplicate notification {notification.id}")
        self._notifications[notification.id] = notification

    def get(self, notification_id: str) -> Notification:
        try:
            return self._notifications[notification_id]
        except KeyError:
            raise NotificationNotFoundError(notification_id) from None

    def queued(self) -> list[Notification]:
        return sorted(
            (n for n in self._notifications.values() if n.state == "queued"),
            key=lambda n: (n.created_at, n.id),
        )

    def set_state(
        self, notification_id: str, state: str, at: datetime
    ) -> Notification:
        current = self.get(notification_id)
        updated = replace(
            current,
            state=state,
            delivered_at=at if state == "delivered" else current.delivered_at,
        )
        self._notifications[notification_id] = updated
        return updated

    def ack(self, notification_id: str, at: datetime) -> Notification:
        current = self.get(notification_id)
        updated = replace(current, state="acked", acked_at=at)
        self._notifications[notification_id] = updated
        return updated

    def recent_matching(
        self, entity_refs: tuple[dict[str, str], ...], priority: str, since: datetime
    ) -> list[Notification]:
        return sorted(
            (
                n
                for n in self._notifications.values()
                if n.priority == priority
                and n.entity_refs == entity_refs
                and n.created_at >= since
                # only surfaced rows count as a prior notification
                and n.state in ("delivered", "batched", "acked")
            ),
            key=lambda n: (n.created_at, n.id),
        )
