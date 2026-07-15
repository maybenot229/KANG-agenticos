"""FakeJobStore + FakeKillSwitch — in-memory scheduler state (13 §2.3).

Layer: adapters/fakes.
Constitutional home: 11_CODING §5/§7 (every port has an in-memory fake).
Mirrors the sqlite semantics: last_slot = max started (any outcome);
consecutive_failures = trailing failed/timeout since last ok.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from kang.domain.ports.scheduler import Job, RunOutcome

__all__ = ["FakeJobStore", "FakeKillSwitch"]


@dataclass
class _Run:
    job_id: str
    slot: datetime
    outcome: RunOutcome | None
    finished: datetime | None


class FakeJobStore:
    """JobStore over lists."""

    def __init__(self, jobs: list[Job] | None = None, clock=None) -> None:
        self._jobs: dict[str, Job] = {j.id: j for j in (jobs or [])}
        self._runs: list[_Run] = []
        self._clock = clock

    def register_job(self, job: Job) -> None:
        self._jobs[job.id] = job

    # Back-compat alias used by some tests.
    add_job = register_job

    def list_jobs(self) -> list[Job]:
        return sorted(self._jobs.values(), key=lambda j: j.name)

    def last_slot(self, job_id: str) -> datetime | None:
        slots = [r.slot for r in self._runs if r.job_id == job_id]
        return max(slots) if slots else None

    def start_run(self, job_id: str, slot: datetime, correlation_id: str) -> int:
        self._runs.append(_Run(job_id=job_id, slot=slot, outcome=None, finished=None))
        return len(self._runs) - 1

    def finish_run(self, run_id: int, outcome: RunOutcome, detail: str | None) -> None:
        run = self._runs[run_id]
        run.outcome = outcome
        run.finished = self._clock.now() if self._clock else run.slot

    def record_skipped(self, job_id: str, slot: datetime) -> None:
        self._runs.append(
            _Run(job_id=job_id, slot=slot, outcome="skipped", finished=slot)
        )

    def consecutive_failures(self, job_id: str) -> int:
        count = 0
        for run in reversed(self._runs):
            if run.job_id != job_id or run.outcome is None:
                continue
            if run.outcome in ("failed", "timeout"):
                count += 1
            else:
                break
        return count

    def set_quarantined(self, job_id: str, quarantined: bool) -> None:
        self._jobs[job_id] = replace(self._jobs[job_id], quarantined=quarantined)

    def recover_incomplete(self, now: datetime) -> int:
        recovered = 0
        for run in self._runs:
            if run.finished is None:
                run.outcome = "failed"
                run.finished = now
                recovered += 1
        return recovered

    # test introspection
    def runs_for(self, job_id: str) -> list[_Run]:
        return [r for r in self._runs if r.job_id == job_id]


class FakeKillSwitch:
    """KillSwitch over a boolean."""

    def __init__(self) -> None:
        self._engaged = False
        self.reason = ""

    def is_engaged(self) -> bool:
        return self._engaged

    def engage(self, reason: str) -> None:
        self._engaged = True
        self.reason = reason

    def disengage(self) -> None:
        self._engaged = False
        self.reason = ""
