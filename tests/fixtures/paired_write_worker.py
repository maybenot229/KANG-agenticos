"""Paired-write worker — drives the REAL event bus, killable at each EB-004
step, for the C2 crash-replay gate (13 §2.5).

This worker does NOT reimplement the write ordering: it calls the production
`EventBus.publish` (EB-004 steps 1-5) and the production `EventBus.recover`
(the caged `Reconciliation` + delivery resume). Kill points are injected via
a dying-port wrapper (`_KillingEventLog`) so the process dies at a real
boundary between steps WITHOUT any test seam inside production code —
os._exit(9), no cleanup, exactly what a crash leaves.

Usage: python paired_write_worker.py <workdir> <kill_at>
  kill_at ∈ before_append | after_append | after_state | after_confirm |
           during_deliver | none
"""

from __future__ import annotations

import itertools
import os
import sys
from pathlib import Path

from kang.adapters.eventlog.delivery_store import SqliteDeliveryStore
from kang.adapters.eventlog.event_log import SqliteEventLog
from kang.adapters.eventlog.schema import open_eventlog
from kang.adapters.fakes.clock import FakeClock
from kang.adapters.jsonl.audit_log import JsonlAuditLog
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.recovery import SqliteRecoveryApplier
from kang.adapters.sqlite.task_store import SqliteTaskStore
from kang.domain.ports.eventlog import EventEnvelope, EventLog, StoredEvent
from kang.domain.ports.task_store import Task
from kang.domain.tasks import TaskDraft, create_task
from kang.kernel.audit.service import AuditService
from kang.kernel.bus.bus import EventBus, Subscriber
from kang.kernel.bus.delivery import Delivery
from kang.kernel.bus.reconciliation import Reconciliation
from kang.kernel.permissions.engine import PermissionEngine
from kang.kernel.runtime.sleeper import RealSleeper

KILL_POINTS = (
    "before_append",
    "after_append",
    "after_state",
    "after_confirm",
    "during_deliver",
    "none",
)

TASK_ID = "task-c2"
EVENT_ID = "event-c2"
DEVICE = "device-test"
SUBSCRIBER = "recorder"


def task_payload(task: Task) -> dict:
    """The EB-003 self-sufficient payload: the full field set, not an id."""
    return {
        "id": task.id,
        "project_id": task.project_id,
        "title": task.title,
        "notes": task.notes,
        "status": task.status,
        "priority": task.priority,
        "due": task.due,
        "plan_date": task.plan_date,
        "estimate_min": task.estimate_min,
        "actual_min": task.actual_min,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
        "device_id": task.device_id,
        "revision": task.revision,
    }


def task_envelope(
    task: Task, event_id: str = EVENT_ID, event_type: str = "task.created"
) -> EventEnvelope:
    return EventEnvelope(
        event_id=event_id,
        type=event_type,
        occurred_at=task.updated_at.isoformat(),
        principal="kang",
        correlation_id=f"corr-{event_id}",
        device_id=task.device_id,
        payload=task_payload(task),
        recovery_grade=True,
        entity_refs=({"kind": "task", "id": task.id},),
    )


class _KillingEventLog:
    """EventLog decorator that os._exit(9)s at a chosen EB-004 boundary.
    Delegates everything else to the real log — the production write order
    runs unchanged; only the process's lifetime is cut."""

    def __init__(self, inner: EventLog, kill_at: str) -> None:
        self._inner = inner
        self._kill_at = kill_at

    def append(self, envelope: EventEnvelope) -> int:
        if self._kill_at == "before_append":
            os._exit(9)
        seq = self._inner.append(envelope)
        if self._kill_at == "after_append":
            os._exit(9)
        return seq

    def confirm(self, seq: int) -> None:
        if self._kill_at == "after_state":  # state committed, not yet confirmed
            os._exit(9)
        self._inner.confirm(seq)
        if self._kill_at == "after_confirm":  # confirmed, not yet delivered
            os._exit(9)

    def mark_orphaned(self, seq: int) -> None:
        self._inner.mark_orphaned(seq)

    def pending(self) -> list[StoredEvent]:
        return self._inner.pending()

    def read_from(self, seq_exclusive: int) -> list[StoredEvent]:
        return self._inner.read_from(seq_exclusive)

    def find_by_event_id(self, event_id: str) -> StoredEvent | None:
        return self._inner.find_by_event_id(event_id)

    def last_seq(self) -> int:
        return self._inner.last_seq()


