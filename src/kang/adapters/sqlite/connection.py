"""SQLite connection opening — the DB-001 PRAGMA discipline, applied at open.

Layer: adapters/sqlite (the only home of SQL — DB-002).
Constitutional home: 07_DATABASE DB-001 (PRAGMAs set at open, verified;
drift = startup failure). M0 opened per-call connections for the store and
migration tests; the single-writer executor + read pool arrived at M1 —
ADR-036 D3, `connection_pool.py` in this same package.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

__all__ = ["PragmaDriftError", "open_connection", "open_read_only_connection"]

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


def open_read_only_connection(db_path: Path | str) -> sqlite3.Connection:
    """Open one of DB-001's four read-only pool connections (ADR-036 D3):
    the same PRAGMA discipline as `open_connection`, plus `query_only =
    ON` — verified, not just set, matching this module's own drift
    standard — so an accidental write inside a "query"-kind operation
    fails loudly (`sqlite3.OperationalError`) instead of silently
    succeeding against a connection that was never supposed to write."""
    conn = open_connection(db_path)
    conn.execute("PRAGMA query_only = ON")
    value = str(conn.execute("PRAGMA query_only").fetchone()[0])
    if value != "1":
        raise PragmaDriftError(
            f"PRAGMA query_only is {value!r}, expected '1' "
            "(DB-001: drift is a startup failure)"
        )
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
