"""Request/response schemas for `system.health` (ADR-010 Ruling 1).

Layer: api.
Constitutional home: 09_UI §12 ("Health: the metrics surface (D015 +
07_DATABASE Part 17): job statuses, backup age + last restore-
verification result, index parity, integrity-incident counter").

Added 2026-08-05: scoped to job statuses + the automation kill-switch
only — `JobStore.list_jobs()`/`.consecutive_failures()` and
`KillSwitch.is_engaged()` already existed. Backup age, restore-
verification, index parity, and the integrity-incident counter were NOT
in this response — no port/store exposed them yet, and inventing that
tracking then (rather than exposing something that already exists, the
`deadline.list`/`audit.list` pattern this session has followed
throughout) would have been new domain surface, not API-layer exposure.

Backup age + last restore-verification result joined 2026-09-12
(ADR-033), once `BackupService.latest_status()` existed to read
(`backups/manifest.jsonl`, ADR-031/032) — the same pure-exposure pattern
the rest of this response already followed. Index parity and the
integrity-incident counter remain the open, honestly-named gap.

A fifth field — off-machine backup evidence (07 Part XII.5) — joined
2026-09-13 (ADR-034). 09_UI §12's own four-field list does not name it,
but Part XII.5 assigns the health panel exactly this warning; ADR-034
records that as a doc gap, not a reason to omit the field.
"""

from __future__ import annotations

from pydantic import BaseModel

__all__ = [
    "JobStatus",
    "SystemHealthRequest",
    "SystemHealthResponse",
]


class SystemHealthRequest(BaseModel):
    """`system.health` params (operations.py::make_system_health_handler).
    No fields: the handler takes none, mirroring `DeadlineSweepRequest`."""


class JobStatus(BaseModel):
    """One scheduled job's status — `Job`'s fields (`domain/ports/
    scheduler.py`) plus its trailing failure count
    (`JobStore.consecutive_failures`), the number ADR-006/05_AGENTS §11's
    quarantine-at-3 threshold is measured against."""

    id: str
    name: str
    schedule: str
    catch_up: str
    enabled: bool
    quarantined: bool
    consecutive_failures: int


class SystemHealthResponse(BaseModel):
    """`system.health` result: every registered job's status plus whether
    automation is globally paused (D013's kill-switch, `KillSwitch.
    is_engaged()`). `jobs` is empty whenever the scheduler never wired
    (07 F8: missing/invalid `kang.toml` fails closed to no automation) —
    an honest empty list, not an error, since job_store itself always
    constructs regardless of scheduler wiring (2026-08-05).

    `last_snapshot_at`/`last_verify_at` (ADR-033) are raw ISO-8601
    timestamps, not precomputed ages — matching every other timestamp
    this API serves; the client ages them, same as it already must for
    `task.created_at`/`deadline.at`. All three backup fields are `None`
    together when no snapshot has ever run, and `last_verify_at`/
    `last_verify_ok` alone are `None` when a snapshot exists but no
    verify has run yet — two genuinely different "nothing yet" states,
    not collapsed into one. `last_verify_ok` is the check's `integrity_ok`
    AND `read_shapes_ok` together (ADR-032) — a clean integrity check
    with a broken read shape is still a failed restore-test by 07 Part
    XII.3's own standard, and reporting integrity alone would drop that
    half of the finding.

    `external_backup_marker_at`/`external_backup_stale` (ADR-034) answer
    a different question from the three backup fields above: not
    whether KANG's own on-machine snapshot succeeded, but whether Kang
    has ever moved a copy off this machine (07 Part XII.5). Read live on
    every call, same as `last_snapshot_at`/`last_verify_at` — not a
    cached result of the weekly `backup_offsite_check` job, which governs
    only how often the `attention` notification fires."""

    jobs: list[JobStatus]
    automation_engaged: bool
    last_snapshot_at: str | None
    last_verify_at: str | None
    last_verify_ok: bool | None
    external_backup_marker_at: str | None
    external_backup_stale: bool
