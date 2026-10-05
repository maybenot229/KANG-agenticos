"""SQLite connection opening — the DB-001 PRAGMA discipline, applied at open.

Layer: adapters/sqlite (the only home of SQL — DB-002).
Constitutional home: 07_DATABASE DB-001 (PRAGMAs set at open, verified;
drift = startup failure). M0 opened per-call connections for the store and
migration tests; the single-writer executor + read pool arrived at M1 —
ADR-036 D3, `connection_pool.py` in this same package.

ADR-055 D3: every connection opened here also loads `sqlite-vec` and
verifies it answers `vec_version()` — the same drift standard as the
PRAGMAs. The vector-invalidation triggers (migration `0022`) touch `vec0`
tables whenever a memory row changes, so a connection that cannot see the
module cannot safely write `memory_record` at all; it is refused at open,
never discovered mid-transaction. Connections opened elsewhere on purpose
(the backup service's read-only snapshot probe) never touch a `vec0`
table, and `integrity_check`/`VACUUM INTO`/`ATTACH` do not need the module.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import sqlite_vec

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
    _load_vector_extension(conn)
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


def _load_vector_extension(conn: sqlite3.Connection) -> None:
    """ADR-055 D3: load `sqlite-vec`, then switch extension loading back
    off (nothing else may load native code through this connection), and
    verify the module answers."""
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
    except (sqlite3.Error, AttributeError) as exc:
        raise PragmaDriftError(
            f"sqlite-vec could not be loaded: {exc} (ADR-055 D3: a "
            "connection without vec0 is a startup failure)"
        ) from exc
    finally:
        conn.enable_load_extension(False)
    version = conn.execute("SELECT vec_version()").fetchone()[0]
    if not str(version).startswith("v0."):
        raise PragmaDriftError(
            f"sqlite-vec reports {version!r}, expected v0.x (ADR-055 D3)"
        )


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
