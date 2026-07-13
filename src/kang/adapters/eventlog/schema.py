"""eventlog.db schema + connection — the 15 §5.2 DDL, verbatim.

Layer: adapters/eventlog (its own file, its own connection — 07 §1.2:
"append-heavy, independent retention/compaction, MUST survive/replay across
kang.db restores — coupling them would entangle recovery domains").
Constitutional home: 15_EVENT_BUS §5.2 (DDL adopted into 07 Part V);
DB-001 durability pairing (synchronous=FULL on its own connection — the
redo duty's price, paid knowingly, EB-003).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

__all__ = ["EventlogPragmaError", "open_eventlog"]

# 15 §5.2, verbatim. Index doctrine: every index cites its consumer.
_DDL = """
CREATE TABLE IF NOT EXISTS event (
  seq            INTEGER PRIMARY KEY,          -- single-writer monotonic
  event_id       TEXT NOT NULL UNIQUE,          -- UUIDv7
  type           TEXT NOT NULL,
  type_version   INTEGER NOT NULL DEFAULT 1,
  occurred_at    TEXT NOT NULL,
  recorded_at    TEXT NOT NULL,
  principal      TEXT NOT NULL,
  correlation_id TEXT NOT NULL,
  causation_id   TEXT,                          -- parent event_id, nullable
  entity_refs    TEXT NOT NULL,                 -- JSON array
  payload        TEXT NOT NULL,                 -- JSON, schema-validated
  provenance     TEXT NOT NULL CHECK (provenance IN
                   ('kang','derived','external_untrusted')),
  recovery_grade INTEGER NOT NULL DEFAULT 0,
  device_id      TEXT NOT NULL,
  state          TEXT NOT NULL DEFAULT 'pending' CHECK (state IN
                   ('pending','confirmed','orphaned'))
);
CREATE INDEX IF NOT EXISTS idx_event_type    ON event(type, seq);
                                             -- consumer: typed resume
CREATE INDEX IF NOT EXISTS idx_event_corr    ON event(correlation_id);
                                             -- consumer: explain chains
CREATE INDEX IF NOT EXISTS idx_event_pending ON event(state)
  WHERE state = 'pending';                   -- consumer: reconciliation

CREATE TABLE IF NOT EXISTS subscription_cursor (
  subscriber   TEXT PRIMARY KEY,
  last_seq     INTEGER NOT NULL DEFAULT 0,
  updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dead_letter (
  id           TEXT PRIMARY KEY,
  event_seq    INTEGER NOT NULL REFERENCES event(seq),
  subscriber   TEXT NOT NULL,
  attempts     INTEGER NOT NULL,
  last_error   TEXT NOT NULL,
  created_at   TEXT NOT NULL,
  resolved     TEXT CHECK (resolved IN ('redelivered','discarded')),
  resolved_at  TEXT
);
"""


class EventlogPragmaError(Exception):
    """A required PRAGMA did not take effect — startup-blocking (DB-001)."""


def open_eventlog(db_path: Path | str) -> sqlite3.Connection:
    """Open eventlog.db: own connection, synchronous=FULL (the write-ahead
    net must survive what kang.db is allowed to lose), schema applied
    idempotently."""
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = FULL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    synchronous = conn.execute("PRAGMA synchronous").fetchone()[0]
    if int(synchronous) != 2:  # 2 = FULL
        raise EventlogPragmaError(
            f"eventlog synchronous is {synchronous!r}, expected FULL (2) — "
            "the redo duty depends on it (EB-003, DB-001)"
        )
    conn.executescript(_DDL)
    return conn
