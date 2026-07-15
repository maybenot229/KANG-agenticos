"""Delivery — per-subscriber cursors, FIFO, retries, dead letters (EB-007).

Layer: kernel/bus. A supervision point (11 §9's closed list): a handler
exception is captured here, retried, and dead-lettered — it never escapes
to blocking siblings.
Constitutional home: 15_EVENT_BUS EB-007 (per-subscriber independent
cursors; FIFO by seq; retry ×5 → dead-letter; the cursor advances PAST a
dead-lettered event so one poison event never starves a subscriber's
stream; consumers dedup on event_id — at-least-once). Only CONFIRMED events
are delivered (EB-004 step 5 follows confirmation); orphaned events are
never delivered (§4.3); a pending event stops the sweep to preserve FIFO.

Timed backoff (M3): between failed attempts the delivery waits
`retry_delay_seconds(attempt)` via the injected Sleeper (the real one sleeps
wall-time; the fake records the delays so tests prove the wait without
waiting — 13 §1.4). This closes the M2 deferral: redelivery no longer fires
immediately, it honors the exponential schedule.
"""

from __future__ import annotations

from typing import Callable

from kang.domain.ports.delivery import DeliveryStore
from kang.domain.ports.eventlog import EventEnvelope, EventLog
from kang.domain.ports.sleeper import Sleeper
from kang.kernel.audit.service import AuditService

__all__ = ["Delivery", "Handler", "MAX_ATTEMPTS", "retry_delay_seconds"]

# EB-007.4: "maximum 5 attempts, then dead-letter."
MAX_ATTEMPTS = 5

Handler = Callable[[EventEnvelope], None]


def retry_delay_seconds(attempt: int) -> float:
    """Exponential backoff schedule (base 0.5 s, doubling) the async loop
    will honor between attempts (EB-007.4). Pure — tested for shape."""
    if attempt < 1:
        raise ValueError("attempt is 1-based")
    return 0.5 * (2 ** (attempt - 1))


class Delivery:
    """Drains one subscriber's stream from its cursor. Deterministic per
    subscriber (FIFO by seq); cross-subscriber interleaving is not relied
    upon (§7.3)."""

    def __init__(
        self,
        event_log: EventLog,
        delivery_store: DeliveryStore,
        audit: AuditService,
        dead_letter_id: Callable[[], str],
        sleeper: Sleeper,
        max_attempts: int = MAX_ATTEMPTS,
    ) -> None:
        self._event_log = event_log
        self._store = delivery_store
        self._audit = audit
        self._dead_letter_id = dead_letter_id
        self._sleeper = sleeper
        self._max_attempts = max_attempts

    def deliver(self, subscriber: str, handler: Handler) -> int:
        """Deliver every confirmed event past the cursor, in seq order.
        Returns the count of events the cursor advanced over."""
        advanced = 0
        for stored in self._event_log.read_from(self._store.cursor(subscriber)):
            if stored.state == "pending":
                break  # not yet confirmed — preserve FIFO, wait
            if stored.state == "confirmed":
                self._deliver_one(subscriber, handler, stored.seq, stored.envelope)
            # orphaned: never delivered (§4.3) — advance past it
            self._store.advance_cursor(subscriber, stored.seq)
            advanced += 1
        return advanced

    def _deliver_one(
        self, subscriber: str, handler: Handler, seq: int, envelope: EventEnvelope
    ) -> None:
        last_error = ""
        for attempt in range(1, self._max_attempts + 1):
            try:
                handler(envelope)
                return
            except Exception as exc:  # supervision point (11 §9)
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < self._max_attempts:
                    # Wait the exponential backoff before the next attempt
                    # (EB-007.4). Fake sleeper records; real one waits.
                    self._sleeper.sleep(retry_delay_seconds(attempt))
        self._dead_letter(subscriber, seq, last_error)

    def _dead_letter(self, subscriber: str, seq: int, last_error: str) -> None:
        self._store.record_dead_letter(
            self._dead_letter_id(), seq, subscriber, self._max_attempts, last_error
        )
        self._audit.record(
            principal="kernel:bus",
            action="delivery.dead_lettered",
            details={"subscriber": subscriber, "event_seq": seq, "error": last_error},
        )
