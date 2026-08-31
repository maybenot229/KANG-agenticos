"""SqliteBackupService — the daily snapshot policy over `backup.py`'s
mechanisms (ADR-031).

Layer: adapters/sqlite. Lives here, rather than in an `adapters/backup/`
of its own, because it builds on `backup.py`'s `vacuum_into` in this same
folder — and 17 §4.3.6 forbids cross-adapter imports, so a separate tech
folder would break the independence contract to gain nothing. The file
operations it also performs are stdlib `pathlib`/`shutil` on its own
snapshot outputs, not another adapter's territory.

Constitutional home: 07_DATABASE Part XII (the whole policy: integrity
gate, `VACUUM INTO`, manifest line, 30 daily + 12 monthly retention with
first-of-month promotion), 05_AGENTS Appendix E (`backup.snapshot`,
daily).

`backup.py` holds the mechanisms and stays policy-free; this holds the
policy and opens no connections of its own. Both connections are injected
— DB-001 keeps the write connection thread-confined, and taking a
snapshot must not smuggle in a second one.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

from kang.adapters.sqlite.backup import SnapshotError, vacuum_into
from kang.domain.ports.backup import BackupError, SnapshotRecord

__all__ = ["DAILY_KEPT", "MONTHLY_KEPT", "SqliteBackupService"]

DAILY_KEPT = 30  # 07 Part XII.2
MONTHLY_KEPT = 12  # 07 Part XII.2


class SqliteBackupService:
    """BackupService over %KANG_HOME%/backups/."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        eventlog: sqlite3.Connection,
        kang_home: Path,
    ) -> None:
        self._conn = connection
        self._eventlog = eventlog
        self._home = kang_home

    @property
    def _root(self) -> Path:
        return self._home / "backups"

    def take_snapshot(self, now: str) -> SnapshotRecord:
        day = now[:10].replace("-", "")  # YYYYMMDD from the ISO timestamp
        month = now[:7]  # YYYY-MM
        daily = self._root / "daily"
        try:
            # vacuum_into runs the integrity gate itself and refuses to
            # archive suspect state (07 Part XV F1) — not re-checked here,
            # so there is one gate, not two that could disagree.
            database = vacuum_into(self._conn, daily / f"kang-{day}.db")
            eventlog = vacuum_into(self._eventlog, daily / f"eventlog-{day}.db")
        except SnapshotError as exc:
            raise BackupError(str(exc)) from exc
        audit = self._copy_audit(month, day, daily)
        promoted = self._promote_monthly(database, month)
        total = sum(p.stat().st_size for p in (database, eventlog) if p.exists())
        record = SnapshotRecord(
            taken_at=now,
            database=str(database),
            eventlog=str(eventlog),
            audit=str(audit) if audit else None,
            bytes_total=total,
            duration_ms=0,  # stamped by the caller, which owns the clock
            integrity_ok=True,  # a failure raised above; see the port docstring
            schema_version=self._schema_version(),
            promoted_monthly=str(promoted) if promoted else None,
            pruned=self._prune(),
        )
        self._append_manifest(record)
        return record

    def _copy_audit(self, month: str, day: str, daily: Path) -> Path | None:
        """07 Part XII.1: "audit: current month file copy". Absent in a
        month with no audited action yet — reported as None, not invented
        as an empty file."""
        source = self._home / "audit" / f"{month}.jsonl"
        if not source.exists():
            return None
        target = daily / f"audit-{day}.jsonl"
        shutil.copy2(source, target)
        return target

    def _promote_monthly(self, database: Path, month: str) -> Path | None:
        """07 Part XII.2: "first snapshot of each month promoted". A copy,
        not a move — the daily retains its own retention clock."""
        target = self._root / "monthly" / f"kang-{month.replace('-', '')}.db"
        if target.exists():
            return None
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(database, target)
        return target

    def _schema_version(self) -> int:
        row = self._conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    def _append_manifest(self, record: SnapshotRecord) -> None:
        """One JSON line per snapshot (07 Part XII.1). Append-only, the
        same shape the audit log already uses — never rewritten."""
        self._root.mkdir(parents=True, exist_ok=True)
        line = json.dumps(
            {
                "taken_at": record.taken_at,
                "database": record.database,
                "eventlog": record.eventlog,
                "audit": record.audit,
                "bytes_total": record.bytes_total,
                "integrity_ok": record.integrity_ok,
                "schema_version": record.schema_version,
                "promoted_monthly": record.promoted_monthly,
                "pruned": list(record.pruned),
            },
            sort_keys=True,
        )
        with (self._root / "manifest.jsonl").open("a", encoding="utf-8") as sink:
            sink.write(line + "\n")

    def _prune(self) -> tuple[str, ...]:
        """Keep the newest 30 daily and 12 monthly (07 Part XII.2).

        Names sort chronologically by construction (`kang-YYYYMMDD.db`,
        `kang-YYYYMM.db`), so lexical order IS date order — no filesystem
        mtime is consulted, which would be wrong after a copy or restore.
        Daily grouping is per prefix so the kang/eventlog/audit families
        each keep their own 30 rather than competing for one budget."""
        removed: list[str] = []
        for prefix in ("kang-", "eventlog-", "audit-"):
            removed += _keep_newest(self._root / "daily", prefix, DAILY_KEPT)
        removed += _keep_newest(self._root / "monthly", "kang-", MONTHLY_KEPT)
        return tuple(removed)


def _keep_newest(directory: Path, prefix: str, keep: int) -> list[str]:
    if not directory.exists():
        return []
    matching = sorted(p for p in directory.iterdir() if p.name.startswith(prefix))
    doomed = matching[: max(0, len(matching) - keep)]
    for path in doomed:
        path.unlink()
    return [str(p) for p in doomed]
