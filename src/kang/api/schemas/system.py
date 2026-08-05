"""Request/response schemas for `system.health` (ADR-010 Ruling 1).

Layer: api.
Constitutional home: 09_UI §12 ("Health: the metrics surface (D015 +
07_DATABASE Part 17): job statuses, backup age + last restore-
verification result, index parity, integrity-incident counter").

Added 2026-08-05: scoped to job statuses + the automation kill-switch
only — `JobStore.list_jobs()`/`.consecutive_failures()` and
`KillSwitch.is_engaged()` already existed. Backup age, restore-
verification, index parity, and the integrity-incident counter are NOT
in this response — no port/store exposes them yet, and inventing that
tracking now (rather than exposing something that already exists, the
`deadline.list`/`audit.list` pattern this session has followed
throughout) would be new domain surface, not API-layer exposure. Named
as a real, open gap, not silently completed.
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
    constructs regardless of scheduler wiring (2026-08-05)."""

    jobs: list[JobStatus]
    automation_engaged: bool
