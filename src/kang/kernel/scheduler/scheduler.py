"""Scheduler — catch-up policies, quarantine, kill-switch (D014, 05 §11).

Layer: kernel/scheduler.
Constitutional home: 04_ARCHITECTURE D014 (catch-up on startup after
downtime: run_once_latest | run_all_missed | skip), 05_AGENTS §11
(quarantine at ≥3 consecutive failures; concurrency 1 — no second run while
one is in flight, trivially held by synchronous catch-up), 10_SECURITY D013
(kill-switch pauses all automation). The job body is an injected runner
(agent execution is M7); this module decides WHAT runs WHEN and records it.

`job.timeout_s` gets a SOFT signal only (`_record_overrun_if_any`,
`job.overrun` audit action) — a post-hoc "this ran past its budget" report,
never enforcement. Real enforcement (interrupting an in-flight call) needs
a killable subprocess and its own IPC design; ruled not ripe while every
wired job is deterministic pure-SQL with no network/model calls to hang on
(a real design conversation's own conclusion, not a default).

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
from kang.domain.ports.schedule import ScheduleParser
from kang.domain.ports.scheduler import Job, JobStore, KillSwitch
from kang.kernel.audit.service import AuditService
from kang.kernel.scheduler.schedule import parse_schedule

__all__ = ["CatchUpReport", "JobRunner", "Scheduler", "SchedulerDeps"]

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


@dataclass(frozen=True)
class SchedulerDeps:
    """The Scheduler's collaborators (11 §4: beyond a few parameters, a
    dataclass).

    `parse` is injected rather than imported so wall-clock (`cron:`) dialects
    can live in `adapters/scheduler/` — `kernel → adapters` is forbidden
    (17 §4.2), and D014 placed cron parsing in the adapter. It defaults to
    the kernel's interval forms, so a Scheduler built without a wall-clock
    dialect behaves exactly as before (ADR-006).
    """

    clock: Clock
    job_store: JobStore
    kill_switch: KillSwitch
    runner: JobRunner
    audit: AuditService
    correlation_id: Callable[[], str]
    parse: ScheduleParser = parse_schedule


class Scheduler:
    """Runs due work on startup and on tick, honoring catch-up policy."""

    def __init__(self, deps: SchedulerDeps) -> None:
        self._clock = deps.clock
        self._jobs = deps.job_store
        self._kill_switch = deps.kill_switch
        self._runner = deps.runner
        self._audit = deps.audit
        self._correlation_id = deps.correlation_id
        self._parse = deps.parse

    def tick(self) -> CatchUpReport | None:
        """Re-run `catch_up()` from the live tick loop (ADR-019). `catch_up`
        is idempotent by construction (baseline = last processed slot), so
        calling it again mid-session is correct by construction, not a new
        scheduling algorithm — it only ever picks up newly-due slots.

        A failure `catch_up()` itself already isolates (a job body raising)
        never reaches here — `_run_slot` catches those per-slot. What can
        still escape is something catch_up() doesn't expect (e.g. a store
        error) — caught here, audited as `automation.tick_failed`, and
        swallowed: the tick loop must survive this and let the next tick
        retry, not take the whole Core down over what may be transient."""
        try:
            return self.catch_up()
        except Exception as exc:  # the tick loop must outlive this
            self._audit.record(
                "kernel:scheduler",
                "automation.tick_failed",
                {"error": f"{type(exc).__name__}: {exc}"},
            )
            return None

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
        schedule = self._parse(job.schedule)
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
        started_at = self._clock.now()
        try:
            self._runner(job, slot)
        except Exception as exc:  # a failed job body — supervised here
            self._record_overrun_if_any(job, started_at)
            self._jobs.finish_run(run_id, "failed", f"{type(exc).__name__}: {exc}")
            totals["failed"] += 1
            return self._maybe_quarantine(job, quarantined)
        self._record_overrun_if_any(job, started_at)
        self._jobs.finish_run(run_id, "ok", None)
        totals["ran"] += 1
        return False

    def _record_overrun_if_any(self, job: Job, started_at: datetime) -> None:
        """Soft, observability-only overrun signal (D014: "health status on
        the dashboard"). NOT enforcement — `job.timeout_s` names a budget
        nothing can actually interrupt yet: the runner call above is
        synchronous and blocking, Python cannot force-kill a thread, and
        Windows has no SIGALRM. Real enforcement would need the job body
        isolated in a killable subprocess with its own IPC back through the
        operation channel — real, separate infrastructure, not ripe while
        every wired job is deterministic pure-SQL with zero network/model
        calls (confirmed by reading `plan.generate`/`deadline.sweep`'s own
        handlers, not assumed). This only ever runs AFTER the call already
        returned (success or failure) — it reports a budget that was
        already blown, it does not enforce one."""
        elapsed_s = (self._clock.now() - started_at).total_seconds()
        if elapsed_s > job.timeout_s:
            self._audit.record(
                "kernel:scheduler",
                "job.overrun",
                {
                    "job": job.id,
                    "elapsed_s": round(elapsed_s, 3),
                    "timeout_s": job.timeout_s,
                },
            )

    def _maybe_quarantine(self, job: Job, quarantined: list[str]) -> bool:
        """Quarantine the job if it has ≥3 consecutive failures (05 §11)."""
        if self._jobs.consecutive_failures(job.id) < QUARANTINE_THRESHOLD:
            return False
        self._jobs.set_quarantined(job.id, True)
        quarantined.append(job.id)
        self._audit.record("kernel:scheduler", "job.quarantined", {"job": job.id})
        return True
