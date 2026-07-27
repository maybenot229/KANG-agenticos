"""Calendar port — read-only access to the cached calendar (M5 stub).

Layer: domain/ports. Ports own their datatypes (17 §7).
Constitutional home: 07_DATABASE §5.2 (`calendar_cache`, DERIVED — the
provider is the truth, 02_PRD §12), 18 §3 M5 ("calendar-read stub"),
05_AGENTS Appendix A (the planner holds `calendar.read`; `calendar.write` is
consequential and is v0.2, 02_PRD §15).

READ ONLY, deliberately. There is no write method and no sync method on this
port: calendar write is a consequential action arriving at v0.2 with its own
held-action path, and adding a write door now — even unused — would be an
authority path nobody reviewed (14_CLAUDE §8.2's spirit).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

__all__ = ["CalendarEvent", "CalendarStore"]


@dataclass(frozen=True)
class CalendarEvent:
    """One cached calendar event (07 §5.2's columns).

    `starts`/`ends` are ISO-8601 strings, mirroring the columns — the same
    reasoning as `Deadline.at`: a stated instant, not something to re-derive
    through a timezone-aware type on every read.
    """

    provider_event_id: str
    calendar_id: str
    starts: str
    fetched_at: str
    title: str | None = None
    ends: str | None = None
    all_day: bool = False


class CalendarStore(Protocol):
    """Read access to the calendar cache."""

    def events_on(self, day: str) -> list[CalendarEvent]:
        """Every cached event starting on `day` (an ISO date, `YYYY-MM-DD`),
        ordered `(starts, provider_event_id)` — a deterministic total order,
        so the same cache always yields the same plan (13 §2.6).

        An empty list is the honest answer when no provider is configured;
        it is never an error, and the Planner MUST render a plan without a
        calendar (NFR-002: the core loop works fully offline).
        """
        ...
