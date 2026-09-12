"""Backup port — daily snapshots as a contract, not a script (ADR-031).

Layer: domain/ports. Ports own their datatypes (17 §7).
Constitutional home: 07_DATABASE Part XII (`VACUUM INTO` is the only
sanctioned backup method; integrity gate before snapshot; daily snapshot
recorded in a manifest; retention 30 daily + 12 monthly), 05_AGENTS
Appendix E (`backup.snapshot`, daily).

The service takes a snapshot and reports what it did; it does NOT decide
when — that is the scheduler's (ADR-006), and the operation the job
invokes is `backup.snapshot` (12_API). Refusing to snapshot suspect state
is the implementation's duty, not the caller's: a failed integrity check
raises rather than returning a record, so a caller cannot mistake a
refusal for a success (07 Part XV F1).

HONEST LIMIT (07 Part XII.3), now half-closed by `verify_latest`
(ADR-032): "A backup that hasn't been restore-tested is treated as
nonexistent." `verify_latest` opens the latest daily snapshot read-only,
integrity-checks it, and exercises the two named read shapes that
actually exist in code (`v_active_deadlines`/`v_today_tasks` —
`v_project_memory`/`v_contested_records` have no implementation; Memory
is Phase 2). Row counts vs. live are reported, never gated — 07 Part
XII.3's own "±expected churn" has no number anywhere in the constitution,
and this port does not invent one (ADR-032 D2).

`latest_status` (ADR-033) is the read half `system.health` (09_UI §12)
needs — "backup age + last restore-verification result" — and is
deliberately the only method here with no clock parameter: it reads what
already happened, it does not stamp anything new.

`external_backup_status` (ADR-034) answers a genuinely different
question from every method above: not "did KANG's own on-machine
snapshot succeed," but "has Kang ever moved a copy off this machine" (07
Part XII.5 — "KANG's own duty ends at `backups/`"). The marker path is
bound at construction, like the backups directory itself, not passed per
call — it never changes within a Core's lifetime.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

__all__ = [
    "BackupError",
    "BackupService",
    "BackupStatus",
    "EXTERNAL_BACKUP_STALE_AFTER",
    "ExternalBackupStatus",
    "SnapshotRecord",
    "VerifyRecord",
    "external_backup_is_stale",
]

# ADR-034 D2: Part XII.5 names "(weekly)" once, for the panel's warning
# cadence — read directly as the staleness threshold too, rather than
# inventing a second, undocumented number for "how old is too old."
EXTERNAL_BACKUP_STALE_AFTER = timedelta(days=7)


def external_backup_is_stale(last_marker_at: str | None, now: str) -> bool:
    """Shared by every `BackupService` implementation (ADR-034 D3), so the
    real adapter and the fake cannot silently disagree about what "stale"
    means (13 §2.3). No marker ever configured or touched reads as stale
    by the same honest reasoning a missing `backups/manifest.jsonl` reads
    as "no backup yet" elsewhere on this port — not an error, and not
    treated differently from a marker that once existed and aged out."""
    if last_marker_at is None:
        return True
    return (
        datetime.fromisoformat(now) - datetime.fromisoformat(last_marker_at)
        > EXTERNAL_BACKUP_STALE_AFTER
    )


class BackupError(Exception):
    """A snapshot could not be taken safely. Never silently partial."""


@dataclass(frozen=True)
class SnapshotRecord:
    """One manifest entry (07 Part XII.1: "size, duration, integrity
    result, schema_version"), plus the paths written and whatever
    retention removed in the same pass."""

    taken_at: str  # ISO-8601, from the injected clock (11 §25)
    database: str  # the kang.db snapshot path
    eventlog: str  # the eventlog.db snapshot path — NOT optional; DB-001's
    #   durability pairing restores by replaying the event log for
    #   post-snapshot Tier-1 effects, so a database snapshot without its
    #   event log is a restore that silently loses the recovery window
    audit: str | None  # the copied current-month audit file, or None when
    #   no audit file exists yet for this month
    bytes_total: int
    duration_ms: int
    integrity_ok: bool  # always True on a returned record — a failed check
    #   raises BackupError instead (see the module docstring)
    schema_version: int
    promoted_monthly: str | None  # the monthly path, when this snapshot was
    #   the first of its month (07 Part XII.2's promotion)
    pruned: tuple[str, ...]  # paths retention removed in this pass


@dataclass(frozen=True)
class VerifyRecord:
    """One verify manifest entry (ADR-032). Unlike `SnapshotRecord`, a
    failed check is a normal, returned result — not an exception. A
    corrupted snapshot or a broken read shape IS the finding this exists
    to surface (05_AGENTS Appendix A: "alert on any failure — no silent
    skip, ever"), so it must reach the caller, not be swallowed as a
    raise. `BackupError` is reserved for "nothing to verify" — a
    structurally different condition from "checked and failed"."""

    verified_at: str  # ISO-8601, from the injected clock
    snapshot: str  # which daily snapshot was opened
    integrity_ok: bool
    read_shapes_checked: tuple[str, ...]  # names of the shapes actually run
    read_shapes_not_built: tuple[str, ...]  # named views with no
    #   implementation yet (v_project_memory/v_contested_records — Memory
    #   is Phase 2), reported so "2/4" never reads as "passed"
    read_shape_errors: tuple[str, ...]  # empty when every checked shape
    #   returned without raising
    live_row_counts: dict[str, int]
    snapshot_row_counts: dict[str, int]
    schema_version: int

    @property
    def read_shapes_ok(self) -> bool:
        return not self.read_shape_errors


@dataclass(frozen=True)
class BackupStatus:
    """The read half of the port (ADR-033) — what `system.health` (09_UI
    §12) needs: "backup age + last restore-verification result". Both
    halves are `None` when that kind of run has never happened; not an
    error, since a fresh Core genuinely has no backup history yet."""

    last_snapshot_at: str | None  # most recent "kind": "snapshot" line's
    #   taken_at — raw timestamp, not a precomputed age (matching every
    #   other timestamp this API serves; the client ages it, same as it
    #   already must for task.created_at/deadline.at/etc.)
    last_verify_at: str | None  # most recent "kind": "verify" line's
    #   verified_at
    last_verify_ok: bool | None  # that line's integrity_ok AND (not
    #   read_shape_errors) — a clean integrity check with a broken read
    #   shape is still a failed restore-test by 07 Part XII.3's own
    #   standard ("every view returns"); integrity_ok alone would drop
    #   that half of the finding


@dataclass(frozen=True)
class ExternalBackupStatus:
    """07 Part XII.5's off-machine evidence (ADR-034) — read from a
    Kang-configured marker file's mtime, NOT `backups/manifest.jsonl`
    (which records KANG's own on-machine snapshots, not what happened to
    them afterward). `last_marker_at` is `None` when Kang has never
    configured a marker path, or the configured path does not exist yet
    — the same honest "no evidence" outcome either way; KANG cannot
    force an off-machine copy to exist (07 Part XII.5: "it can refuse to
    let it be forgotten")."""

    last_marker_at: str | None
    stale: bool


class BackupService(Protocol):
    """Takes, records, and verifies snapshots per 07_DATABASE Part XII."""

    def take_snapshot(self, now: str) -> SnapshotRecord:
        """Snapshot the database and its event log, copy the current-month
        audit file, append a manifest line, then apply retention.

        Raises `BackupError` if the integrity gate fails or a target
        already exists — never returns a partial record.
        """
        ...

    def verify_latest(self, now: str) -> VerifyRecord:
        """Restore-test the most recent daily snapshot (ADR-032): open it
        read-only, integrity-check it, exercise the read shapes that
        exist today, and report row counts against the live database.

        Raises `BackupError` only when there is no daily snapshot to
        verify at all — a failed check is a returned `VerifyRecord`, not
        an exception (see that dataclass's own docstring)."""
        ...

    def latest_status(self) -> BackupStatus:
        """The most recent snapshot and verify entries (ADR-033) — pure
        read, opens no `kang.db` connection, touches nothing, never
        raises. No manifest at all is the same as an empty one: both
        halves of the returned `BackupStatus` are `None`."""
        ...

    def external_backup_status(self, now: str) -> ExternalBackupStatus:
        """07 Part XII.5's off-machine evidence (ADR-034): the
        Kang-configured marker's mtime, and whether it is older than
        `EXTERNAL_BACKUP_STALE_AFTER`. Never raises — an unconfigured or
        missing marker is a normal, honest `stale=True` result, not an
        error."""
        ...
