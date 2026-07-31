"""Cron schedules — the wall-clock dialect (ADR-006 Part A).

The claim under test is that Kang's actual routine is expressible and fires
at the right local instants: 05:45 Monday–Saturday, 06:45 Sunday, in
`Asia/Kuching`, with Saturday treated as a school day.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from kang.adapters.scheduler import parse_cron
from kang.domain.ports.schedule import Schedule, ScheduleError

KUCHING = ZoneInfo("Asia/Kuching")  # UTC+8, no DST
MORNING = "cron:45 5 * * 1-6 | 45 6 * * 0"
ANCHOR = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _local(year, month, day, hour, minute) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=KUCHING)


def _window(schedule, start_local, days: int):
    after = start_local.astimezone(timezone.utc)
    until = (start_local + timedelta(days=days)).astimezone(timezone.utc)
    return [
        m.astimezone(KUCHING) for m in schedule.occurrences_in(ANCHOR, after, until)
    ]


class TestContract:
    def test_a_cron_schedule_satisfies_the_port(self):
        assert isinstance(parse_cron(MORNING, KUCHING), Schedule)

    def test_it_is_not_event_triggered(self):
        assert parse_cron(MORNING, KUCHING).is_event_triggered is False

    def test_anchor_is_ignored_because_cron_is_absolute(self):
        """The interval dialects are anchor-relative; cron names absolute
        times. Two different anchors MUST give identical occurrences."""
        schedule = parse_cron(MORNING, KUCHING)
        after = _local(2026, 3, 2, 0, 0).astimezone(timezone.utc)
        until = _local(2026, 3, 4, 0, 0).astimezone(timezone.utc)
        far_anchor = datetime(2019, 7, 4, 13, 37, tzinfo=timezone.utc)
        assert schedule.occurrences_in(ANCHOR, after, until) == (
            schedule.occurrences_in(far_anchor, after, until)
        )


class TestKangsRoutine:
    def test_a_full_week_fires_seven_times(self):
        # Mon 2026-03-02 .. Sun 2026-03-08
        fired = _window(parse_cron(MORNING, KUCHING), _local(2026, 3, 2, 0, 0), 7)
        assert len(fired) == 7

    def test_school_days_fire_at_0545_local(self):
        fired = _window(parse_cron(MORNING, KUCHING), _local(2026, 3, 2, 0, 0), 6)
        assert all((m.hour, m.minute) == (5, 45) for m in fired), fired

    def test_saturday_is_a_school_day(self):
        saturday = _local(2026, 3, 7, 0, 0)
        assert saturday.weekday() == 5
        fired = _window(parse_cron(MORNING, KUCHING), saturday, 1)
        assert [(m.hour, m.minute) for m in fired] == [(5, 45)]

    def test_sunday_fires_at_0645_local(self):
        sunday = _local(2026, 3, 8, 0, 0)
        assert sunday.weekday() == 6
        fired = _window(parse_cron(MORNING, KUCHING), sunday, 1)
        assert [(m.hour, m.minute) for m in fired] == [(6, 45)]

    def test_occurrences_are_returned_as_utc(self):
        fired = parse_cron(MORNING, KUCHING).occurrences_in(
            ANCHOR,
            _local(2026, 3, 2, 0, 0).astimezone(timezone.utc),
            _local(2026, 3, 3, 0, 0).astimezone(timezone.utc),
        )
        # 05:45 Kuching (UTC+8) is 21:45 UTC the previous day
        assert fired[0].tzinfo is timezone.utc
        assert (fired[0].hour, fired[0].minute) == (21, 45)

    def test_the_timezone_actually_matters(self):
        """A different zone must move the firing instant — proving the
        schedule is not silently evaluated in UTC."""
        after = _local(2026, 3, 2, 0, 0).astimezone(timezone.utc)
        until = _local(2026, 3, 3, 0, 0).astimezone(timezone.utc)
        kuching = parse_cron(MORNING, KUCHING).occurrences_in(ANCHOR, after, until)
        utc = parse_cron(MORNING, ZoneInfo("UTC")).occurrences_in(ANCHOR, after, until)
        assert kuching != utc


class TestWindowSemantics:
    def test_after_is_exclusive_and_until_inclusive(self):
        schedule = parse_cron("cron:45 5 * * *", KUCHING)
        exact = _local(2026, 3, 2, 5, 45).astimezone(timezone.utc)
        # `after` == the firing instant ⇒ excluded
        assert schedule.occurrences_in(ANCHOR, exact, exact) == []
        # `until` == the firing instant ⇒ included
        just_before = exact - timedelta(minutes=1)
        assert schedule.occurrences_in(ANCHOR, just_before, exact) == [exact]

    def test_weeks_of_downtime_enumerate_every_missed_slot(self):
        """NFR-008: the catch-up window can be weeks. run_all_missed needs
        every slot, so enumeration must not silently cap."""
        fired = _window(parse_cron(MORNING, KUCHING), _local(2026, 3, 2, 0, 0), 28)
        assert len(fired) == 28


class TestParsing:
    def test_lists_ranges_and_steps(self):
        schedule = parse_cron("cron:0,30 * * * *", KUCHING)
        fired = _window(schedule, _local(2026, 3, 2, 0, 0), 1)
        assert len(fired) == 48  # twice an hour

    def test_step_syntax(self):
        schedule = parse_cron("cron:*/15 0 * * *", KUCHING)
        # start a minute before midnight so the 00:00 slot is inside the
        # window (`after` is exclusive) and the day's four slots are whole
        fired = _window(schedule, _local(2026, 3, 1, 23, 59), 1)
        assert [m.minute for m in fired[:4]] == [0, 15, 30, 45]

    @pytest.mark.parametrize(
        "raw",
        [
            "cron:",  # no expression
            "cron:45 5 * *",  # four fields
            "cron:45 5 * * * *",  # six fields
            "cron:99 5 * * *",  # minute out of range
            "cron:45 5 * * 9",  # weekday out of range
            "cron:x 5 * * *",  # not a number
            "cron:5-1 5 * * *",  # backwards range
            "cron:*/0 5 * * *",  # zero step
        ],
    )
    def test_malformed_expressions_are_refused(self, raw):
        # A schedule that parses into the wrong times is worse than one that
        # refuses to load — it fires at a moment nobody chose.
        with pytest.raises(ScheduleError):
            parse_cron(raw, KUCHING)

    def test_a_non_cron_string_is_refused(self):
        with pytest.raises(ScheduleError):
            parse_cron("hourly", KUCHING)
