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
from kang.adapters.scheduler import CRON_PREFIX, parse_cron
from kang.adapters.sqlite.calendar_store import SqliteCalendarStore
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.deadline_store import SqliteDeadlineStore
from kang.adapters.sqlite.idempotency_store import SqliteIdempotencyStore
from kang.adapters.sqlite.invocation_store import SqliteInvocationStore
from kang.adapters.sqlite.job_store import SqliteJobStore, SqliteKillSwitch
from kang.adapters.sqlite.migrations import apply_migrations
from kang.adapters.sqlite.notification_store import SqliteNotificationStore
from kang.adapters.sqlite.recovery import SqliteRecoveryApplier
from kang.adapters.sqlite.session_store import SqliteSessionStore
from kang.adapters.sqlite.task_store import SqliteTaskStore
from kang.api.dispatch import ApiRequest, Dispatcher, DispatcherDeps
from kang.api.http_binding import make_server
from kang.api.operations import (
    PlannerDeps,
    make_deadline_create_handler,
    make_deadline_sweep_handler,
    make_explain_invocation_handler,
    make_explain_stub_handler,
    make_notification_ack_handler,
    make_plan_generate_handler,
    make_registry_get_handler,
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

MIGRATIONS_DIR = Path(__file__).resolve().parents[4] / "migrations"


@dataclass
class Core:
    """The wired system: the dispatcher plus what the server needs to mint a
    session and shut down cleanly."""

    dispatcher: Dispatcher
    sessions: SqliteSessionStore
    new_id: object
    _connections: list
    scheduler: object = None

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
JOB_OPERATIONS: dict[str, str] = {"morning_plan": "plan.generate"}


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


def _build_handlers(w: _HandlerWiring) -> dict:
    """The operation name → handler table. Plain construction, one entry per
    registered operation — the registry is the contract, this is its wiring."""
    return {
        "registry.get": make_registry_get_handler(),
        "task.create": make_task_create_handler(
            w.bus, w.task_store, w.clock, w.new_id, w.device_id
        ),
        "task.get": make_task_get_handler(w.task_store),
        "deadline.create": make_deadline_create_handler(
            w.bus, w.deadline_store, w.clock, w.new_id, w.device_id
        ),
        "deadline.sweep": make_deadline_sweep_handler(
            w.bus, w.deadline_store, w.clock, w.new_id, w.device_id
        ),
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
    }


def build_core(kang_home: Path, device_id: str = "device-local") -> Core:
    kang_home.mkdir(parents=True, exist_ok=True)
    clock = SystemClock()

    def new_id() -> str:
        return uuid7(int(clock.now().timestamp() * 1000), os.urandom)

    kang = open_connection(kang_home / "kang.db")
    apply_migrations(kang, MIGRATIONS_DIR, clock)
    events = open_eventlog(kang_home / "events" / "eventlog.db")

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

    task_store = SqliteTaskStore(kang, clock)
    deadline_store = SqliteDeadlineStore(kang, clock)
    invocations = SqliteInvocationStore(kang)
    handlers = _build_handlers(
        _HandlerWiring(
            connection=kang,
            bus=bus,
            clock=clock,
            new_id=new_id,
            device_id=device_id,
            audit=audit,
            task_store=task_store,
            deadline_store=deadline_store,
            notification_store=notification_store,
            invocations=invocations,
        )
    )
    dispatcher = Dispatcher(
        handlers,
        DispatcherDeps(
            sessions=SqliteSessionStore(kang),
            permissions=engine,
            idempotency=SqliteIdempotencyStore(kang),
            invocations=invocations,
            audit=audit,
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
                audit=audit,
                dispatcher=dispatcher,
                sessions=sessions,
                new_id=new_id,
            )
        ),
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
    """
    try:
        triggers = load_planner_triggers(wiring.kang_home / "config" / "kang.toml")
    except PlannerConfigError as exc:
        wiring.audit.record(
            SCHEDULER_PRINCIPAL, "automation.unconfigured", {"reason": str(exc)}
        )
        return None
    job_store = SqliteJobStore(wiring.connection, wiring.clock)
    job_store.register_job(
        Job(
            id=MORNING_PLAN_JOB,
            name=MORNING_PLAN_JOB,
            schedule=triggers.morning_cron(),
            catch_up=triggers.catch_up_policy,  # run_once_latest: one plan
            created_at=wiring.clock.now(),
        )
    )
    return Scheduler(
        SchedulerDeps(
            clock=wiring.clock,
            job_store=job_store,
            kill_switch=SqliteKillSwitch(wiring.connection, wiring.clock),
            runner=_make_job_runner(wiring.dispatcher, wiring.sessions, wiring.new_id),
            audit=wiring.audit,
            correlation_id=wiring.new_id,
            parse=_make_schedule_parser(ZoneInfo(triggers.timezone)),
        )
    )


def serve(kang_home: Path, host: str = "127.0.0.1", port: int = 0) -> None:
    """Wire the Core, mint a first-party session, write the session file the
    CLI reads (API-003: the Core's session file), and serve the operation
    channel until interrupted. port=0 binds an ephemeral port."""
    core = build_core(kang_home)
    session = core.mint_first_party_session()
    server = make_server(core.dispatcher, host, port)
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
