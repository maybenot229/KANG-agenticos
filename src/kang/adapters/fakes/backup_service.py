"""FakeBackupService — in-memory BackupService, contract-paired (13 §2.3).

Layer: adapters/fakes.
Constitutional home: 11_CODING §5/§7 (every port has an in-memory fake).

Models the two behaviours a caller can actually observe: a snapshot
returns a record, and a refused snapshot raises `BackupError` rather than
returning a partial one. It writes no files — the real adapter's
`VACUUM INTO`, manifest and retention are proven against a real database
in `integration/sqlite/test_backup_service.py`, not simulated here.
"""

from __future__ import annotations

from kang.domain.ports.backup import BackupError, SnapshotRecord

__all__ = ["FakeBackupService"]


class FakeBackupService:
    """BackupService over a list. `fail_with` makes the next call raise —
    the integrity-gate refusal path, without corrupting a database."""

    def __init__(self) -> None:
        self.taken: list[SnapshotRecord] = []
        self.fail_with: str | None = None

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
