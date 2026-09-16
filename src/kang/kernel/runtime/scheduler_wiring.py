"""Scheduler wiring — the composition root's scheduler-specific slice
(ADR-023).

Layer: kernel/runtime, exempt from the import matrix exactly as
`composition.py` is (17 §4.3's composition-root exception, extended here
by ADR-023 — registered by name in `tools/importlinter.toml`, both files
together forming one conceptual composition root, not two).

Split out of `composition.py` when the third scheduled job (ADR-022)
pushed that file past the size lint's hard limits (both the file itself
and `_wire_scheduler`'s own line count) — a mechanical reason, not a new
concept. `composition.py` still owns `build_core`/`serve`/`Core` and
calls into `_wire_scheduler`/`_tick_forever` here exactly as it called
its own private functions before.

Also imports `kang.agents.runtime.executor` as of ADR-043 (2026-09-16) —
`AGENT_ROUTED_JOBS`' own dispatch through `run_mechanical_agent`. Legal
only here, under the same composition-root exemption already covering
`kang.adapters`/`kang.api`, extended to `kang.agents` by a matching
`tools/importlinter.toml` entry added in that ADR's own PR (17 §4.4: a
new legitimate import earns a contract entry, not a workaround).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from kang.adapters.config.planner_config import (
    PlannerConfigError,
    load_planner_triggers,
)
from kang.adapters.scheduler import CRON_PREFIX, parse_cron
from kang.agents.runtime.executor import ExecutorDeps, run_mechanical_agent
from kang.api.dispatch import ApiRequest, Dispatcher
from kang.domain.ports.scheduler import Job
from kang.domain.ports.session import Session
from kang.kernel.audit.service import AuditService
from kang.kernel.orchestrator.registry import AgentRegistry
from kang.kernel.scheduler.schedule import parse_schedule
from kang.kernel.scheduler.scheduler import Scheduler, SchedulerDeps

__all__ = [
    "AGENT_ROUTED_JOBS",
    "BACKUP_OFFSITE_CHECK_JOB",
    "BACKUP_SNAPSHOT_JOB",
    "BACKUP_VERIFY_JOB",
    "DEADLINE_SWEEP_JOB",
    "HELD_ACTION_EXPIRE_JOB",
    "JOB_OPERATIONS",
    "MORNING_PLAN_JOB",
    "SCHEDULER_PRINCIPAL",
    "TICK_INTERVAL_S",
    "_SchedulerWiring",
    "_make_job_runner",
    "_make_schedule_parser",
    "_tick_forever",
    "_wire_scheduler",
]

SCHEDULER_PRINCIPAL = "kernel:scheduler"  # dispatches jobs (already audits
#   under this name — ADR-006 names nothing new)
MORNING_PLAN_JOB = "morning_plan"  # 05 Appendix E's ritual name
DEADLINE_SWEEP_JOB = "deadline_sweep"  # 05 Appendix E's ritual name (ADR-020)
HELD_ACTION_EXPIRE_JOB = "held_action_expire"  # ADR-022
BACKUP_SNAPSHOT_JOB = "backup_snapshot"  # 05 Appendix E name (ADR-031)
BACKUP_VERIFY_JOB = "backup_verify"  # 05 Appendix E name (ADR-032)
BACKUP_OFFSITE_CHECK_JOB = "backup_offsite_check"  # ADR-034 — Appendix E
#   itemizes no job for this (ADR-034's own Context section); named to
#   match the existing backup.* family, not invented from nothing.

TICK_INTERVAL_S = 60  # ADR-019: how often the live tick re-runs catch-up.
# A plain constant, not a kang.toml key — nothing has asked to tune this
# yet, unlike [planner.triggers]'s lived trigger times. Read directly by
# asyncio.sleep() since ADR-036 D4 — no clock-based gating needed anymore
# (that existed only because http.server's service_actions() polled on
# its own schedule; a native asyncio task just sleeps for the interval).

# Which registry operation each job runs (ADR-006 Part B, ruling 4). The
# `job` table has no `operation` column and job names are ritual names
# (`morning_plan`), not operation names (`plan.generate`) — 05 Appendix E is
# explicit about that — so the mapping has to live somewhere. Here: the one
# module permitted to know both layers. It stays a plain literal because
# SEC-005 forbids hidden execution and P5 asks that "what will KANG do next
# and why" be answerable by reading, not by tracing.
JOB_OPERATIONS: dict[str, str] = {
    "morning_plan": "plan.generate",
    "deadline_sweep": "deadline.sweep",  # ADR-020
    "held_action_expire": "held_action.expire",  # ADR-022
    "backup_snapshot": "backup.snapshot",  # ADR-031
    "backup_verify": "backup.verify",  # ADR-032
    "backup_offsite_check": "backup.offsite_check",  # ADR-034
}

# ADR-043/045: jobs whose real scheduled trigger runs through the
# mechanical-agent envelope (agents/runtime/executor.py::
# run_mechanical_agent) instead of a direct kernel:scheduler dispatch —
# a named, reviewable job-name -> agent-id MAPPING, never inferred from
# a job name happening to match a real agent id. `deadline_sweep`'s own
# job name and agent id happen to be the same string (coincidence, not
# a mechanism this map relies on) — `backup_monitor` runs three
# differently-named jobs, which is why this is a dict, not a set
# (ADR-045's own finding: ADR-043's frozenset couldn't express "which
# agent" once job name and agent id stopped being the same string).
# `morning_plan`'s real cognitive counterpart (`planner`) is out of
# scope for the mechanical-only executor (03_ROADMAP Phase 1);
# `held_action_expire` names no agent in Appendix A's catalog at all —
# both stay off this map for the same reason ADR-043 gave.
AGENT_ROUTED_JOBS: dict[str, str] = {
    DEADLINE_SWEEP_JOB: "deadline_sweep",
    BACKUP_SNAPSHOT_JOB: "backup_monitor",
    BACKUP_VERIFY_JOB: "backup_monitor",
    BACKUP_OFFSITE_CHECK_JOB: "backup_monitor",
}


def _make_schedule_parser(tz: ZoneInfo):
    """Parse any registered dialect: wall-clock `cron:` from the adapter,
    interval forms from the kernel. The composite lives here because it is
    the only place that may import both (17 §4.2 forbids kernel↔adapters in
    either direction) — ADR-006 Part A."""

    def parse(raw: str):
        if raw.startswith(CRON_PREFIX):
            return parse_cron(raw, tz)
        return parse_schedule(raw)

    return parse


def _make_job_runner(
    dispatcher: Dispatcher, sessions, new_id, clock, agent_registry: AgentRegistry
):
    """The job→operation seam (ADR-006 Part B).

    Jobs dispatch through the SAME pipeline a UI command takes, so scheduled
    work is permission-checked, idempotency-keyed, invocation-recorded and
    audited exactly once, by one path (12 §5). That is what lets
    `explain.invocation` reconstruct why a job acted — which matters most
    for the actions Kang did not watch happen (12 §12).

    A job in `AGENT_ROUTED_JOBS` (ADR-043) runs through `run_mechanical_
    agent` instead of dispatching directly — the session is then minted
    for principal `agent:{id}`, not `kernel:scheduler`, by the executor
    itself. Every other job keeps the original direct-dispatch shape
    below, session minted here for principal `kernel:scheduler` with
    **first_party=False**. That is a feature, not a limitation either
    way: per ADR-002 first-party means "arrived out-of-band through
    Kang's own UI", so a job (or an agent acting for one) is structurally
    incapable of approving a held action — SEC-003 enforced by
    construction rather than by remembering. Do NOT "fix" this by minting
    first-party sessions for jobs; that hands automation the power to
    approve its own consequences.
    """

    def dispatch(
        operation: str, params: dict, session_token: str, idempotency_key: str | None
    ) -> dict:
        return dispatcher.dispatch(
            ApiRequest(
                operation=operation,
                params=params,
                session_token=session_token,
                idempotency_key=idempotency_key,
            )
        )

    executor_deps = ExecutorDeps(
        dispatch=dispatch, sessions=sessions, new_id=new_id, clock=clock
    )

    def run(job: Job, slot: datetime) -> None:
        operation = JOB_OPERATIONS.get(job.name)
        if operation is None:
            raise KeyError(
                f"job {job.name!r} has no registered operation — a scheduled "
                "job that runs nothing is a wiring defect, not a no-op"
            )
        # Deterministic per (job, slot): a replayed slot returns the
        # cached outcome instead of re-executing (API-004). Defence in
        # depth — the durable guard is the job_run baseline, since
        # API-004 keys are retained only 7 days.
        idempotency_key = f"job:{job.id}:{slot.isoformat()}"

        if job.name in AGENT_ROUTED_JOBS:
            response = _run_via_agent_envelope(
                job, operation, idempotency_key, agent_registry, executor_deps
            )
        else:
            response = _run_via_direct_dispatch(
                slot, operation, idempotency_key, dispatch, sessions, new_id
            )

        if not response.get("ok"):
            # Raising is what the Scheduler counts as a failed slot, which is
            # what drives retry/quarantine (05 §11). Swallowing it here would
            # make a broken job look healthy forever.
            raise RuntimeError(
                f"job {job.name} → {operation} failed: {response.get('error')}"
            )

    return run


def _run_via_agent_envelope(
    job: Job,
    operation: str,
    idempotency_key: str,
    agent_registry: AgentRegistry,
    executor_deps: ExecutorDeps,
) -> dict:
    """ADR-043/045: a job in `AGENT_ROUTED_JOBS` runs through
    `run_mechanical_agent`, looked up via that dict's own job-name ->
    agent-id mapping (never the job name itself past ADR-045 — see
    that map's own docstring) — split out of `_make_job_runner`'s own
    closure purely to keep that function under the size lint's line
    limit (11 §4), not a domain concept of its own."""
    agent_id = AGENT_ROUTED_JOBS[job.name]
    agent = agent_registry.get(agent_id)
    if agent is None:
        raise KeyError(
            f"job {job.name!r} maps to agent {agent_id!r} in "
            "AGENT_ROUTED_JOBS, but no such agent exists in the "
            "AgentRegistry — a wiring defect, not a runtime condition "
            "to degrade past"
        )
    return run_mechanical_agent(
        agent, operation, {}, executor_deps, idempotency_key=idempotency_key
    ).response


def _run_via_direct_dispatch(
    slot: datetime,
    operation: str,
    idempotency_key: str,
    dispatch,
    sessions,
    new_id,
) -> dict:
    """The original, pre-ADR-043 shape: every job outside
    `AGENT_ROUTED_JOBS` still mints its own session for principal
    `kernel:scheduler` and dispatches directly — split out of
    `_make_job_runner`'s own closure for the same size-lint reason as
    its sibling above."""
    session = Session(
        token=new_id(),
        principal=SCHEDULER_PRINCIPAL,
        first_party=False,  # a job is not Kang's hand (ADR-002)
        created_at=slot.isoformat(),
    )
    sessions.create(session)
    return dispatch(operation, {}, session.token, idempotency_key)


@dataclass(frozen=True)
class _SchedulerWiring:
    """What the scheduler needs from the already-built Core (11 §4)."""

    kang_home: object
    connection: object
    clock: object
    audit: AuditService
    dispatcher: Dispatcher
    sessions: object
    new_id: object
    job_store: object
    kill_switch: object
    agent_registry: AgentRegistry  # ADR-043: AGENT_ROUTED_JOBS' own lookup


def _wire_scheduler(wiring: _SchedulerWiring):
    """Join the scheduler to the Core and register its jobs (ADR-006).

    Trigger times come from `kang.toml`, converted to a cron-list by the
    config object — never hardcoded here (05 Appendix E: config, not spec).
    `register_job` is insert-or-replace, so startup re-registration is
    idempotent and an edited config takes effect on the next boot.

    Missing or invalid config FAILS CLOSED to no automation rather than
    refusing to boot — the 07 F8 shape, which does the same for
    `permissions.toml`. ADR-006 said "fail fast", and the point it was making
    stands: never *invent* a timezone or a trigger time, because an invented
    schedule fires at a moment nobody chose. But declining to schedule is not
    the same as declining to run. Bricking the whole Core over a missing
    optional file would take Kang's manual use of the system down with the
    automation, which is a worse failure than automation being off and said
    so out loud (SEC-009: fail visibly, and degrade specifically).

    `job_store`/`kill_switch` are passed in, constructed once in
    `build_core` (2026-08-05) rather than here — the System-domain Health
    view (09_UI §12) needs them regardless of whether this function
    reaches its `return None` below.
    """
    try:
        triggers = load_planner_triggers(wiring.kang_home / "config" / "kang.toml")
    except PlannerConfigError as exc:
        wiring.audit.record(
            SCHEDULER_PRINCIPAL, "automation.unconfigured", {"reason": str(exc)}
        )
        return None
    job_store = wiring.job_store
    _register_scheduled_jobs(job_store, triggers, wiring.clock)
    return Scheduler(
        SchedulerDeps(
            clock=wiring.clock,
            job_store=job_store,
            kill_switch=wiring.kill_switch,
            runner=_make_job_runner(
                wiring.dispatcher,
                wiring.sessions,
                wiring.new_id,
                wiring.clock,
                wiring.agent_registry,
            ),
            audit=wiring.audit,
            correlation_id=wiring.new_id,
            parse=_make_schedule_parser(ZoneInfo(triggers.timezone)),
        )
    )


def _register_scheduled_jobs(job_store, triggers, clock) -> None:
    """The five job rows `_wire_scheduler` registers on every boot (11 §4
    — split into two families purely to keep both this function and
    `_wire_scheduler` under the size lint's line limit; neither split is
    a domain concept of its own, same reasoning `_build_stores`/
    `_build_bus_wiring` were extracted for)."""
    _register_planning_jobs(job_store, triggers, clock)
    _register_backup_jobs(job_store, clock)


def _register_planning_jobs(job_store, triggers, clock) -> None:
    """morning_plan, deadline_sweep, held_action_expire."""
    job_store.register_job(
        Job(
            id=MORNING_PLAN_JOB,
            name=MORNING_PLAN_JOB,
            schedule=triggers.morning_cron(),
            catch_up=triggers.catch_up_policy,  # run_once_latest: one plan
            created_at=clock.now(),
        )
    )
    job_store.register_job(
        Job(
            id=DEADLINE_SWEEP_JOB,
            name=DEADLINE_SWEEP_JOB,
            # 05 Appendix E: hourly, any product state, run_once_latest.
            # Anchor-relative (not kang.toml-driven) — a sweep's exact
            # minute is meaningless, unlike morning_plan's wall-clock
            # ritual (ADR-006's own reasoning for keeping the interval
            # forms alongside cron).
            schedule="hourly",
            catch_up="run_once_latest",
            created_at=clock.now(),
            # 05_AGENTS Appendix A's own deadline_sweep row names 2m
            # directly (unlike morning_plan: the planner agent's 10m there
            # is a budget across three different job triggers, not
            # morning_plan's own number — not reused here to avoid
            # inventing a figure nothing actually names).
            timeout_s=120,
        )
    )
    job_store.register_job(
        Job(
            id=HELD_ACTION_EXPIRE_JOB,
            name=HELD_ACTION_EXPIRE_JOB,
            # ADR-022: daily, proportionate to the 24h expiry window this
            # sweep protects — no wall-clock urgency the way deadline_
            # sweep's hourly cadence has, so no cron/kang.toml needed.
            schedule="daily",
            catch_up="run_once_latest",
            created_at=clock.now(),
        )
    )


def _register_backup_jobs(job_store, clock) -> None:
    """backup_snapshot (ADR-031), backup_verify (ADR-032),
    backup_offsite_check (ADR-034)."""
    job_store.register_job(
        Job(
            id=BACKUP_SNAPSHOT_JOB,
            name=BACKUP_SNAPSHOT_JOB,
            # 05 Appendix E: daily. ADR-031 CORRECTS that table's
            # `run_all_missed` to `run_once_latest`: after N days of
            # downtime, run_all_missed would take N snapshots of the same
            # current database under N different dates — N-1 of them
            # lying about what those days held, at N times the disk. One
            # snapshot now is the honest result; the manifest records the
            # gap. The override is deliberate and argued in the ADR, not
            # a silent deviation.
            schedule="daily",
            catch_up="run_once_latest",
            created_at=clock.now(),
            # 07 Part XII's own timing target is "< 60 s at 10-year size";
            # doubled, the same way deadline_sweep took Appendix A's named
            # figure rather than inventing one.
            timeout_s=120,
        )
    )
    job_store.register_job(
        Job(
            id=BACKUP_VERIFY_JOB,
            name=BACKUP_VERIFY_JOB,
            # 05 Appendix E: monthly. Not a plain interval literal — the
            # scheduler's interval dialect supports only every:{s}/daily/
            # hourly/minutely, no "monthly" (ADR-032 correction 3) — so
            # this uses the cron dialect already load-bearing for
            # morning_plan's own wall-clock trigger, at the timezone
            # kang.toml already provides. 03:00 on the 1st, after that
            # day's 02:30 daily snapshot has already run.
            schedule="cron:0 3 1 * *",
            catch_up="run_once_latest",
            created_at=clock.now(),
            # 07 Part XII's own restore-test target is "< 5 min"; 120s
            # matches backup_snapshot's own margin, not a fresh number.
            timeout_s=120,
        )
    )
    job_store.register_job(
        Job(
            id=BACKUP_OFFSITE_CHECK_JOB,
            name=BACKUP_OFFSITE_CHECK_JOB,
            # ADR-034 D5/D2: weekly, matching Part XII.5's own "(weekly)"
            # word — read as both the check cadence AND the staleness
            # threshold, one number, not two. Sunday 03:00: the same 3am
            # maintenance slot backup_verify already uses monthly.
            schedule="cron:0 3 * * 0",
            catch_up="run_once_latest",  # multiple missed weeks catch up
            #   to one check of current state, not N reads of an
            #   unchanged marker (ADR-031's own reasoning for its sibling).
            created_at=clock.now(),
            # A single file stat — no timing target named anywhere in 07
            # Part XII.5, so no figure invented; the default applies.
        )
    )


def _tick_once(core) -> None:
    """One tick: re-run the scheduler's catch-up, if a scheduler is
    wired. `core.scheduler` is `None` when `kang.toml` is missing/invalid
    (`_wire_scheduler`'s own fail-closed path) — silently skipped, same
    as every other scheduler operation already does. A plain function
    (not a closure) so it can be handed to `WriteExecutor.submit`
    directly and unit-tested against a bare stand-in with a `.scheduler`
    attribute, no real `Core` required."""
    if core.scheduler is not None:
        core.scheduler.tick()


async def _tick_forever(write_executor) -> None:
    """The live tick (ADR-019), now a native `asyncio` loop (ADR-036 D4)
    instead of an `HTTPServer.service_actions()` override: re-runs
    `Scheduler.tick()` every `TICK_INTERVAL_S`, via the write-executor
    `serve()` already uses for every dispatch — a scheduled job is a
    command like any other, so it queues behind the same single worker,
    never racing a concurrent request for the connection.

    No clock-based gating needed anymore (contrast the old
    `service_actions()` shape, called on every server poll regardless of
    interval): `asyncio.sleep()` IS the interval here, not a wall-clock
    read to compare against one (11 §25's ban is on the latter). Runs
    until cancelled — the caller wraps this in a supervised task (ADR-036
    D2) and cancels it on shutdown."""
    while True:
        await asyncio.sleep(TICK_INTERVAL_S)
        await write_executor.submit(_tick_once)
