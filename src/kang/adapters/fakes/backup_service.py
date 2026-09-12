"""FakeBackupService — in-memory BackupService, contract-paired (13 §2.3).

Layer: adapters/fakes.
Constitutional home: 11_CODING §5/§7 (every port has an in-memory fake).

Models the behaviours a caller can actually observe: a snapshot returns a
record, and a refused snapshot raises `BackupError` rather than returning
a partial one; a verify returns a record even when the check fails
(ADR-032 — a failed check IS the finding, not an exception), and raises
only when there is nothing to verify. It writes no files — the real
adapter's `VACUUM INTO`, manifest and retention are proven against a real
database in `integration/sqlite/test_backup_service.py`, not simulated
here.
"""

from __future__ import annotations

from kang.domain.ports.backup import (
    BackupError,
    BackupStatus,
    ExternalBackupStatus,
    SnapshotRecord,
    VerifyRecord,
    external_backup_is_stale,
)

__all__ = ["FakeBackupService"]


class FakeBackupService:
    """BackupService over a list. `fail_with` makes the next `take_snapshot`
    raise — the integrity-gate refusal path, without corrupting a
    database. `verify_result` lets a test hand back a specific
    `VerifyRecord` (including a failed one); `verify_fail_with` makes
    `verify_latest` raise instead, for the "nothing to verify" case."""

    def __init__(self) -> None:
        self.taken: list[SnapshotRecord] = []
        self.fail_with: str | None = None
        self.verified: list[VerifyRecord] = []
        self.verify_result: VerifyRecord | None = None
        self.verify_fail_with: str | None = None
        # ADR-034: set directly to simulate a marker's mtime — no real
        # file, unlike the real adapter's `Path.stat()`.
        self.external_marker_at: str | None = None

    def take_snapshot(self, now: str) -> SnapshotRecord:
        if self.fail_with is not None:
            raise BackupError(self.fail_with)
        day = now[:10].replace("-", "")
        record = SnapshotRecord(
            taken_at=now,
            database=f"backups/daily/kang-{day}.db",
            eventlog=f"backups/daily/eventlog-{day}.db",
            audit=f"backups/daily/audit-{day}.jsonl",
            bytes_total=4096,
            duration_ms=0,
            integrity_ok=True,
            schema_version=1,
            promoted_monthly=None,
            pruned=(),
        )
        self.taken.append(record)
        return record

    def verify_latest(self, now: str) -> VerifyRecord:
        if self.verify_fail_with is not None:
            raise BackupError(self.verify_fail_with)
        record = self.verify_result or VerifyRecord(
            verified_at=now,
            snapshot="backups/daily/kang-20260101.db",
            integrity_ok=True,
            read_shapes_checked=("v_active_deadlines", "v_today_tasks"),
            read_shapes_not_built=("v_project_memory", "v_contested_records"),
            read_shape_errors=(),
            live_row_counts={},
            snapshot_row_counts={},
            schema_version=1,
        )
        self.verified.append(record)
        return record

    def latest_status(self) -> BackupStatus:
        """ADR-033: mirrors the real adapter's "last line of each kind"
        semantics using the two lists this fake already keeps, in the
        order calls actually happened — not merely the last call to
        EITHER method, since a snapshot and a verify are independent
        histories."""
        last_verify = self.verified[-1] if self.verified else None
        return BackupStatus(
            last_snapshot_at=self.taken[-1].taken_at if self.taken else None,
            last_verify_at=last_verify.verified_at if last_verify else None,
            last_verify_ok=(
                last_verify.integrity_ok and last_verify.read_shapes_ok
                if last_verify
                else None
            ),
        )

    def external_backup_status(self, now: str) -> ExternalBackupStatus:
        """ADR-034: uses the shared pure function, so this fake cannot
        silently disagree with the real adapter about what "stale"
        means (13 §2.3)."""
        return ExternalBackupStatus(
            last_marker_at=self.external_marker_at,
            stale=external_backup_is_stale(self.external_marker_at, now),
        )
