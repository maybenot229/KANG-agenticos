"""FakeCalendarStore — in-memory CalendarStore, contract-paired (13 §2.3).

Layer: adapters/fakes.
Constitutional home: 11_CODING §5/§7 (every port has an in-memory fake).
"""

from __future__ import annotations

from kang.domain.ports.calendar_store import CalendarEvent

__all__ = ["FakeCalendarStore"]


class FakeCalendarStore:
    """CalendarStore over a list, mirroring the real store's ordering."""

    def __init__(self, events: list[CalendarEvent] | None = None) -> None:
        self._events = list(events or [])

    def add(self, event: CalendarEvent) -> None:
        """Test-only seeding. The port itself is read-only (calendar write is
        v0.2 and consequential); this exists so fixtures can populate a day
        without a provider."""
        self._events.append(event)

    def events_on(self, day: str) -> list[CalendarEvent]:
        return sorted(
            (e for e in self._events if e.starts.startswith(day)),
            key=lambda e: (e.starts, e.provider_event_id),
        )
