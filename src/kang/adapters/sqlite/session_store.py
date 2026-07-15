"""SqliteSessionStore — local session → principal resolution (API-003).

Layer: adapters/sqlite (SQL confined here — DB-002).
Constitutional home: 12_API API-003 (local sessions resolve to a principal;
the API refuses requests with no valid session). The session token itself
is a secret handed to first-party clients via the Core's session file
(readable only by Kang's OS account, SEC-011); it never appears in logs.
"""

from __future__ import annotations

import sqlite3

from kang.domain.ports.session import Session, SessionInvalid

__all__ = ["SqliteSessionStore"]


class SqliteSessionStore:
    """SessionStore over kang.db."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, session: Session) -> None:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._conn.execute(
                "INSERT INTO session (token, principal, first_party, created_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    session.token,
                    session.principal,
                    int(session.first_party),
                    session.created_at,
                ),
            )
            self._conn.execute("COMMIT")
        except sqlite3.Error:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise

    def resolve(self, token: str) -> Session:
        row = self._conn.execute(
            "SELECT token, principal, first_party, created_at FROM session "
            "WHERE token = ?",
            (token,),
        ).fetchone()
        if row is None:
            raise SessionInvalid("no live session for the presented token")
        return Session(
            token=row[0],
            principal=row[1],
            first_party=bool(row[2]),
            created_at=row[3],
        )
