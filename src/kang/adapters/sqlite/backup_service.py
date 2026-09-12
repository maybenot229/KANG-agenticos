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

from kang.adapters.sqlite.backup import SnapshotError, integrity_check, vacuum_into
from kang.adapters.sqlite.deadline_store import SqliteDeadlineStore
from kang.adapters.sqlite.task_store import SqliteTaskStore
from kang.domain.ports.backup import (
    BackupError,
    BackupStatus,
    SnapshotRecord,
    VerifyRecord,
)
from kang.domain.ports.clock import Clock

__all__ = ["DAILY_KEPT", "MONTHLY_KEPT", "ROW_COUNT_TABLES", "SqliteBackupService"]

DAILY_KEPT = 30  # 07 Part XII.2
MONTHLY_KEPT = 12  # 07 Part XII.2

# ADR-032 D2: reported for verify's row-count comparison, never gated —
# every table `_Stores` wires (composition.py), excluding session/
# idempotency_key/schema_version, which measure nothing about churn.
ROW_COUNT_TABLES = (
    "task",
    "deadline",
    "held_action",
    "job",
    "project",
    "competition",
    "milestone",
    "goal",
    "notification",
)

# ADR-032 D1: the named-query suite is the two read shapes that actually
# have an implementation. v_project_memory/v_contested_records are named
# in 07 §4.1 but Memory (domain/memory/) is `__all__: []` — Phase 2 — so
# there is nothing to run yet; reported as not-built, never silently
# skipped.
_READ_SHAPES_NOT_BUILT = ("v_project_memory", "v_contested_records")


class SqliteBackupService:
    """BackupService over %KANG_HOME%/backups/."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        eventlog: sqlite3.Connection,
        kang_home: Path,
        clock: Clock,
    ) -> None:
        self._conn = connection
        self._eventlog = eventlog
        self._home = kang_home
        # Needed only to satisfy SqliteDeadlineStore/SqliteTaskStore's own
        # constructor for verify_latest's read-shape checks (ADR-032 D1) —
        # both read methods called here (.active()/.plannable()) never
        # touch it. Injected rather than constructed here: a second
        # adapter tech folder (os_windows.clock) may not be imported from
        # this one (17 §4.3.6's independence contract) — the composition
        # root already owns a real Clock and is the one place permitted
        # to hand it across.
        self._clock = clock

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
        self._append_manifest(
            "snapshot",
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
        )
        return record

    def verify_latest(self, now: str) -> VerifyRecord:
        daily = self._root / "daily"
        candidates = sorted(
            p for p in daily.glob("kang-*.db") if p.name.startswith("kang-")
        )
        if not candidates:
            raise BackupError("no daily snapshot exists to verify")
        snapshot = candidates[-1]  # lexical order is date order (see _prune)

        # A genuinely read-only connection (07 Part XII.3: "open latest
        # snapshot READ-ONLY") — NOT open_connection(), which sets
        # PRAGMA journal_mode=WAL and would write -wal/-shm files next to
        # a snapshot that is supposed to stay exactly what VACUUM INTO
        # produced.
        conn = sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)
        try:
            integrity = integrity_check(conn)
            shapes_ok, errors = self._check_read_shapes(conn)
            snapshot_counts = _row_counts(conn)
            schema_version = _schema_version_of(conn)
        finally:
            conn.close()

        record = VerifyRecord(
            verified_at=now,
            snapshot=str(snapshot),
            integrity_ok=integrity.ok,
            read_shapes_checked=shapes_ok,
            read_shapes_not_built=_READ_SHAPES_NOT_BUILT,
            read_shape_errors=errors,
            live_row_counts=_row_counts(self._conn),
            snapshot_row_counts=snapshot_counts,
            schema_version=schema_version,
        )
        self._append_manifest(
            "verify",
            {
                "verified_at": record.verified_at,
                "snapshot": record.snapshot,
                "integrity_ok": record.integrity_ok,
                "read_shapes_checked": list(record.read_shapes_checked),
                "read_shapes_not_built": list(record.read_shapes_not_built),
                "read_shape_errors": list(record.read_shape_errors),
                "live_row_counts": record.live_row_counts,
                "snapshot_row_counts": record.snapshot_row_counts,
                "schema_version": record.schema_version,
            },
        )
        return record

    def latest_status(self) -> BackupStatus:
        """ADR-033: linear scan, matching the "boring by construction"
        standard already applied to a manifest this size (ADR-031's own
        "at today's scale... effectively instantaneous" reasoning). No
        manifest at all — a fresh Core — is the same as an empty one, not
        an error: both fields stay `None`."""
        manifest = self._root / "manifest.jsonl"
        if not manifest.exists():
            return BackupStatus(
                last_snapshot_at=None, last_verify_at=None, last_verify_ok=None
            )
        last_snapshot: dict | None = None
        last_verify: dict | None = None
        for line in manifest.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            if entry.get("kind") == "snapshot":
                last_snapshot = entry
            elif entry.get("kind") == "verify":
                last_verify = entry
        return BackupStatus(
            last_snapshot_at=last_snapshot["taken_at"] if last_snapshot else None,
            last_verify_at=last_verify["verified_at"] if last_verify else None,
            last_verify_ok=(
                last_verify["integrity_ok"] and not last_verify["read_shape_errors"]
                if last_verify
                else None
            ),
        )

    def _check_read_shapes(
        self, snapshot_conn: sqlite3.Connection
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """ADR-032 D1: run the two named read shapes that actually exist
        against the snapshot connection, using the REAL production store
        classes — not a hand-duplicated query — so this proves the actual
        read path works, not a copy of it that could silently drift."""
        checked: list[str] = []
        errors: list[str] = []
        for name, call in (
            (
                "v_active_deadlines",
                lambda: SqliteDeadlineStore(snapshot_conn, self._clock).active(),
            ),
            (
                "v_today_tasks",
                lambda: SqliteTaskStore(snapshot_conn, self._clock).plannable(),
            ),
        ):
            checked.append(name)
            try:
                call()
            except sqlite3.Error as exc:
                errors.append(f"{name}: {exc}")
        return tuple(checked), tuple(errors)

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
        return _schema_version_of(self._conn)

    def _append_manifest(self, kind: str, fields: dict) -> None:
        """One JSON line per run (07 Part XII.1), `snapshot` or `verify`
        (ADR-032) — append-only, the same shape the audit log already
        uses, never rewritten. `kind` is what lets a reader (and
        `test_backup_service.py`) tell the two apart in one file rather
        than needing a second manifest."""
        self._root.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"kind": kind, **fields}, sort_keys=True)
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


def _row_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """ADR-032 D2: a plain `COUNT(*)` per table in `ROW_COUNT_TABLES`,
    reported as data — see the module-level constant's own comment for
    why no pass/fail tolerance is applied here."""
    return {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ROW_COUNT_TABLES
    }


def _schema_version_of(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _keep_newest(directory: Path, prefix: str, keep: int) -> list[str]:
    if not directory.exists():
        return []
    matching = sorted(p for p in directory.iterdir() if p.name.startswith(prefix))
    doomed = matching[: max(0, len(matching) - keep)]
    for path in doomed:
        path.unlink()
    return [str(p) for p in doomed]
