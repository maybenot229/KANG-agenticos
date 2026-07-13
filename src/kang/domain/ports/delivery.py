"""Delivery-bookkeeping port — per-subscriber cursors and dead letters.

Layer: domain/ports. Ports own their datatypes (17 §7).
Constitutional home: 15_EVENT_BUS EB-007 (per-subscriber independent
cursors are delivery truth; FIFO by seq; retries → dead-letter; the cursor
advances past a dead-lettered event so one poison event never starves a
subscriber's stream), §5.2 (subscription_cursor, dead_letter tables live in
eventlog.db). Implemented by adapters/eventlog over the same connection as
the event table; fake in adapters/fakes (contract-paired, 13 §2.3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

__all__ = ["DeadLetter", "DeliveryStore"]


@dataclass(frozen=True)
class DeadLetter:
    """A delivery that failed its maximum attempts (§7.4). Never
    auto-discarded, never auto-redelivered — surfaced until Kang acts."""

    id: str
    event_seq: int
    subscriber: str
    attempts: int
    last_error: str
    created_at: str


class DeliveryStore(Protocol):
    """Durable delivery state: where each subscriber's stream stands, and
    what it could not be delivered."""

    def cursor(self, subscriber: str) -> int:
        """The subscriber's last delivered seq (0 when never delivered)."""
        ...

    def advance_cursor(self, subscriber: str, seq: int) -> None:
        """Record delivery (or dead-lettered skip) up to and including seq.
        Advance is the delivery acknowledgment (§7.2)."""
        ...

    def record_dead_letter(
        self,
        dead_letter_id: str,
        event_seq: int,
        subscriber: str,
        attempts: int,
        last_error: str,
    ) -> DeadLetter:
        """Persist a dead letter (§7.5). One honest sentence of error."""
        ...

    def dead_letters(self) -> list[DeadLetter]:
        """Unresolved dead letters, oldest first — the health-panel source."""
        ...
