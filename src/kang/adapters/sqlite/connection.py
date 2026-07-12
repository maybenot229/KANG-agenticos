"""SQLite connection opening — the DB-001 PRAGMA discipline, applied at open.

Layer: adapters/sqlite (the only home of SQL — DB-002).
Constitutional home: 07_DATABASE DB-001 (PRAGMAs set at open, verified;
drift = startup failure). M0 opens per-call connections for the store and
migration tests; the single-writer executor + read pool arrive at M1.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

__all__ = ["PragmaDriftError", "open_connection"]

_PRAGMAS = (
    ("journal_mode", "wal"),
    ("foreign_keys", "1"),
    ("busy_timeout", "5000"),
    ("temp_store", "2"),  # MEMORY
)


class PragmaDriftError(Exception):
    """A PRAGMA did not take effect — startup-blocking (DB-001)."""


def open_connection(db_path: Path | str) -> sqlite3.Connection:
    """Open kang.db (or a test copy) with the DB-001 PRAGMA set applied
    and verified. Explicit transactions only (isolation is manual)."""
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA temp_store = MEMORY")
    _verify(conn)
    return conn


def _verify(conn: sqlite3.Connection) -> None:
    checks = {
        "journal_mode": ("wal", "memory"),  # ':memory:' DBs report 'memory'
        "foreign_keys": ("1",),
        "busy_timeout": ("5000",),
        "temp_store": ("2",),
    }
    for pragma, accepted in checks.items():
        value = str(conn.execute(f"PRAGMA {pragma}").fetchone()[0]).lower()
        if value not in accepted:
            raise PragmaDriftError(
                f"PRAGMA {pragma} is {value!r}, expected one of {accepted} "
                "(DB-001: drift is a startup failure)"
            )
