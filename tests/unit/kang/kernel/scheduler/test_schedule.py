"""Schedule parsing + occurrence enumeration (D014 catch-up substrate)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from kang.kernel.scheduler.schedule import ScheduleError, parse_schedule

ANCHOR = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _at(hours: float) -> datetime:
    return ANCHOR + timedelta(hours=hours)


def test_parses_named_and_interval_forms():
    assert parse_schedule("hourly").period_seconds == 3600
    assert parse_schedule("daily").period_seconds == 86400
    assert parse_schedule("every:900").period_seconds == 900


def test_event_schedule_is_event_triggered():
    schedule = parse_schedule("event:task.created")
    assert schedule.is_event_triggered
    assert schedule.occurrences_in(ANCHOR, ANCHOR, _at(100)) == []


def test_unsupported_schedule_raises():
    with pytest.raises(ScheduleError):
        parse_schedule("0 6 * * *")  # cron proper → adapter's job (D014)
    with pytest.raises(ScheduleError):
        parse_schedule("every:0")


def test_occurrences_on_the_grid():
    hourly = parse_schedule("hourly")
    # from anchor, slots at +1h..+3h within (anchor, anchor+3h]
    occ = hourly.occurrences_in(ANCHOR, ANCHOR, _at(3))
    assert occ == [_at(1), _at(2), _at(3)]


def test_occurrences_are_strictly_after_baseline():
    hourly = parse_schedule("hourly")
    # baseline at +1h ⇒ next slots +2h, +3h (not +1h again)
    occ = hourly.occurrences_in(ANCHOR, _at(1), _at(3))
    assert occ == [_at(2), _at(3)]


def test_no_occurrences_when_no_full_period_elapsed():
    hourly = parse_schedule("hourly")
    assert hourly.occurrences_in(ANCHOR, ANCHOR, _at(0.5)) == []


def test_downtime_produces_all_missed_slots():
    hourly = parse_schedule("hourly")
    # created at anchor, last processed at +1h, now +5h ⇒ 4 missed
    occ = hourly.occurrences_in(ANCHOR, _at(1), _at(5))
    assert occ == [_at(2), _at(3), _at(4), _at(5)]
