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

HONEST LIMIT (07 Part XII.3, restated because it bounds what this port
can claim): "A backup that hasn't been restore-tested is treated as
nonexistent." This port produces snapshots that are taken, recorded and
pruned. The monthly verification job that would make them *backups* is
deferred (ADR-031 D3) — until it exists, nothing may report that KANG
has backups on the strength of this port alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

__all__ = ["BackupError", "BackupService", "SnapshotRecord"]


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


class BackupService(Protocol):
    """Takes and records snapshots per 07_DATABASE Part XII."""

    def take_snapshot(self, now: str) -> SnapshotRecord:
        """Snapshot the database and its event log, copy the current-month
        audit file, append a manifest line, then apply retention.

        Raises `BackupError` if the integrity gate fails or a target
        already exists — never returns a partial record.
        """
        ...
