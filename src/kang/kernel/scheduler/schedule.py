"""Schedule parsing + occurrence enumeration — the catch-up substrate.

Layer: kernel/scheduler.
Constitutional home: 04_ARCHITECTURE D014 (schedules are cron-like +
event-triggered). The catch-up decision needs only "which slots fell in
(after, until]"; this module answers that on an interval grid anchored at
the job's creation. Full cron-expression parsing is deferred to the
Scheduler adapter (D014: "APScheduler ... may be used inside the adapter,
behind our Scheduler port") — the interval forms here are exact and
deterministic, which is what the catch-up policies and their tests need.

Supported: `every:{seconds}`, `daily` (86400s), `hourly` (3600s),
`event:{type}` (event-triggered — no time grid, empty occurrences).
"""

from __future__ import annotations

from datetime import datetime, timedelta

__all__ = ["Schedule", "ScheduleError", "parse_schedule"]

_NAMED_PERIODS = {"daily": 86400, "hourly": 3600, "minutely": 60}


class ScheduleError(Exception):
    """The schedule string is not a form this scheduler understands."""


class Schedule:
    """A time grid. `period_seconds` is None for event-triggered schedules,
    which have no time-based occurrences (they fire on the bus, not the
    clock)."""

    def __init__(self, raw: str, period_seconds: int | None) -> None:
        self.raw = raw
        self.period_seconds = period_seconds

    @property
    def is_event_triggered(self) -> bool:
        return self.period_seconds is None

    def occurrences_in(
        self, anchor: datetime, after: datetime, until: datetime
    ) -> list[datetime]:
        """Slot times strictly after `after` and at or before `until`, on the
        grid anchor + k·period (k ≥ 1). Empty for event-triggered schedules."""
        if self.period_seconds is None:
            return []
        period = timedelta(seconds=self.period_seconds)
        # First grid index strictly after `after`.
        elapsed = (after - anchor).total_seconds()
        start_k = max(1, int(elapsed // self.period_seconds) + 1)
        occurrences: list[datetime] = []
        slot = anchor + start_k * period
        while slot <= until:
            if slot > after:
                occurrences.append(slot)
            slot += period
        return occurrences


def parse_schedule(raw: str) -> Schedule:
    """Parse a schedule string into a Schedule."""
    text = raw.strip()
    if not text:
        raise ScheduleError("schedule must be non-empty")
    if text.startswith("event:"):
        return Schedule(text, period_seconds=None)
    if text in _NAMED_PERIODS:
        return Schedule(text, period_seconds=_NAMED_PERIODS[text])
    if text.startswith("every:"):
        value = text[len("every:") :]
        if not value.isdigit() or int(value) <= 0:
            raise ScheduleError(f"every:{value!r} needs a positive integer seconds")
        return Schedule(text, period_seconds=int(value))
    raise ScheduleError(
        f"unsupported schedule {raw!r}; use every:{{s}}, daily, hourly, "
        "or event:{type} (cron parsing lives in the adapter — D014)"
    )
