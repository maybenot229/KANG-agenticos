"""kang.db backup mechanics — VACUUM INTO snapshots + integrity checks.

Layer: adapters/sqlite.
Constitutional home: 07_DATABASE Part XII ("VACUUM INTO produces a
consistent, defragmented, WAL-independent copy while the DB stays live.
It is the only sanctioned backup method. File-copying a live WAL database
is forbidden."); Part XV F1 (integrity_check before snapshot; on failure,
freeze — never snapshot suspect state). The scheduled daily job (02:30)
arrives with the scheduler at M3; these are its mechanisms.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

__all__ = ["IntegrityReport", "SnapshotError", "integrity_check", "vacuum_into"]


class SnapshotError(Exception):
    """The snapshot could not be taken safely. Never silently partial."""


@dataclass(frozen=True)
class IntegrityReport:
    ok: bool
    findings: tuple[str, ...]


def integrity_check(conn: sqlite3.Connection) -> IntegrityReport:
    """PRAGMA integrity_check, full. 'ok' or the loud list of findings.

    Severe corruption makes SQLite raise instead of report — translated
    here into the same typed, visible result (11 §9), never re-hidden."""
    try:
        rows = [str(row[0]) for row in conn.execute("PRAGMA integrity_check")]
    except sqlite3.DatabaseError as exc:
        return IntegrityReport(ok=False, findings=(f"integrity_check raised: {exc}",))
    ok = rows == ["ok"]
    return IntegrityReport(ok=ok, findings=() if ok else tuple(rows))


def vacuum_into(conn: sqlite3.Connection, destination: Path) -> Path:
    """Snapshot the live database into `destination` (07 Part XII.1):
    integrity gate first — a suspect database is frozen, not archived."""
    report = integrity_check(conn)
    if not report.ok:
        raise SnapshotError(
            "integrity_check failed; refusing to snapshot suspect state "
            f"(07 Part XV F1): {report.findings[:3]}"
        )
    if destination.exists():
        raise SnapshotError(f"snapshot target already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # VACUUM INTO cannot be parameterized; the path is caller-controlled
    # config, quoted for SQLite's single-quote rules.
    quoted = str(destination).replace("'", "''")
    conn.execute(f"VACUUM INTO '{quoted}'")
    return destination
