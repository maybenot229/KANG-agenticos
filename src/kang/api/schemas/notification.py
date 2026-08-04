"""Request/response schemas for notification.* operations (ADR-010 Ruling 1).

Layer: api.
Constitutional home: 12_API §2/§13, ADR-010 Ruling 1. `id`'s non-empty
constraint mirrors `operations.py::make_notification_ack_handler`'s exact
check — `not notification_id`, a truthiness test, not a `.strip()` test
(unlike `task.create`'s title). `Field(min_length=1)` matches that
precisely: it rejects `""` but allows a whitespace-only string, exactly as
the handler does today. Do not "fix" this to `.strip()` semantics without
first changing the handler — the schema must describe the real contract.

Roll-out session: 2026-07-31 (follow-up to the task.* proof-of-pattern).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = [
    "NotificationAckRequest",
    "NotificationAckResponse",
]


class NotificationAckRequest(BaseModel):
    """`notification.ack` params (operations.py::make_notification_ack_handler)."""

    id: str = Field(min_length=1)


class NotificationAckResponse(BaseModel):
    """`notification.ack` result (operations.py::make_notification_ack_handler)."""

    id: str
    state: str
