"""notification.ack handler.

Layer: api.
Constitutional home: 12_API §13.
"""

from __future__ import annotations

from typing import Any

from kang.api.dispatch import Handler, HandlerContext
from kang.api.errors import ApiError
from kang.domain.ports.clock import Clock
from kang.domain.ports.notification_store import (
    NotificationNotFoundError,
    NotificationStore,
)

__all__ = ["make_notification_ack_handler"]


def make_notification_ack_handler(
    notification_store: NotificationStore, clock: Clock
) -> Handler:
    """`notification.ack` (12 §13): acking is a command, and it is additive
    — it stamps `acked_at` and never deletes history."""

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        notification_id = params.get("id")
        if not isinstance(notification_id, str) or not notification_id:
            raise ApiError("invalid_request", "notification.ack requires an 'id'")
        try:
            acked = notification_store.ack(notification_id, clock.now())
        except NotificationNotFoundError as exc:
            raise ApiError("not_found", f"no notification {notification_id}") from exc
        return {"id": acked.id, "state": acked.state}

    return handler
