"""Transaction helpers shared by the memory-side stores (ADR-051 D3).

Layer: adapters/sqlite (SQL/transactions live here — DB-002).
Constitutional home: 07_DATABASE DB-001/DB-002 (every write is an explicit
`BEGIN IMMEDIATE` transaction), 15_EVENT_BUS EB-004 (the state commit runs
inside `bus.publish`).

A store write called alone opens (and commits) its own transaction; called
inside a `SqliteUnitOfWork.run`, it joins the one already open — so
`memory.approve` can insert the record and resolve the queue row atomically
without either store knowing about the other.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager

__all__ = ["SqliteUnitOfWork", "writing"]


@contextmanager
def writing(conn: sqlite3.Connection) -> Iterator[None]:
    """Join the caller's open transaction, or run one of our own."""
    if conn.in_transaction:
        yield
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


class SqliteUnitOfWork:
    """UnitOfWork over one kang.db connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def run(self, work: Callable[[], None]) -> None:
        with writing(self._conn):
            work()