def _recorder_handler(deliveries_path: Path, kill_at: str):
    """A subscriber that records delivered event_ids (dedup on event_id —
    the at-least-once consumer contract, §7.6). Dies AFTER its side effect
    but before the cursor advances when kill_at == during_deliver, proving
    idempotent dedup absorbs the redelivery."""

    def handler(envelope: EventEnvelope) -> None:
        seen = _delivered(deliveries_path)
        if envelope.event_id in seen:
            return  # idempotent: already delivered
        with deliveries_path.open("a", encoding="utf-8") as sink:
            sink.write(envelope.event_id + "\n")
        if kill_at == "during_deliver":
            os._exit(9)

    return handler


def _delivered(deliveries_path: Path) -> list[str]:
    if not deliveries_path.exists():
        return []
    return [
        line.strip()
        for line in deliveries_path.read_text().splitlines()
        if line.strip()
    ]


class _Wiring:
    """Holds the bus + its connections so the recovery path can close them
    (the publish path dies mid-flight, so it never closes — that is the
    crash)."""

    def __init__(self, bus, store, task, connections):
        self.bus = bus
        self.store = store
        self.task = task
        self._connections = connections

    def close(self) -> None:
        for connection in self._connections:
            connection.close()


def _build_bus(workdir: Path, kill_at: str) -> _Wiring:
    clock = FakeClock()
    kang = open_connection(workdir / "kang.db")
    events = open_eventlog(workdir / "events" / "eventlog.db")
    log = _KillingEventLog(SqliteEventLog(events, clock), kill_at)
    store = SqliteTaskStore(kang, clock)
    delivery_store = SqliteDeliveryStore(events, clock)
    audit = AuditService(JsonlAuditLog(workdir / "audit"), clock)
    applier = SqliteRecoveryApplier(kang)
    ids = (f"dl-{n}" for n in itertools.count())
    delivery = Delivery(
        log,
        delivery_store,
        audit,
        dead_letter_id=lambda: next(ids),
        sleeper=RealSleeper(),
    )
    reconciliation = Reconciliation(log, applier, audit, clock)
    handler = _recorder_handler(workdir / "deliveries.log", kill_at)
    # Publisher principal on these envelopes is `kang` (Kang's own action);
    # the `*` grant authorizes publishing the core namespace (EB-010).
    permissions = PermissionEngine({"kang": ("*",)})
    bus = EventBus(
        log,
        delivery,
        reconciliation,
        permissions,
        audit,
        [Subscriber(SUBSCRIBER, handler)],
    )
    task = create_task(
        TaskDraft(title="crash me"), task_id=TASK_ID, clock=clock, device_id=DEVICE
    )
    return _Wiring(bus, store, task, [kang, events])


def run_publish(workdir: Path, kill_at: str) -> None:
    """The write path: publish the event with the state commit as the
    interleaved kang.db transaction (EB-004 step 3)."""
    wiring = _build_bus(workdir, kill_at)
    wiring.bus.publish(
        task_envelope(wiring.task),
        commit_state=lambda: wiring.store.create(wiring.task),
    )


def recover(workdir: Path) -> dict:
    """A fresh process's startup: build the real bus over the surviving
    files and run the production recovery (caged Reconciliation + delivery
    resume). Returns the convergence facts the C2 gate asserts on."""
    wiring = _build_bus(workdir, kill_at="none")
    report = wiring.bus.recover()
    kang, events = wiring._connections
    try:
        row = kang.execute(
            "SELECT id, title, status, device_id, revision, created_at, updated_at "
            "FROM task WHERE id = ?",
            (TASK_ID,),
        ).fetchone()
        integrity = kang.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        states = [r[0] for r in events.execute("SELECT state FROM event ORDER BY seq")]
        pending = wiring.bus.pending_count()
    finally:
        wiring.close()
    return {
        "reapplied": report.reapplied,
        "confirmed": report.confirmed,
        "orphaned": report.orphaned,
        "window": report.window,
        "task_row": row,
        "kang_integrity": integrity,
        "event_states": states,
        "pending_after": pending,
        "delivered": _delivered(workdir / "deliveries.log"),
    }


if __name__ == "__main__":
    directory, kill_point = Path(sys.argv[1]), sys.argv[2]
    if kill_point not in KILL_POINTS:
        raise SystemExit(f"kill_at must be one of {KILL_POINTS}")
    run_publish(directory, kill_point)
