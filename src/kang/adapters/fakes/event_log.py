"""FakeEventLog — in-memory EventLog, contract-paired with SqliteEventLog.

Layer: adapters/fakes (13 §2.3).
Constitutional home: 11_CODING §5/§7 (every port has an in-memory fake).
"""

from __future__ import annotations

from dataclasses import replace

from kang.domain.ports.clock import Clock
from kang.domain.ports.eventlog import (
    EventEnvelope,
    EventNotFoundError,
    StoredEvent,
    validate_envelope,
)

__all__ = ["FakeEventLog"]


class FakeEventLog:
    """EventLog over a list. Mirrors the port contract exactly: validation
    at append, monotonic seq, pending → confirmed | orphaned."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._events: list[StoredEvent] = []

    def append(self, envelope: EventEnvelope) -> int:
        validate_envelope(envelope)
        seq = len(self._events) + 1
        self._events.append(
            StoredEvent(
                seq=seq,
                envelope=envelope,
                recorded_at=self._clock.now().isoformat(),
                state="pending",
            )
        )
        return seq

    def _set_state(self, seq: int, state: str) -> None:
        if not 1 <= seq <= len(self._events):
            raise EventNotFoundError(str(seq))
        self._events[seq - 1] = replace(self._events[seq - 1], state=state)

    def confirm(self, seq: int) -> None:
        self._set_state(seq, "confirmed")

    def mark_orphaned(self, seq: int) -> None:
        self._set_state(seq, "orphaned")

    def pending(self) -> list[StoredEvent]:
        return [event for event in self._events if event.state == "pending"]

    def read_from(self, seq_exclusive: int) -> list[StoredEvent]:
        return [event for event in self._events if event.seq > seq_exclusive]

    def last_seq(self) -> int:
        return len(self._events)
