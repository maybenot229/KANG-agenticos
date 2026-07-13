"""FakeDeliveryStore — in-memory DeliveryStore, contract-paired (13 §2.3).

Layer: adapters/fakes.
Constitutional home: 11_CODING §5/§7 (every port has an in-memory fake).
"""

from __future__ import annotations

from kang.domain.ports.clock import Clock
from kang.domain.ports.delivery import DeadLetter

__all__ = ["FakeDeliveryStore"]


class FakeDeliveryStore:
    """DeliveryStore over dicts. Cursors are monotonic (never retreat)."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._cursors: dict[str, int] = {}
        self._dead_letters: list[DeadLetter] = []

    def cursor(self, subscriber: str) -> int:
        return self._cursors.get(subscriber, 0)

    def advance_cursor(self, subscriber: str, seq: int) -> None:
        if seq > self._cursors.get(subscriber, 0):
            self._cursors[subscriber] = seq

    def record_dead_letter(
        self,
        dead_letter_id: str,
        event_seq: int,
        subscriber: str,
        attempts: int,
        last_error: str,
    ) -> DeadLetter:
        dead_letter = DeadLetter(
            id=dead_letter_id,
            event_seq=event_seq,
            subscriber=subscriber,
            attempts=attempts,
            last_error=last_error,
            created_at=self._clock.now().isoformat(),
        )
        self._dead_letters.append(dead_letter)
        return dead_letter

    def dead_letters(self) -> list[DeadLetter]:
        return list(self._dead_letters)
