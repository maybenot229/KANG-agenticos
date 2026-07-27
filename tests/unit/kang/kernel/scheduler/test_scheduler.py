"""Scheduler catch-up policies, quarantine, kill-switch (D014, 05 §11, D013).

The three catch-up policies converge as specified after simulated downtime;
consecutive failures quarantine; the kill-switch pauses all automation.
Fault-injection convergence across a real restart is the C3 gate
(suites/replay/test_scheduler_catchup.py); this proves the policy logic.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from kang.adapters.fakes.audit_log import FakeAuditLog
from kang.adapters.fakes.job_store import FakeJobStore, FakeKillSwitch
from kang.domain.ports.scheduler import Job
from kang.kernel.audit.service import AuditService
from kang.kernel.scheduler.scheduler import QUARANTINE_THRESHOLD, Scheduler, SchedulerDeps

ANCHOR = datetime(2026, 1, 1, tzinfo=timezone.utc)


class MovableClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def set(self, now: datetime) -> None:
        self._now = now


def _job(policy: str, schedule: str = "hourly") -> Job:
    return Job(
        id=f"job-{policy}",
        name=f"job-{policy}",
        schedule=schedule,
        catch_up=policy,
        created_at=ANCHOR,
    )


def _scheduler(clock, job_store, kill_switch, runner):
    return Scheduler(
        SchedulerDeps(
            clock=clock,
            job_store=job_store,
            kill_switch=kill_switch,
            runner=runner,
            audit=AuditService(FakeAuditLog(), clock),
            correlation_id=lambda: "corr-sched",
        )
    )


def _run_at(hours: float, jobs, runner=None, kill_switch=None):
    clock = MovableClock(ANCHOR + timedelta(hours=hours))
    store = FakeJobStore(jobs=jobs, clock=clock)
    ran: list = []
    scheduler = _scheduler(
        clock,
        store,
        kill_switch or FakeKillSwitch(),
        runner or (lambda job, slot: ran.append((job.id, slot))),
    )
    report = scheduler.catch_up()
    return report, store, ran


def test_run_once_latest_runs_a_single_slot_after_downtime():
    # 5 hours of missed hourly slots ⇒ run exactly once (the latest).
    report, store, ran = _run_at(5, [_job("run_once_latest")])
    assert report.ran == 1
    assert len(ran) == 1
    assert ran[0][1] == ANCHOR + timedelta(hours=5)  # the latest slot


def test_run_all_missed_runs_every_slot():
    report, store, ran = _run_at(5, [_job("run_all_missed")])
    assert report.ran == 5
    assert [slot for _, slot in ran] == [
        ANCHOR + timedelta(hours=h) for h in (1, 2, 3, 4, 5)
    ]


def test_skip_runs_nothing_but_advances_the_baseline():
    report, store, ran = _run_at(5, [_job("skip")])
    assert report.ran == 0
    assert report.skipped == 1
    assert ran == []
    # baseline advanced to the latest slot ⇒ a second catch-up runs nothing
    assert store.last_slot("job-skip") == ANCHOR + timedelta(hours=5)


def test_catch_up_is_idempotent_when_rerun():
    jobs = [_job("run_all_missed")]
    clock = MovableClock(ANCHOR + timedelta(hours=3))
    store = FakeJobStore(jobs=jobs, clock=clock)
    ran: list = []
    scheduler = _scheduler(
        clock, store, FakeKillSwitch(), lambda job, slot: ran.append(slot)
    )
    scheduler.catch_up()
    scheduler.catch_up()  # second pass: no new slots
    assert len(ran) == 3


def test_event_triggered_jobs_are_not_time_dispatched():
    report, store, ran = _run_at(
        10, [_job("run_all_missed", schedule="event:task.created")]
    )
    assert report.ran == 0 and ran == []


def test_consecutive_failures_quarantine_the_job():
    calls = {"n": 0}

    def failing(job, slot):
        calls["n"] += 1
        raise RuntimeError("boom")

    # run_all_missed with >= 3 missed slots, each failing ⇒ quarantine.
    report, store, _ = _run_at(5, [_job("run_all_missed")], runner=failing)
    assert "job-run_all_missed" in report.quarantined
    assert store.list_jobs()[0].quarantined is True
    # fail-forward: stopped at the quarantine threshold, not all 5 slots
    assert calls["n"] == QUARANTINE_THRESHOLD


def test_quarantined_job_is_not_dispatched():
    job = Job(
        id="j",
        name="j",
        schedule="hourly",
        catch_up="run_all_missed",
        created_at=ANCHOR,
        quarantined=True,
    )
    report, store, ran = _run_at(5, [job])
    assert report.ran == 0 and ran == []


def test_disabled_job_is_not_dispatched():
    job = Job(
        id="j",
        name="j",
        schedule="hourly",
        catch_up="run_all_missed",
        created_at=ANCHOR,
        enabled=False,
    )
    report, store, ran = _run_at(5, [job])
    assert report.ran == 0 and ran == []


def test_kill_switch_pauses_all_automation():
    kill_switch = FakeKillSwitch()
    kill_switch.engage("Kang pulled the switch")
    report, store, ran = _run_at(5, [_job("run_all_missed")], kill_switch=kill_switch)
    assert report.paused is True
    assert report.ran == 0
    assert ran == []


def test_recover_incomplete_marks_crashed_runs_failed():
    clock = MovableClock(ANCHOR + timedelta(hours=2))
    store = FakeJobStore(jobs=[_job("run_all_missed")], clock=clock)
    # simulate a crashed run: started, never finished
    store.start_run("job-run_all_missed", ANCHOR + timedelta(hours=1), "c")
    scheduler = _scheduler(clock, store, FakeKillSwitch(), lambda job, slot: None)
    scheduler.catch_up()
    outcomes = [r.outcome for r in store.runs_for("job-run_all_missed")]
    assert "failed" in outcomes  # the crashed run was reconciled
