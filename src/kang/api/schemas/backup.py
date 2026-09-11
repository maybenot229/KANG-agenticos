"""Request/response schemas for `backup.snapshot`/`backup.verify`
(ADR-010 Ruling 1).

Layer: api.
Constitutional home: 07_DATABASE Part XII (the manifest fields
`BackupSnapshotResponse` mirrors: "size, duration, integrity result,
schema_version"; Part XII.3, the restore-test `BackupVerifyResponse`
mirrors), 05_AGENTS Appendix E (`backup.snapshot`/`.verify`, daily/
monthly), ADR-031, ADR-032.

Added 2026-08-17 alongside the first caller `backup.py`'s mechanisms ever
had — they shipped at M1 and were never wired to the daily job the
module's own header promised "arrives with the scheduler at M3". Verify
followed on 2026-09-11 (ADR-032), closing Part XII.3's own "a backup
that hasn't been restore-tested is treated as nonexistent."
"""

from __future__ import annotations

from pydantic import BaseModel

__all__ = [
    "BackupSnapshotRequest",
    "BackupSnapshotResponse",
    "BackupVerifyRequest",
    "BackupVerifyResponse",
]


class BackupSnapshotRequest(BaseModel):
    """`backup.snapshot` params — no fields, mirroring
    `DeadlineSweepRequest`/`HeldActionExpireRequest`'s shape: a sweep-like
    maintenance command takes no arguments."""


class BackupSnapshotResponse(BaseModel):
    """The manifest line this run wrote, returned verbatim.

    `integrity_ok` is always True on a success: a failed integrity check
    raises rather than returning a record (07 Part XV F1 — suspect state
    is frozen, never archived), so the field records which gate was
    passed rather than reporting a result that could be False here."""

    database: str
    eventlog: str
    audit: str | None
    bytes_total: int
    integrity_ok: bool
    schema_version: int
    promoted_monthly: str | None
    pruned: list[str]


class BackupVerifyRequest(BaseModel):
    """`backup.verify` params — no fields, same shape as
    `BackupSnapshotRequest`."""


class BackupVerifyResponse(BaseModel):
    """The verify manifest line this run wrote (ADR-032), returned
    verbatim.

    Unlike `BackupSnapshotResponse`, `integrity_ok` CAN be False here — a
    corrupted snapshot is exactly the finding this operation exists to
    surface (05_AGENTS Appendix A: "alert on any failure — no silent
    skip, ever"), not something the handler refuses to report.

    `read_shapes_not_built` names the two views 07 §4.1 lists that have
    no implementation (Memory is Phase 2), so a caller reads "2 of 4
    checked" rather than mistaking an incomplete suite for a passed one.
    `live_row_counts`/`snapshot_row_counts` are reported, never gated —
    07 Part XII.3's own "±expected churn" has no defined tolerance
    anywhere (ADR-032 D2)."""

    snapshot: str
    integrity_ok: bool
    read_shapes_checked: list[str]
    read_shapes_not_built: list[str]
    read_shape_errors: list[str]
    live_row_counts: dict[str, int]
    snapshot_row_counts: dict[str, int]
    schema_version: int
