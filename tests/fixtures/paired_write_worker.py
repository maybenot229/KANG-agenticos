"""Paired-write worker — the DB-001 durability pairing as a killable process.

Runs the M1 write pairing (EB-004 steps 2-4; step 5, fan-out, is M2's):

    append event (pending, synchronous=FULL)
      -> commit kang.db state
      -> confirm event

and `os._exit(9)`s at the requested kill point — no cleanup, no atexit,
exactly what a crash leaves behind. The crash-replay suite (13 §2.5) spawns
this between every adjacent step pair and asserts convergence.

Usage: python paired_write_worker.py <workdir> <kill_at>
  kill_at: before_append | after_append | after_state | after_confirm | none
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from kang.adapters.eventlog.event_log import SqliteEventLog
from kang.adapters.eventlog.schema import open_eventlog
from kang.adapters.fakes.clock import FakeClock
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.task_store import SqliteTaskStore
from kang.domain.ports.eventlog import EventEnvelope
from kang.domain.ports.task_store import Task
from kang.domain.tasks import TaskDraft, create_task

KILL_POINTS = ("before_append", "after_append", "after_state", "after_confirm", "none")

TASK_ID = "task-c1"
DEVICE = "device-test"


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
    task: Task, event_id: str, event_type: str = "task.created"
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


def _kill_if(kill_at: str, point: str) -> None:
    if kill_at == point:
        os._exit(9)


def run(workdir: Path, kill_at: str) -> None:
    clock = FakeClock()
    kang_conn = open_connection(workdir / "kang.db")
    event_conn = open_eventlog(workdir / "eventlog.db")
    event_log = SqliteEventLog(event_conn, clock)
    task = create_task(
        TaskDraft(title="crash me"), task_id=TASK_ID, clock=clock, device_id=DEVICE
    )
    envelope = task_envelope(task, event_id="event-c1")

    _kill_if(kill_at, "before_append")
    seq = event_log.append(envelope)  # EB-004 step 2
    _kill_if(kill_at, "after_append")
    SqliteTaskStore(kang_conn, clock).create(task)  # step 3
    _kill_if(kill_at, "after_state")
    event_log.confirm(seq)  # step 4
    _kill_if(kill_at, "after_confirm")


if __name__ == "__main__":
    directory, kill_point = Path(sys.argv[1]), sys.argv[2]
    if kill_point not in KILL_POINTS:
        raise SystemExit(f"kill_at must be one of {KILL_POINTS}")
    run(directory, kill_point)
