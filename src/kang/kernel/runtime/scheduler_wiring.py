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
calls into `_wire_scheduler`/`_make_ticking_server_class` here exactly as
it called its own private functions before.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from http.server import HTTPServer
from zoneinfo import ZoneInfo

from kang.adapters.config.planner_config import (
    PlannerConfigError,
    load_planner_triggers,
)
from kang.adapters.scheduler import CRON_PREFIX, parse_cron
from kang.api.dispatch import ApiRequest, Dispatcher
from kang.domain.ports.scheduler import Job
from kang.domain.ports.session import Session
from kang.kernel.audit.service import AuditService
from kang.kernel.scheduler.schedule import parse_schedule
from kang.kernel.scheduler.scheduler import Scheduler, SchedulerDeps

__all__ = [
    "DEADLINE_SWEEP_JOB",
    "HELD_ACTION_EXPIRE_JOB",
    "JOB_OPERATIONS",
    "MORNING_PLAN_JOB",
    "SCHEDULER_PRINCIPAL",
    "TICK_INTERVAL_S",
    "_SchedulerWiring",
    "_make_job_runner",
    "_make_schedule_parser",
    "_make_ticking_server_class",
    "_wire_scheduler",
]

SCHEDULER_PRINCIPAL = "kernel:scheduler"  # dispatches jobs (already audits
#   under this name — ADR-006 names nothing new)
MORNING_PLAN_JOB = "morning_plan"  # 05 Appendix E's ritual name
DEADLINE_SWEEP_JOB = "deadline_sweep"  # 05 Appendix E's ritual name (ADR-020)
HELD_ACTION_EXPIRE_JOB = "held_action_expire"  # ADR-022

TICK_INTERVAL_S = 60  # ADR-019: how often the live tick re-runs catch-up.
# A plain constant, not a kang.toml key — nothing has asked to tune this
# yet, unlike [planner.triggers]'s lived trigger times.

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


def _make_job_runner(dispatcher: Dispatcher, sessions, new_id):
    """The job→operation seam (ADR-006 Part B).

    Jobs dispatch through the SAME pipeline a UI command takes, so scheduled
    work is permission-checked, idempotency-keyed, invocation-recorded and
    audited exactly once, by one path (12 §5). That is what lets
    `explain.invocation` reconstruct why a job acted — which matters most
    for the actions Kang did not watch happen (12 §12).

    The session is minted for principal `kernel:scheduler` with
    **first_party=False**. That is a feature, not a limitation: per ADR-002
    first-party means "arrived out-of-band through Kang's own UI", so a job
    is structurally incapable of approving a held action — SEC-003 enforced
    by construction rather than by remembering. Do NOT "fix" this by minting
    first-party sessions for jobs; that hands automation the power to
    approve its own consequences.
    """

    def run(job: Job, slot: datetime) -> None:
        operation = JOB_OPERATIONS.get(job.name)
        if operation is None:
            raise KeyError(
                f"job {job.name!r} has no registered operation — a scheduled "
                "job that runs nothing is a wiring defect, not a no-op"
            )
        session = Session(
            token=new_id(),
            principal=SCHEDULER_PRINCIPAL,
            first_party=False,  # a job is not Kang's hand (ADR-002)
            created_at=slot.isoformat(),
        )
        sessions.create(session)
        response = dispatcher.dispatch(
            ApiRequest(
                operation=operation,
                params={},
                session_token=session.token,
                # Deterministic per (job, slot): a replayed slot returns the
                # cached outcome instead of re-executing (API-004). Defence
                # in depth — the durable guard is the job_run baseline,
                # since API-004 keys are retained only 7 days.
                idempotency_key=f"job:{job.id}:{slot.isoformat()}",
            )
        )
        if not response.get("ok"):
            # Raising is what the Scheduler counts as a failed slot, which is
            # what drives retry/quarantine (05 §11). Swallowing it here would
            # make a broken job look healthy forever.
            raise RuntimeError(
                f"job {job.name} → {operation} failed: {response.get('error')}"
            )

    return run


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
            runner=_make_job_runner(wiring.dispatcher, wiring.sessions, wiring.new_id),
            audit=wiring.audit,
            correlation_id=wiring.new_id,
            parse=_make_schedule_parser(ZoneInfo(triggers.timezone)),
        )
    )


def _register_scheduled_jobs(job_store, triggers, clock) -> None:
    """The three job rows `_wire_scheduler` registers on every boot (11 §4
    — extracted purely to keep `_wire_scheduler` under the size lint's
    line limit; not a domain concept of its own, same reasoning
    `_build_stores`/`_build_bus_wiring` were extracted for)."""
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


def _make_ticking_server_class(scheduler, clock) -> type[HTTPServer]:
    """ADR-019: a plain `HTTPServer` subclass whose `service_actions()` —
    called once per `serve_forever` poll cycle, on the same thread that
    owns `kang.db` — re-runs the scheduler's catch-up on a tick.

    No new thread, no new connection: DB-001's thread-confined single
    writer stays exactly as it is, because this never leaves the
    connection-owning thread. Gated by `TICK_INTERVAL_S` via `clock`, not
    wall time (11 §25 bans wall-clock outside ports). `scheduler` is
    closed over rather than threaded through `make_server` so
    `http_binding.py` stays fully scheduler-ignorant — this is the
    composition root's own bridge (ADR-006 ruling 4's precedent)."""

    class _TickingHTTPServer(HTTPServer):
        _last_tick = None

        def service_actions(self) -> None:
            if scheduler is None:
                return
            now = clock.now()
            if (
                self._last_tick is not None
                and (now - self._last_tick).total_seconds() < TICK_INTERVAL_S
            ):
                return
            self._last_tick = now
            scheduler.tick()

    return _TickingHTTPServer
