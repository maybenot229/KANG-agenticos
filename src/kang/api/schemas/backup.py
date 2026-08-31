"""Request/response schemas for `backup.snapshot` (ADR-010 Ruling 1).

Layer: api.
Constitutional home: 07_DATABASE Part XII (the manifest fields this
response mirrors: "size, duration, integrity result, schema_version"),
05_AGENTS Appendix E (`backup.snapshot`, daily), ADR-031.

Added 2026-08-17 alongside the first caller `backup.py`'s mechanisms ever
had — they shipped at M1 and were never wired to the daily job the
module's own header promised "arrives with the scheduler at M3".
"""

from __future__ import annotations

from pydantic import BaseModel

__all__ = ["BackupSnapshotRequest", "BackupSnapshotResponse"]


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
