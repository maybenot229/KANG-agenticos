"""Milestone API handlers — the Milestones sub-domain's first write path
(ADR-015).

The claim under test: `milestone.create` publishes `milestone.created`
(recovery-grade, full row) under `kernel:milestones`, and the write
commits only inside that publish (EB-004) — there is no path to a
committed milestone row that skips the bus.
"""

from __future__ import annotations

import itertools

import pytest

from kang.adapters.fakes.audit_log import FakeAuditLog
from kang.adapters.fakes.clock import FakeClock
from kang.adapters.fakes.delivery_store import FakeDeliveryStore
from kang.adapters.fakes.event_log import FakeEventLog
from kang.adapters.fakes.milestone_store import FakeMilestoneStore
from kang.adapters.fakes.recovery import FakeRecoveryApplier
from kang.adapters.fakes.sleeper import FakeSleeper
from kang.api.dispatch import HandlerContext
from kang.api.errors import ApiError
from kang.api.operations import (
    make_milestone_create_handler,
    make_milestone_list_handler,
)
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
        PermissionEngine({"kernel:milestones": ("events.publish:kang",)}),
        audit,
    )
    store = FakeMilestoneStore()
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


def _create(wiring, **params):
    handler = make_milestone_create_handler(
        wiring["bus"], wiring["store"], wiring["clock"], wiring["new_id"], DEVICE
    )
    return handler(wiring["context"], params)


def _list(wiring, project_id):
    handler = make_milestone_list_handler(wiring["store"])
    return handler(wiring["context"], {"project_id": project_id})


def _published(wiring) -> list[str]:
    return [s.envelope.type for s in wiring["log"].read_from(0)]


class TestCreate:
    def test_creates_and_publishes_milestone_created(self, wiring):
        result = _create(wiring, project_id="proj-1", title="Working prototype")
        stored = wiring["store"].list_for_project("proj-1")[0]
        assert stored.id == result["milestone_id"]
        assert _published(wiring) == ["milestone.created"]

    def test_created_event_is_recovery_grade_with_the_full_row(self, wiring):
        _create(wiring, project_id="proj-1", title="Working prototype")
        (stored,) = wiring["log"].read_from(0)
        assert stored.envelope.recovery_grade is True
        assert stored.envelope.payload["title"] == "Working prototype"
        assert stored.envelope.payload["project_id"] == "proj-1"
        assert stored.envelope.payload["status"] == "pending"

    def test_invalid_draft_is_an_api_error_not_a_domain_leak(self, wiring):
        with pytest.raises(ApiError):
            _create(wiring, project_id="proj-1", title="   ")

    def test_missing_project_id_is_refused(self, wiring):
        with pytest.raises(ApiError):
            _create(wiring, project_id="", title="Working prototype")

    def test_non_iso_due_is_refused(self, wiring):
        with pytest.raises(ApiError):
            _create(wiring, project_id="proj-1", title="Working prototype", due="soon")


class TestList:
    """`milestone.list` (ADR-015, tracking only). The claim: it exposes
    `MilestoneStore.list_for_project()`'s existing contract — scoped to
    one project, due-then-id ordered — verbatim."""

    def test_requires_a_project_id(self, wiring):
        handler = make_milestone_list_handler(wiring["store"])
        with pytest.raises(ApiError):
            handler(wiring["context"], {})

    def test_empty_project_lists_nothing(self, wiring):
        assert _list(wiring, "proj-1") == {"milestones": []}

    def test_lists_a_milestone_with_every_field(self, wiring):
        created = _create(
            wiring,
            project_id="proj-1",
            title="Working prototype",
            due="2026-06-01T00:00:00+00:00",
        )
        (item,) = _list(wiring, "proj-1")["milestones"]
        assert item == {
            "id": created["milestone_id"],
            "project_id": "proj-1",
            "title": "Working prototype",
            "status": "pending",
            "due": "2026-06-01T00:00:00+00:00",
        }

    def test_scoped_to_the_requested_project_only(self, wiring):
        _create(wiring, project_id="proj-1", title="A")
        _create(wiring, project_id="proj-2", title="B")
        titles = [m["title"] for m in _list(wiring, "proj-1")["milestones"]]
        assert titles == ["A"]
