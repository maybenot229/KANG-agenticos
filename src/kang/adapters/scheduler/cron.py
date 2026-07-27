"""Cron schedules — the wall-clock dialect (ADR-006, discharging D014).

Layer: adapters/scheduler (the technology folder D014 anticipated: "cron
parsing lives in the adapter, behind our Scheduler port"). Imports only
`domain/ports` — `adapters → kernel` is forbidden (17 §4.2).

Form: `cron:{expr}` or `cron:{expr} | {expr} | …` — one or more standard
5-field expressions, `minute hour day-of-month month day-of-week`. A LIST is
supported because standard cron cannot express two different times on
different days in one expression, and a crontab solves that with two lines;
one `job` row holds one schedule string. Splitting the morning brief into two
job rows instead would give one ritual two independent catch-up baselines,
so downtime spanning Saturday into Sunday would generate the plan twice
(ADR-006 Part A, option A2, rejected for exactly this).

TIMEZONE. `Clock` returns aware UTC (its port says MUST), but cron names
local wall-clock times, so a timezone is required — not optional, not
defaulted. It is passed in from config rather than read from the host,
because a laptop opened in another country must not move Kang's morning
brief. Local→UTC resolution goes through `zoneinfo` rather than a fixed
offset so a future DST-observing timezone does not silently break.
ADR-006 does NOT rule on DST-ambiguous or skipped local times; `Asia/Kuching`
has no DST, and inventing a rule for an unreachable case would be guessing.

No dependency: D014 permits APScheduler inside this adapter, but a 5-field
matcher over a bounded window is small and exact, and E10 asks what a decade
of maintaining a dependency costs (ADR-006 Part A).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from kang.domain.ports.schedule import ScheduleError

__all__ = ["CRON_PREFIX", "CronSchedule", "parse_cron"]

CRON_PREFIX = "cron:"
_EXPR_SEPARATOR = "|"
_FIELD_COUNT = 5

# (name, low, high) per cron field, in expression order.
_FIELDS = (
    ("minute", 0, 59),
    ("hour", 0, 23),
    ("day of month", 1, 31),
    ("month", 1, 12),
    ("day of week", 0, 6),  # 0 = Sunday, standard cron
)


def _parse_field(raw: str, name: str, low: int, high: int) -> frozenset[int]:
    """Expand one cron field into the set of values it matches.

    Supports `*`, `N`, `a-b`, and a `/step` suffix on `*` or a range, each
    comma-separable — the subset of cron that is universally agreed on.
    Anything else raises rather than being silently ignored: a schedule that
    parses into the wrong times is worse than one that refuses to load.
    """
    values: set[int] = set()
    for part in raw.split(","):
        step = 1
        body = part
        if "/" in part:
            body, _, step_text = part.partition("/")
            if not step_text.isdigit() or int(step_text) < 1:
                raise ScheduleError(f"{name}: step in {part!r} must be a positive int")
            step = int(step_text)
        if body == "*":
            start, end = low, high
        elif "-" in body.lstrip("-"):
            start_text, _, end_text = body.partition("-")
            start, end = _to_int(start_text, name, part), _to_int(end_text, name, part)
        else:
            start = end = _to_int(body, name, part)
        if start > end:
            raise ScheduleError(f"{name}: range {part!r} runs backwards")
        if start < low or end > high:
            raise ScheduleError(f"{name}: {part!r} is outside {low}-{high}")
        values.update(range(start, end + 1, step))
    return frozenset(values)


def _to_int(text: str, name: str, part: str) -> int:
    if not text.isdigit():
        raise ScheduleError(f"{name}: {part!r} is not a number")
    return int(text)


class _Expression:
    """One parsed 5-field cron expression."""

    def __init__(self, raw: str) -> None:
        fields = raw.split()
        if len(fields) != _FIELD_COUNT:
            raise ScheduleError(
                f"cron expression {raw!r} needs {_FIELD_COUNT} fields "
                "(minute hour day-of-month month day-of-week), got "
                f"{len(fields)}"
            )
        self.raw = raw
        self.minute, self.hour, self.day, self.month, self.weekday = (
            _parse_field(text, name, low, high)
            for text, (name, low, high) in zip(fields, _FIELDS)
        )

    def matches(self, moment: datetime) -> bool:
        """Whether a LOCAL wall-clock minute satisfies this expression.

        Day-of-month and day-of-week are OR-ed when both are restricted —
        standard cron's long-standing (and genuinely surprising) rule, which
        is honoured here rather than quietly simplified, because a schedule
        that behaves differently from every other cron would be worse than
        one that is merely odd.
        """
        # Python: Monday is 0, Sunday is 6. Cron: Sunday is 0.
        cron_weekday = (moment.weekday() + 1) % 7
        if moment.minute not in self.minute or moment.hour not in self.hour:
            return False
        if moment.month not in self.month:
            return False
        day_restricted = len(self.day) < 31
        weekday_restricted = len(self.weekday) < 7
        day_hit = moment.day in self.day
        weekday_hit = cron_weekday in self.weekday
        if day_restricted and weekday_restricted:
            return day_hit or weekday_hit
        return day_hit and weekday_hit


class CronSchedule:
    """A wall-clock schedule: the union of one or more cron expressions."""

    def __init__(self, raw: str, expressions: list[_Expression], tz: ZoneInfo) -> None:
        self.raw = raw
        self._expressions = expressions
        self._tz = tz

    @property
    def is_event_triggered(self) -> bool:
        return False

    def occurrences_in(
        self, anchor: datetime, after: datetime, until: datetime
    ) -> list[datetime]:
        """Firing instants in (after, until], ascending, as aware UTC.

        `anchor` is ignored: cron names absolute times (see the port).

        Walks the window minute by minute in local time. Exact and obviously
        correct, and bounded by the window — even "weeks of neglect"
        (NFR-008) is tens of thousands of cheap comparisons, which is the
        right trade against a cleverer search that could be subtly wrong
        about a DST boundary or a month end.
        """
        if not self._expressions:
            return []
        local_end = until.astimezone(self._tz)
        moment = (after.astimezone(self._tz) + timedelta(minutes=1)).replace(
            second=0, microsecond=0
        )
        occurrences: list[datetime] = []
        while moment <= local_end:
            if any(expression.matches(moment) for expression in self._expressions):
                instant = moment.astimezone(timezone.utc)
                if instant > after:
                    occurrences.append(instant)
            moment += timedelta(minutes=1)
        return occurrences


def parse_cron(raw: str, tz: ZoneInfo) -> CronSchedule:
    """Parse `cron:{expr}[ | {expr}…]`. Raises ScheduleError on anything
    malformed — a schedule is refused at load rather than firing at a time
    nobody intended."""
    if not raw.startswith(CRON_PREFIX):
        raise ScheduleError(f"{raw!r} is not a {CRON_PREFIX} schedule")
    body = raw[len(CRON_PREFIX) :].strip()
    if not body:
        raise ScheduleError("cron schedule needs at least one expression")
    expressions = [
        _Expression(part.strip())
        for part in body.split(_EXPR_SEPARATOR)
        if part.strip()
    ]
    if not expressions:
        raise ScheduleError("cron schedule needs at least one expression")
    return CronSchedule(raw, expressions, tz)
