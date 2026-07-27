"""SqliteCalendarStore — the calendar cache over kang.db (read-only).

Layer: adapters/sqlite (SQL confined here — DB-002; no SELECT *, 11 §13).
Constitutional home: 07_DATABASE §5.2 (`calendar_cache`), 18 §3 M5.

No write path by design — see the port's docstring.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from kang.domain.ports.calendar_store import CalendarEvent

__all__ = ["SqliteCalendarStore"]

_COLUMNS = (
    "provider_event_id, calendar_id, title, starts, ends, all_day, fetched_at"
)


def _row_to_event(row: sqlite3.Row | tuple) -> CalendarEvent:
    (
        provider_event_id,
        calendar_id,
        title,
        starts,
        ends,
        all_day,
        fetched_at,
    ) = row
    return CalendarEvent(
        provider_event_id=provider_event_id,
        calendar_id=calendar_id,
        title=title,
        starts=starts,
        ends=ends,
        all_day=bool(all_day),
        fetched_at=fetched_at,
    )


class SqliteCalendarStore:
    """CalendarStore implementation."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def events_on(self, day: str) -> list[CalendarEvent]:
        # `starts` is ISO-8601, so "on this day" is the half-open range
        # [day, day+1). A range keeps idx_calendar_starts usable, which a
        # substr() or LIKE comparison would not — and the index doctrine
        # (07 Part VI) means an index must actually serve its cited query.
        # Parsing `day` also rejects a malformed date here rather than
        # silently matching nothing.
        next_day = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM calendar_cache WHERE starts >= ? AND starts < ? "
            "ORDER BY starts, provider_event_id",
            (day, next_day),
        ).fetchall()
        return [_row_to_event(row) for row in rows]
