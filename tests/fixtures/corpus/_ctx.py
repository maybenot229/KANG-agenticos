"""Shared generation context: seeded randomness, ids, timelines, and the
chunked writer (ADR-049 D2/D4).

Raw parameterized SQL with explicit column lists, at most 1,000 rows per
transaction (07 DB-002). The connection is opened with isolation_level=None
(`open_connection`), so this module owns every transaction boundary.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from random import Random

from kang.adapters.fakes.clock import FakeClock
from kang.kernel.runtime.ids import uuid7

from .profiles import SECOND_DEVICE_SHARE, Profile
from .text import Vocabulary

CHUNK_ROWS = 1000  # DB-002: bulk jobs chunk into <=1000-row transactions
CORPUS_START = datetime(2016, 1, 1, tzinfo=timezone.utc)


class Weighted:
    """(value, weight) pairs sampled with cumulative weights."""

    def __init__(self, pairs: Sequence[tuple[object, int]]) -> None:
        self.values = [v for v, _ in pairs]
        total = 0
        self.cum: list[int] = []
        for _, weight in pairs:
            total += weight
            self.cum.append(total)

    def pick(self, rng: Random):
        return rng.choices(self.values, cum_weights=self.cum)[0]


def iso(moment: datetime) -> str:
    """07 DB-003 timestamp: YYYY-MM-DDTHH:MM:SS.mmmZ (UTC)."""
    return moment.isoformat(timespec="milliseconds")[:-6] + "Z"


@dataclass
class Ctx:
    conn: sqlite3.Connection
    rng: Random
    vocab: Vocabulary
    profile: Profile
    devices: tuple[str, str] = ("dev-corpus-primary", "dev-corpus-second")
    # Ids and facts the later tables' links and FKs need.
    goal_ids: list[str] = field(default_factory=list)
    project_ids: list[str] = field(default_factory=list)
    competition_ids: list[str] = field(default_factory=list)
    conversation_ids: list[str] = field(default_factory=list)
    note_paths: list[str] = field(default_factory=list)
    memory_ids: list[str] = field(default_factory=list)
    memory_types: list[str] = field(default_factory=list)
    memory_statuses: list[str] = field(default_factory=list)
    episode_ids: list[str] = field(default_factory=list)
    # (src, dst, type) rows the indexer will derive from FK columns.
    fk_edges: list[tuple[str, str, str]] = field(default_factory=list)

    def new_id(self, moment: datetime) -> str:
        return uuid7(int(moment.timestamp() * 1000), self.rng.randbytes)

    def device(self) -> str:
        return self.devices[1 if self.rng.random() < SECOND_DEVICE_SHARE else 0]

    def timeline(self, count: int, span_days: int | None = None) -> Iterator[datetime]:
        """`count` strictly increasing instants across the profile's span,
        stepped by an injected FakeClock (deterministic, never wall time)."""
        span = span_days if span_days is not None else self.profile.span_days
        clock = FakeClock(CORPUS_START)
        step = span * 86400 / max(count, 1)
        for _ in range(count):
            clock.advance(step * self.rng.uniform(0.5, 1.5))
            yield clock.now()

    def flush(self, statements: Sequence[tuple[str, Sequence[tuple]]]) -> None:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            for sql, rows in statements:
                self.conn.executemany(sql, rows)
            self.conn.execute("COMMIT")
        except sqlite3.Error:
            if self.conn.in_transaction:
                self.conn.execute("ROLLBACK")
            raise

    def write(self, sql: str, rows: Iterable[tuple]) -> None:
        batch: list[tuple] = []
        for row in rows:
            batch.append(row)
            if len(batch) == CHUNK_ROWS:
                self.flush([(sql, batch)])
                batch = []
        if batch:
            self.flush([(sql, batch)])


def later(moment: datetime, seconds: float) -> datetime:
    return moment + timedelta(seconds=seconds)
