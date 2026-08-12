"""Composition root — the ONE place concretions meet interfaces (17 §4.3).

Layer: kernel/runtime, but exempt from the import matrix: this is the single
module that MAY import adapters and the api, because something must
instantiate concretions and inject them (17 §4.3 composition-root
exception). It contains wiring only — no branching beyond config, no domain
logic. The exemption is registered by name in tools/importlinter.toml and
MUST NOT spread.

Constitutional home: 11_CODING §11 (composition root, plain constructor
calls, readable top to bottom), 17 §4.3, 12_API §5 (it assembles the
request pipeline), 07 F8 (fail-closed to Kang-only grants if permissions.toml
is missing/invalid).
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from http.server import HTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

from kang.adapters.config.permissions_loader import (
    KANG_ONLY_GRANTS,
    GrantLoadError,
    load_grants,
)
from kang.adapters.config.planner_config import (
    PlannerConfigError,
    load_planner_triggers,
)
from kang.adapters.eventlog.delivery_store import SqliteDeliveryStore
from kang.adapters.eventlog.event_log import SqliteEventLog
from kang.adapters.eventlog.schema import open_eventlog
from kang.adapters.jsonl.audit_log import JsonlAuditLog
from kang.adapters.os_windows.clock import SystemClock
from kang.adapters.os_windows.startup_lock import FileStartupLock
from kang.adapters.scheduler import CRON_PREFIX, parse_cron
from kang.adapters.sqlite.calendar_store import SqliteCalendarStore
from kang.adapters.sqlite.competition_store import SqliteCompetitionStore
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.deadline_store import SqliteDeadlineStore
from kang.adapters.sqlite.goal_store import SqliteGoalStore
from kang.adapters.sqlite.held_action_store import SqliteHeldActionStore
from kang.adapters.sqlite.idempotency_store import SqliteIdempotencyStore
from kang.adapters.sqlite.invocation_store import SqliteInvocationStore
from kang.adapters.sqlite.job_store import SqliteJobStore, SqliteKillSwitch
from kang.adapters.sqlite.migrations import apply_migrations
from kang.adapters.sqlite.milestone_store import SqliteMilestoneStore
from kang.adapters.sqlite.notification_store import SqliteNotificationStore
from kang.adapters.sqlite.project_store import SqliteProjectStore
from kang.adapters.sqlite.recovery import SqliteRecoveryApplier
from kang.adapters.sqlite.session_store import SqliteSessionStore
from kang.adapters.sqlite.task_store import SqliteTaskStore
from kang.api.dispatch import ApiRequest, Dispatcher, DispatcherDeps
from kang.api.http_binding import make_server
from kang.api.operations import (
    ConfirmationDeps,
    PlannerDeps,
    make_audit_list_handler,
    make_competition_create_handler,
    make_competition_list_handler,
    make_deadline_create_handler,
    make_deadline_list_handler,
    make_deadline_sweep_handler,
    make_explain_invocation_handler,
    make_explain_stub_handler,
    make_goal_achieve_handler,
    make_goal_create_handler,
    make_goal_list_handler,
    make_goal_retire_handler,
    make_goal_revise_handler,
    make_held_action_approve_handler,
    make_held_action_cancel_handler,
    make_held_action_list_handler,
    make_invocation_list_handler,
    make_job_disable_handler,
    make_job_enable_handler,
    make_milestone_create_handler,
    make_milestone_drop_handler,
    make_milestone_list_handler,
    make_milestone_miss_handler,
    make_milestone_reach_handler,
    make_notification_ack_handler,
    make_permission_list_handler,
    make_plan_generate_handler,
    make_project_complete_handler,
    make_project_create_handler,
    make_project_list_handler,
    make_registry_get_handler,
    make_system_health_handler,
    make_task_complete_handler,
    make_task_create_handler,
    make_task_get_handler,
)
from kang.domain.notifications import (
    make_deadline_enqueue_handler,
    make_drain_handler,
    notification_requested_payload,
)
from kang.domain.ports.eventlog import EventEnvelope
from kang.domain.ports.scheduler import Job
from kang.domain.ports.session import Session
from kang.domain.ports.startup_lock import AlreadyRunningError
from kang.kernel.audit.service import AuditService
from kang.kernel.bus.bus import EventBus, Subscriber
from kang.kernel.bus.delivery import Delivery
from kang.kernel.bus.reconciliation import Reconciliation
from kang.kernel.permissions.engine import build_checked_engine
from kang.kernel.runtime.ids import uuid7
from kang.kernel.runtime.sleeper import RealSleeper
from kang.kernel.scheduler.schedule import parse_schedule
from kang.kernel.scheduler.scheduler import Scheduler, SchedulerDeps

__all__ = ["Core", "build_core", "serve"]

SESSION_FILE = "session.json"

NOTIFIER_PRINCIPAL = "kernel:notifier"  # publishes notification.requested
SCHEDULER_PRINCIPAL = "kernel:scheduler"  # dispatches jobs (already audits
#   under this name — ADR-006 names nothing new)
MORNING_PLAN_JOB = "morning_plan"  # 05 Appendix E's ritual name
DEADLINE_SWEEP_JOB = "deadline_sweep"  # 05 Appendix E's ritual name (ADR-020)

MIGRATIONS_DIR = Path(__file__).resolve().parents[4] / "migrations"

TICK_INTERVAL_S = 60  # ADR-019: how often the live tick re-runs catch-up.
# A plain constant, not a kang.toml key — nothing has asked to tune this
# yet, unlike [planner.triggers]'s lived trigger times.


@dataclass
class Core:
    """The wired system: the dispatcher plus what the server needs to mint a
    session and shut down cleanly."""

    dispatcher: Dispatcher
    sessions: SqliteSessionStore
    new_id: object
    _connections: list
    scheduler: object = None
    startup_lock: object = None
    clock: object = None  # ADR-019: times the tick loop's interval gate

    def mint_first_party_session(self) -> Session:
        token = self.new_id()  # type: ignore[operator]
        session = Session(
            token=token,
            principal="kang",
            first_party=True,
            created_at="",  # stamped below by the caller's clock if needed
        )
        self.sessions.create(session)
        return session

    def close(self) -> None:
        for connection in self._connections:
            connection.close()
        if self.startup_lock is not None:
            self.startup_lock.release()  # ADR-008 Part A2


class _BusNotificationPublisher:
    """Satisfies the notifier's `NotificationPublisher` port with the real
    bus. Lives here because the composition root is the one place a
    concretion may meet an interface (17 §4.3); putting it in `kernel/bus/`
    would make the kernel domain-aware, which the smell checklist forbids.
    """

    def __init__(self, bus: EventBus, new_id, device_id: str) -> None:
        self._bus = bus
        self._new_id = new_id
        self._device_id = device_id

    def publish_requested(self, notification, caused_by: str) -> None:
        self._bus.publish(
            EventEnvelope(
                event_id=self._new_id(),
                type="notification.requested",
                occurred_at=notification.created_at.isoformat(),
                principal=NOTIFIER_PRINCIPAL,
                correlation_id=notification.correlation_id,
                # Threading causation is what keeps EB-011.2's depth guard
                # live on this path — see the port's docstring.
                causation_id=caused_by,
                device_id=self._device_id,
                payload=notification_requested_payload(notification),
                recovery_grade=False,
                entity_refs=notification.entity_refs,
            ),
            # The queue row is already committed — this event only
            # accelerates the drain (15 §6.2).
            commit_state=lambda: None,
        )


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


def _load_grants(kang_home: Path):
    """Grant truth from %KANG_HOME%/config/permissions.toml; fail closed to
    Kang-only if absent or invalid (07 F8)."""
    try:
        return load_grants(kang_home / "config" / "permissions.toml")
    except (GrantLoadError, ValueError):
        return KANG_ONLY_GRANTS


def _wire_notifier(bus, notification_store, clock, new_id, device_id: str) -> None:
    """Register the notifier's two halves (domain/notifications): enqueue on
    the fact, drain on the accelerant. Registration order IS delivery order
    (§7.7), so enqueue deterministically precedes drain."""
    publisher = _BusNotificationPublisher(bus, new_id, device_id)
    bus.subscribe(
        Subscriber(
            "notifier.enqueue",
            make_deadline_enqueue_handler(notification_store, publisher, clock, new_id),
        )
    )
    bus.subscribe(
        Subscriber("notifier.drain", make_drain_handler(notification_store, clock))
    )


@dataclass(frozen=True)
class _HandlerWiring:
    """Everything the operation handlers are built from (11 §4)."""

    connection: object
    bus: EventBus
    clock: object
    new_id: object
    device_id: str
    audit: AuditService
    task_store: object
    deadline_store: object
    notification_store: object
    invocations: object
    held_action_store: object
    permission_engine: object
    job_store: object
    kill_switch: object
    project_store: object
    competition_store: object
    milestone_store: object
    goal_store: object


def _build_handlers(w: _HandlerWiring) -> dict:
    """The operation name → handler table. Plain construction, one entry per
    registered operation — the registry is the contract, this is its wiring."""
    return {
        "registry.get": make_registry_get_handler(),
        "task.create": make_task_create_handler(
            w.bus, w.task_store, w.clock, w.new_id, w.device_id
        ),
        "task.get": make_task_get_handler(w.task_store),
        "task.complete": make_task_complete_handler(
            w.bus, w.task_store, w.clock, w.new_id, w.device_id
        ),
        "deadline.create": make_deadline_create_handler(
            w.bus, w.deadline_store, w.clock, w.new_id, w.device_id
        ),
        "deadline.sweep": make_deadline_sweep_handler(
            w.bus, w.deadline_store, w.clock, w.new_id, w.device_id
        ),
        "deadline.list": make_deadline_list_handler(w.deadline_store),
        "notification.ack": make_notification_ack_handler(
            w.notification_store, w.clock
        ),
        "plan.generate": make_plan_generate_handler(
            PlannerDeps(
                bus=w.bus,
                tasks=w.task_store,
                deadlines=w.deadline_store,
                calendar=SqliteCalendarStore(w.connection),
                clock=w.clock,
                new_id=w.new_id,
                device_id=w.device_id,
            )
        ),
        "explain.invocation": make_explain_invocation_handler(w.invocations, w.audit),
        "explain.plan_item": make_explain_stub_handler("plan item"),
        "explain.notification": make_explain_stub_handler("notification"),
        "explain.suggestion": make_explain_stub_handler("suggestion"),
        "explain.memory": make_explain_stub_handler("memory record"),
        "permission.list": make_permission_list_handler(w.permission_engine),
        "audit.list": make_audit_list_handler(w.audit, w.clock),
        "system.health": make_system_health_handler(w.job_store, w.kill_switch),
        "invocation.list": make_invocation_list_handler(w.invocations),
        **_build_project_cluster_handlers(w),
        **_build_consequential_handlers(w),
    }


def _build_consequential_handlers(w: _HandlerWiring) -> dict:
    """held_action.*/job.enable/.disable — ADR-021's pipeline, mirroring
    `_build_project_cluster_handlers`'s own extraction (11 §4's size lint).
    `transactional_effects` keys by operation name (JOB_OPERATIONS' shape,
    ADR-006 ruling 4) — held_action.approve looks itself up here."""
    js, ha = w.job_store, w.held_action_store
    transactional_effects = {
        "job.disable": lambda p: js.set_enabled_in_txn(p["job_id"], False),
        "job.enable": lambda p: js.set_enabled_in_txn(p["job_id"], True),
    }
    confirmation = ConfirmationDeps(ha, w.clock, w.new_id)
    return {
        "held_action.approve": make_held_action_approve_handler(
            ha, w.clock, w.connection, transactional_effects
        ),
        "held_action.cancel": make_held_action_cancel_handler(ha),
        "held_action.list": make_held_action_list_handler(ha),
        "job.disable": make_job_disable_handler(js, confirmation),
        "job.enable": make_job_enable_handler(js, confirmation),
    }


def _build_project_cluster_handlers(w: _HandlerWiring) -> dict:
    """project/competition/milestone/goal operations — extracted from
    `_build_handlers` (11 §4 — the flat dict crossed the size lint's
    80-line hard limit the moment goal's transitions landed; per
    11_CODING §25, a lint failure is answered by splitting the unit,
    never relaxing the limit). Not a domain concept of its own, same
    reasoning `_build_stores`/`_build_bus_wiring` were extracted for —
    these four entities already share `domain/projects/`'s own package
    grouping (this session's `goal_service.py`/`milestone_service.py`
    docstrings), so the split mirrors a boundary that already exists."""
    return {
        "project.create": make_project_create_handler(
            w.bus, w.project_store, w.clock, w.new_id, w.device_id
        ),
        "project.list": make_project_list_handler(w.project_store),
        "project.complete": make_project_complete_handler(
            w.bus, w.project_store, w.clock, w.new_id, w.device_id
        ),
        "competition.create": make_competition_create_handler(
            w.bus, w.competition_store, w.clock, w.new_id, w.device_id
        ),
        "competition.list": make_competition_list_handler(w.competition_store),
        "milestone.create": make_milestone_create_handler(
            w.bus, w.milestone_store, w.clock, w.new_id, w.device_id
        ),
        "milestone.list": make_milestone_list_handler(w.milestone_store),
        "milestone.reach": make_milestone_reach_handler(
            w.bus, w.milestone_store, w.clock, w.new_id, w.device_id
        ),
        "milestone.miss": make_milestone_miss_handler(
            w.bus, w.milestone_store, w.clock, w.new_id, w.device_id
        ),
        "milestone.drop": make_milestone_drop_handler(
            w.bus, w.milestone_store, w.clock, w.new_id, w.device_id
        ),
        "goal.create": make_goal_create_handler(
            w.bus, w.goal_store, w.clock, w.new_id, w.device_id
        ),
        "goal.list": make_goal_list_handler(w.goal_store),
        "goal.achieve": make_goal_achieve_handler(
            w.bus, w.goal_store, w.clock, w.new_id, w.device_id
        ),
        "goal.revise": make_goal_revise_handler(
            w.bus, w.goal_store, w.clock, w.new_id, w.device_id
        ),
        "goal.retire": make_goal_retire_handler(
            w.bus, w.goal_store, w.clock, w.new_id, w.device_id
        ),
    }


@dataclass(frozen=True)
class _BusWiring:
    """The bus + its collaborators, constructed once (11 §4 — extracted
    from `build_core` to keep it under the size lint's line limit, same
    reason `_build_stores` was extracted; not a domain concept of its
    own)."""

    audit: AuditService
    engine: object
    bus: EventBus
    notification_store: object


def _build_bus_wiring(kang_home, kang, events, clock, new_id, device_id) -> _BusWiring:
    """Audit log, permission engine, event bus, notifier — wired and
    recovered. Split out of `build_core` verbatim; no behavior change."""
    audit = AuditService(JsonlAuditLog(kang_home / "audit"), clock)
    engine = build_checked_engine(_load_grants(kang_home))
    event_log = SqliteEventLog(events, clock)
    delivery = Delivery(
        event_log,
        SqliteDeliveryStore(events, clock),
        audit,
        dead_letter_id=new_id,
        sleeper=RealSleeper(),
    )
    reconciliation = Reconciliation(
        event_log, SqliteRecoveryApplier(kang), audit, clock
    )
    notification_store = SqliteNotificationStore(kang)
    bus = EventBus(event_log, delivery, reconciliation, engine, audit)
    _wire_notifier(bus, notification_store, clock, new_id, device_id)
    bus.recover()  # startup reconciliation + delivery resume (§4.4)
    return _BusWiring(
        audit=audit, engine=engine, bus=bus, notification_store=notification_store
    )


def build_core(kang_home: Path, device_id: str = "device-local") -> Core:
    kang_home.mkdir(parents=True, exist_ok=True)

    # ADR-008 Part A2: taken before any other resource (kang.db, the
    # eventlog) so a second live Core never gets far enough to contend
    # for either — AlreadyRunningError propagates immediately, nothing
    # yet opened to clean up. Everything from here on releases the lock
    # on its own failure (see the try/except below) rather than leaving
    # it held by a half-initialized Core a retry would then be blocked
    # by.
    startup_lock = FileStartupLock(kang_home / "core.lock")
    startup_lock.acquire()
    try:
        return _build_core_locked(kang_home, device_id, startup_lock)
    except Exception:
        startup_lock.release()
        raise


def _build_core_locked(
    kang_home: Path, device_id: str, startup_lock: FileStartupLock
) -> Core:
    """The rest of `build_core`, run only once the startup lock is held —
    split out so its own exceptions can be caught by name in one place
    (11 §4: not a domain concept of its own, purely so `build_core`'s
    lock/release bracket stays readable)."""
    clock = SystemClock()

    def new_id() -> str:
        return uuid7(int(clock.now().timestamp() * 1000), os.urandom)

    kang = open_connection(kang_home / "kang.db")
    apply_migrations(kang, MIGRATIONS_DIR, clock)
    events = open_eventlog(kang_home / "events" / "eventlog.db")

    wiring = _build_bus_wiring(kang_home, kang, events, clock, new_id, device_id)
    stores = _build_stores(kang, clock)
    handlers = _build_handlers(
        _HandlerWiring(
            connection=kang,
            bus=wiring.bus,
            clock=clock,
            new_id=new_id,
            device_id=device_id,
            audit=wiring.audit,
            task_store=stores.task_store,
            deadline_store=stores.deadline_store,
            notification_store=wiring.notification_store,
            invocations=stores.invocations,
            held_action_store=stores.held_action_store,
            permission_engine=wiring.engine,
            job_store=stores.job_store,
            kill_switch=stores.kill_switch,
            project_store=stores.project_store,
            competition_store=stores.competition_store,
            milestone_store=stores.milestone_store,
            goal_store=stores.goal_store,
        )
    )
    dispatcher = Dispatcher(
        handlers,
        DispatcherDeps(
            sessions=SqliteSessionStore(kang),
            permissions=wiring.engine,
            idempotency=SqliteIdempotencyStore(kang),
            invocations=stores.invocations,
            audit=wiring.audit,
            clock=clock,
            new_id=new_id,
        ),
    )
    sessions = SqliteSessionStore(kang)
    return Core(
        dispatcher=dispatcher,
        sessions=sessions,
        new_id=new_id,
        _connections=[kang, events],
        scheduler=_wire_scheduler(
            _SchedulerWiring(
                kang_home=kang_home,
                connection=kang,
                clock=clock,
                audit=wiring.audit,
                dispatcher=dispatcher,
                sessions=sessions,
                new_id=new_id,
                job_store=stores.job_store,
                kill_switch=stores.kill_switch,
            )
        ),
        startup_lock=startup_lock,
        clock=clock,
    )


@dataclass(frozen=True)
class _Stores:
    """Every store `_build_handlers`/`_wire_scheduler` need, constructed
    once (11 §4 — extracted from `build_core` to keep it under the size
    lint's line limit, not a domain concept of its own)."""

    task_store: object
    deadline_store: object
    invocations: object
    held_action_store: object
    job_store: object
    kill_switch: object
    project_store: object
    competition_store: object
    milestone_store: object
    goal_store: object


def _build_stores(kang, clock) -> _Stores:
    """`job_store`/`kill_switch` are constructed here unconditionally, not
    inside `_wire_scheduler` (which only runs its body — and, until
    2026-08-05, only constructed these — when `kang.toml` loads
    successfully, per 07 F8's fail-closed shape). Neither construction
    depends on `kang.toml`; the System-domain Health view (09_UI §12)
    needs them whether or not automation is configured."""
    return _Stores(
        task_store=SqliteTaskStore(kang, clock),
        deadline_store=SqliteDeadlineStore(kang, clock),
        invocations=SqliteInvocationStore(kang),
        held_action_store=SqliteHeldActionStore(kang),
        job_store=SqliteJobStore(kang, clock),
        kill_switch=SqliteKillSwitch(kang, clock),
        project_store=SqliteProjectStore(kang, clock),
        competition_store=SqliteCompetitionStore(kang),
        milestone_store=SqliteMilestoneStore(kang, clock),
        goal_store=SqliteGoalStore(kang, clock),
    )


@dataclass(frozen=True)
class _SchedulerWiring:
    """What the scheduler needs from the already-built Core (11 §4)."""

    kang_home: Path
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
    job_store.register_job(
        Job(
            id=MORNING_PLAN_JOB,
            name=MORNING_PLAN_JOB,
            schedule=triggers.morning_cron(),
            catch_up=triggers.catch_up_policy,  # run_once_latest: one plan
            created_at=wiring.clock.now(),
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
            created_at=wiring.clock.now(),
            # 05_AGENTS Appendix A's own deadline_sweep row names 2m
            # directly (unlike morning_plan: the planner agent's 10m there
            # is a budget across three different job triggers, not
            # morning_plan's own number — not reused here to avoid
            # inventing a figure nothing actually names).
            timeout_s=120,
        )
    )
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


def serve(kang_home: Path, host: str = "127.0.0.1", port: int = 0) -> None:
    """Wire the Core, mint a first-party session, write the session file the
    CLI reads (API-003: the Core's session file), and serve the operation
    channel until interrupted. port=0 binds an ephemeral port.

    Runs the scheduler's boot catch-up (D014: "on startup after downtime,
    each job's policy decides...") before accepting requests, then keeps
    it live: `serve_forever`'s server is built with a `service_actions()`
    override (ADR-019) that re-runs `Scheduler.tick()` every
    `TICK_INTERVAL_S` — so newly-due jobs are picked up while the process
    keeps running, not only at the next fresh boot. `core.scheduler` is
    `None` when `kang.toml` is missing/invalid (`_wire_scheduler`'s own
    fail-closed path); both the boot catch-up and the live tick are
    skipped silently in that case, same as every other scheduler operation
    already does. `dispatcher.dispatch` runs in-process (no HTTP
    loopback), so the boot catch-up is safe to run before `serve_forever`.

    ADR-008 Part A2: `build_core` takes an exclusive startup lock under
    `%KANG_HOME%` before touching anything else. A second live Core
    against the same home "detects the lock and exits/reports" (the
    ADR's own words) — a clear one-line stderr message and a non-zero
    exit, never a raw traceback, and never a second scheduler/notifier
    racing the first against the same `kang.db`."""
    try:
        core = build_core(kang_home)
    except AlreadyRunningError as exc:
        sys.stderr.write(f"KANG Core: {exc}\n")
        sys.exit(1)
    if core.scheduler is not None:
        core.scheduler.catch_up()
    session = core.mint_first_party_session()
    server = make_server(
        core.dispatcher,
        host,
        port,
        server_class=_make_ticking_server_class(core.scheduler, core.clock),
    )
    bound_host, bound_port = server.server_address[0], server.server_address[1]
    (kang_home / SESSION_FILE).write_text(
        json.dumps({"host": bound_host, "port": bound_port, "token": session.token}),
        encoding="utf-8",
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()
        core.close()


if __name__ == "__main__":
    # python -m kang.kernel.runtime.composition <kang_home> [host] [port]
    home = Path(sys.argv[1])
    serve(
        home,
        host=sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1",
        port=int(sys.argv[3]) if len(sys.argv) > 3 else 0,
    )
