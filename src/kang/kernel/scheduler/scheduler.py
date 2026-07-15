"""Scheduler — catch-up policies, quarantine, kill-switch (D014, 05 §11).

Layer: kernel/scheduler.
Constitutional home: 04_ARCHITECTURE D014 (catch-up on startup after
downtime: run_once_latest | run_all_missed | skip), 05_AGENTS §11
(quarantine at ≥3 consecutive failures; concurrency 1 — no second run while
one is in flight, trivially held by synchronous catch-up), 10_SECURITY D013
(kill-switch pauses all automation). The job body is an injected runner
(agent execution is M7); this module decides WHAT runs WHEN and records it.

Convergence (the C3 gate): the catch-up baseline is the last processed slot
(max job_run.started). Every slot that runs or is skipped leaves a row, so
re-running catch-up after a crash processes only the remaining slots —
idempotent, no double-execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from kang.domain.ports.clock import Clock
from kang.domain.ports.scheduler import Job, JobStore, KillSwitch
from kang.kernel.audit.service import AuditService
from kang.kernel.scheduler.schedule import parse_schedule

__all__ = ["CatchUpReport", "JobRunner", "Scheduler"]

QUARANTINE_THRESHOLD = 3  # consecutive failures (05 §11)

# Runs one job for one slot. Raises to signal failure (a failed body).
JobRunner = Callable[[Job, datetime], None]


@dataclass(frozen=True)
class CatchUpReport:
    """What a catch-up pass did — surfaced to the health panel + audit."""

    ran: int
    skipped: int
    failed: int
    quarantined: tuple[str, ...]
    paused: bool = False


class Scheduler:
    """Runs due work on startup and on tick, honoring catch-up policy."""

    def __init__(
        self,
        clock: Clock,
        job_store: JobStore,
        kill_switch: KillSwitch,
        runner: JobRunner,
        audit: AuditService,
        correlation_id: Callable[[], str],
    ) -> None:
        self._clock = clock
        self._jobs = job_store
        self._kill_switch = kill_switch
        self._runner = runner
        self._audit = audit
        self._correlation_id = correlation_id

    def catch_up(self) -> CatchUpReport:
        """Process every job's missed slots per its policy. First reconciles
        crashed runs, then — unless the kill-switch is engaged — dispatches."""
        now = self._clock.now()
        self._jobs.recover_incomplete(now)
        if self._kill_switch.is_engaged():
            self._audit.record("kernel:scheduler", "automation.paused", None)
            return CatchUpReport(
                ran=0, skipped=0, failed=0, quarantined=(), paused=True
            )

        totals = {"ran": 0, "skipped": 0, "failed": 0}
        quarantined: list[str] = []
        for job in self._jobs.list_jobs():
            if job.enabled and not job.quarantined:
                self._catch_up_job(job, now, totals, quarantined)
        return CatchUpReport(
            ran=totals["ran"],
            skipped=totals["skipped"],
            failed=totals["failed"],
            quarantined=tuple(quarantined),
        )

    def _catch_up_job(
        self, job: Job, now: datetime, totals: dict, quarantined: list[str]
    ) -> None:
        schedule = parse_schedule(job.schedule)
        baseline = self._jobs.last_slot(job.id) or job.created_at
        slots = schedule.occurrences_in(job.created_at, baseline, now)
        if not slots:
            return
        if job.catch_up == "skip":
            self._jobs.record_skipped(job.id, slots[-1])  # advance, run nothing
            totals["skipped"] += 1
            return
        to_run = [slots[-1]] if job.catch_up == "run_once_latest" else slots
        for slot in to_run:
            # Isolated failures don't stop the remaining slots; only reaching
            # the quarantine threshold does (05 §11: ≥3 consecutive).
            if self._run_slot(job, slot, totals, quarantined):
                break

    def _run_slot(
        self, job: Job, slot: datetime, totals: dict, quarantined: list[str]
    ) -> bool:
        """Run one slot. Return True iff this failure quarantined the job
        (the caller stops dispatching it)."""
        run_id = self._jobs.start_run(job.id, slot, self._correlation_id())
        try:
            self._runner(job, slot)
        except Exception as exc:  # a failed job body — supervised here
            self._jobs.finish_run(run_id, "failed", f"{type(exc).__name__}: {exc}")
            totals["failed"] += 1
            return self._maybe_quarantine(job, quarantined)
        self._jobs.finish_run(run_id, "ok", None)
        totals["ran"] += 1
        return False

    def _maybe_quarantine(self, job: Job, quarantined: list[str]) -> bool:
        """Quarantine the job if it has ≥3 consecutive failures (05 §11)."""
        if self._jobs.consecutive_failures(job.id) < QUARANTINE_THRESHOLD:
            return False
        self._jobs.set_quarantined(job.id, True)
        quarantined.append(job.id)
        self._audit.record("kernel:scheduler", "job.quarantined", {"job": job.id})
        return True
