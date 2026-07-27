"""Schedule port — the contract both schedule dialects satisfy.

Layer: domain/ports. Ports own their datatypes (17 §7).
Constitutional home: 04_ARCHITECTURE D014 (schedules are cron-like +
event-triggered; cron parsing lives in the adapter), ADR-006.

This contract exists in `domain/ports` rather than `kernel/scheduler`
because BOTH sides need it and neither may import the other: `adapters →
kernel` is forbidden and `kernel → adapters` is forbidden (17 §4.2), so the
cron adapter and the kernel's interval forms can only meet at the port line.
The kernel's existing interval `Schedule` already satisfies this Protocol
structurally — the contract is a description of what was already there, not
a new shape imposed on it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Protocol, runtime_checkable

__all__ = ["Schedule", "ScheduleError", "ScheduleParser"]


class ScheduleError(Exception):
    """The schedule string is not a form any registered dialect understands."""


@runtime_checkable
class Schedule(Protocol):
    """A set of firing instants, enumerable over a window."""

    @property
    def is_event_triggered(self) -> bool:
        """True for `event:{type}` schedules, which fire on the bus rather
        than the clock and therefore have no time grid."""
        ...

    def occurrences_in(
        self, anchor: datetime, after: datetime, until: datetime
    ) -> list[datetime]:
        """Firing instants strictly after `after` and at or before `until`,
        ascending, as aware UTC.

        `anchor` is the job's creation time. Interval dialects (`every:{s}`,
        `daily`) are anchored to it — their grid is relative. Wall-clock
        dialects (`cron:`) IGNORE it, because cron names absolute times; the
        parameter stays in the signature so one call site serves both
        (ADR-006: adding cron is a new implementation, not an interface
        change, which is what keeps `Scheduler._catch_up_job` and C3's
        catch-up convergence proof untouched).
        """
        ...


# Parses a schedule string into a Schedule, or raises ScheduleError. The
# composition root supplies one that understands every registered dialect.
ScheduleParser = Callable[[str], Schedule]
