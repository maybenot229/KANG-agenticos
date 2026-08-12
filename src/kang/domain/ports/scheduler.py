"""Scheduler ports — jobs, run history, and the automation kill-switch.

Layer: domain/ports. Ports own their datatypes (17 §7).
Constitutional home: 04_ARCHITECTURE D014 (job rows; catch-up policies;
quarantine on repeated failure), 05_AGENTS §11 (catch_up ∈ run_once_latest |
run_all_missed | skip; `failure_count ≥ 3` ⇒ quarantine), 10_SECURITY D013
(kill-switch: one command pauses all automation).

A `job_run.started` is the SLOT time the run represents (07 wins over 04's
last_run/next_run prose): the last processed slot is `max(started)`, which
makes catch-up idempotent across restarts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

__all__ = [
    "CATCH_UP_POLICIES",
    "Job",
    "JobStore",
    "KillSwitch",
    "RunOutcome",
]

CATCH_UP_POLICIES = ("run_once_latest", "run_all_missed", "skip")
RunOutcome = str  # 'ok' | 'failed' | 'timeout' | 'skipped'


@dataclass(frozen=True)
class Job:
    """A scheduled job row (07 §5.5)."""

    id: str
    name: str
    schedule: str  # 'every:{s}' | 'daily' | 'hourly' | 'event:{type}'
    catch_up: str
    created_at: datetime
    enabled: bool = True
    timeout_s: int = 300
    quarantined: bool = False


class JobStore(Protocol):
    """Persistence for jobs and their run history."""

    def register_job(self, job: Job) -> None:
        """Insert or replace a job definition (idempotent by id). Jobs enter
        the store this way — from config/agent registration (D014)."""
        ...

    def list_jobs(self) -> list[Job]:
        """All jobs, name order (deterministic dispatch)."""
        ...

    def last_slot(self, job_id: str) -> datetime | None:
        """The latest slot already processed (max job_run.started, any
        outcome) — the catch-up baseline. None if never run."""
        ...

    def start_run(self, job_id: str, slot: datetime, correlation_id: str) -> int:
        """Record a run starting for `slot` (finished NULL). Returns run id."""
        ...

    def finish_run(self, run_id: int, outcome: RunOutcome, detail: str | None) -> None:
        """Complete a run with its outcome."""
        ...

    def record_skipped(self, job_id: str, slot: datetime) -> None:
        """Record a slot deliberately skipped (advances the baseline without
        running — the `skip` catch-up policy)."""
        ...

    def consecutive_failures(self, job_id: str) -> int:
        """Trailing failed/timeout runs since the last 'ok' (05 §11)."""
        ...

    def set_quarantined(self, job_id: str, quarantined: bool) -> None:
        """Quarantine (or release) a job."""
        ...

    def set_enabled(self, job_id: str, enabled: bool) -> None:
        """Enable or disable a job (ADR-021: `job.enable`/`job.disable`,
        05_AGENTS Appendix D's consequential pair — approved held actions
        only, never called directly)."""
        ...

    def set_enabled_in_txn(self, job_id: str, enabled: bool) -> None:
        """Same as `set_enabled`, transaction-participating — assumes the
        caller already opened a transaction on the shared connection
        (`held_action.approve`'s `transactional` commit_mode driver, ADR-021;
        mirrors `HeldActionStore.approve_in_txn`'s exact shape)."""
        ...

    def recover_incomplete(self, now: datetime) -> int:
        """Mark runs left unfinished by a crash (finished NULL) as failed,
        finishing them at `now`. Returns how many. Startup housekeeping so a
        crashed slot is accounted, not silently reprocessed forever."""
        ...


class KillSwitch(Protocol):
    """The automation kill-switch (D013): engaged ⇒ the scheduler runs
    nothing. Persisted so a paused system stays paused across restart."""

    def is_engaged(self) -> bool: ...

    def engage(self, reason: str) -> None: ...

    def disengage(self) -> None: ...
