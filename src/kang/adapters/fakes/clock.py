"""FakeClock — deterministic Clock for domain tests.

Layer: adapters/fakes (shipped, versioned — 13 §2.3).
Constitutional home: 11_CODING §14 (injected clock); 13_TESTING §1.4
(deterministic always: freeze time, advance explicitly).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

__all__ = ["FakeClock"]


class FakeClock:
    """Clock implementation frozen at a chosen instant."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 1, 1, tzinfo=timezone.utc)
        if self._now.tzinfo is None:
            raise ValueError("FakeClock requires an aware datetime")

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)
