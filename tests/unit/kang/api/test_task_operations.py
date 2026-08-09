"""Task API handlers — `task.complete` (added 2026-08-09), the task
entity's first status-transition operation.

The claim under test: `task.complete` publishes `task.updated`
(already-registered, ADR-004, recovery-grade, full row) under
`kernel:tasks`, and the write commits only inside that publish (EB-004)
— mirroring `_publish_deadline_alert`'s established shape for
`deadline.updated`. `task.create`/`task.get` have no handler-level test
file of their own yet (a pre-existing gap, not touched here); this file
starts with `task.complete` and can grow to cover them later.
"""

from __future__ import annotations

import itertools

import pytest

from kang.adapters.fakes.audit_log import FakeAuditLog
from kang.adapters.fakes.clock import FakeClock
from kang.adapters.fakes.delivery_store import FakeDeliveryStore
from kang.adapters.fakes.event_log import FakeEventLog
from kang.adapters.fakes.recovery import FakeRecoveryApplier
from kang.adapters.fakes.sleeper import FakeSleeper
from kang.adapters.fakes.task_store import FakeTaskStore
from kang.api.dispatch import HandlerContext
from kang.api.errors import ApiError
from kang.api.operations import make_task_complete_handler
from kang.domain.ports.task_store import RevisionConflictError
from kang.domain.tasks import TaskDraft, create_task
from kang.kernel.audit.service import AuditService
from kang.kernel.bus.bus import EventBus
from kang.kernel.bus.delivery import Delivery
from kang.kernel.bus.reconciliation import Reconciliation
from kang.kernel.permissions.engine import PermissionEngine

DEVICE = "device-test"


@pytest.fixture
def wiring():
    clock = FakeClock()
    ids = (f"id-{n:04d}" for n in itertools.count())
    event_log = FakeEventLog(clock)
    audit = AuditService(FakeAuditLog(), clock)
    bus = EventBus(
        event_log,
        Delivery(
            event_log,
            FakeDeliveryStore(clock),
            audit,
            dead_letter_id=lambda: "dl",
            sleeper=FakeSleeper(),
        ),
        Reconciliation(event_log, FakeRecoveryApplier(), audit, clock),
        PermissionEngine({"kernel:tasks": ("events.publish:kang",)}),
        audit,
    )
    store = FakeTaskStore(clock)
    context = HandlerContext(
        principal="kang", correlation_id="corr-1", trigger="cli", first_party=True
    )
    return {
        "bus": bus,
        "store": store,
        "clock": clock,
        "new_id": lambda: next(ids),
        "log": event_log,
        "context": context,
    }


def _seed_task(wiring, **overrides):
    task = create_task(
        TaskDraft(title="a title", **overrides),
        task_id="task-0001",
        clock=wiring["clock"],
        device_id=DEVICE,
    )
    wiring["store"].create(task)
    return task


def _complete(wiring, **params):
    handler = make_task_complete_handler(
        wiring["bus"], wiring["store"], wiring["clock"], wiring["new_id"], DEVICE
    )
    return handler(wiring["context"], params)


def _published(wiring) -> list[str]:
    return [s.envelope.type for s in wiring["log"].read_from(0)]


class TestComplete:
    def test_completes_and_publishes_task_updated(self, wiring):
        _seed_task(wiring)
        result = _complete(wiring, id="task-0001")
        assert result["task_id"] == "task-0001"
        assert result["revision"] == 2  # store bumps on update
        assert wiring["store"].get("task-0001").status == "done"
        assert _published(wiring) == ["task.updated"]

    def test_updated_event_is_recovery_grade_with_the_full_row(self, wiring):
        _seed_task(wiring)
        _complete(wiring, id="task-0001")
        (stored,) = wiring["log"].read_from(0)
        assert stored.envelope.recovery_grade is True
        assert stored.envelope.payload["status"] == "done"
        assert stored.envelope.payload["completed_at"] is not None

    def test_completed_at_is_returned(self, wiring):
        _seed_task(wiring)
        result = _complete(wiring, id="task-0001")
        assert result["completed_at"] == wiring["clock"].now().isoformat()

    def test_unknown_id_is_not_found(self, wiring):
        with pytest.raises(ApiError) as exc_info:
            _complete(wiring, id="task-ghost")
        assert exc_info.value.code == "not_found"

    def test_missing_id_is_invalid_request(self, wiring):
        with pytest.raises(ApiError) as exc_info:
            _complete(wiring, id="")
        assert exc_info.value.code == "invalid_request"

    def test_completing_an_already_done_task_is_invalid_request(self, wiring):
        _seed_task(wiring)
        _complete(wiring, id="task-0001")
        with pytest.raises(ApiError) as exc_info:
            _complete(wiring, id="task-0001")
        assert exc_info.value.code == "invalid_request"
        # The second call's failed validation must not have published or
        # committed a second event — exactly one task.updated total.
        assert _published(wiring) == ["task.updated"]

    def test_revision_conflict_from_a_concurrent_write_is_a_conflict_error(
        self, wiring, monkeypatch
    ):
        _seed_task(wiring)

        def _always_conflicts(task):
            raise RevisionConflictError("stale revision")

        monkeypatch.setattr(wiring["store"], "update", _always_conflicts)
        with pytest.raises(ApiError) as exc_info:
            _complete(wiring, id="task-0001")
        assert exc_info.value.code == "conflict"
        assert exc_info.value.details["current_revision"] == 1
