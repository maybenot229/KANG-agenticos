"""Project API handlers — the Projects domain's first write path (ADR-013).

The claim under test: `project.create` publishes `project.created`
(recovery-grade, full row) under `kernel:projects`, and the write commits
only inside that publish (EB-004) — there is no path to a committed
project row that skips the bus.
"""

from __future__ import annotations

import itertools

import pytest

from kang.adapters.fakes.audit_log import FakeAuditLog
from kang.adapters.fakes.clock import FakeClock
from kang.adapters.fakes.delivery_store import FakeDeliveryStore
from kang.adapters.fakes.event_log import FakeEventLog
from kang.adapters.fakes.project_store import FakeProjectStore
from kang.adapters.fakes.recovery import FakeRecoveryApplier
from kang.adapters.fakes.sleeper import FakeSleeper
from kang.api.dispatch import HandlerContext
from kang.api.errors import ApiError
from kang.api.operations import (
    make_project_complete_handler,
    make_project_create_handler,
    make_project_list_handler,
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
        PermissionEngine({"kernel:projects": ("events.publish:kang",)}),
        audit,
    )
    store = FakeProjectStore(clock)
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
    handler = make_project_create_handler(
        wiring["bus"], wiring["store"], wiring["clock"], wiring["new_id"], DEVICE
    )
    return handler(wiring["context"], params)


def _list(wiring):
    handler = make_project_list_handler(wiring["store"])
    return handler(wiring["context"], {})


def _published(wiring) -> list[str]:
    return [s.envelope.type for s in wiring["log"].read_from(0)]


def _complete(wiring, **params):
    handler = make_project_complete_handler(
        wiring["bus"], wiring["store"], wiring["clock"], wiring["new_id"], DEVICE
    )
    return handler(wiring["context"], params)


class TestCreate:
    def test_creates_and_publishes_project_created(self, wiring):
        result = _create(wiring, name="KANG v0.1")
        assert wiring["store"].list_all()[0].id == result["project_id"]
        assert _published(wiring) == ["project.created"]

    def test_created_event_is_recovery_grade_with_the_full_row(self, wiring):
        _create(wiring, name="KANG v0.1")
        (stored,) = wiring["log"].read_from(0)
        assert stored.envelope.recovery_grade is True
        assert stored.envelope.payload["name"] == "KANG v0.1"
        assert stored.envelope.payload["status"] == "active"

    def test_invalid_draft_is_an_api_error_not_a_domain_leak(self, wiring):
        with pytest.raises(ApiError):
            _create(wiring, name="   ")

    def test_unknown_status_is_refused(self, wiring):
        with pytest.raises(ApiError):
            _create(wiring, name="KANG v0.1", status="bogus")

    def test_optional_fields_round_trip(self, wiring):
        result = _create(
            wiring,
            name="KANG v0.1",
            description="Ship the agentic OS",
            github_repo="maybenot229/KANG",
        )
        stored = wiring["store"].list_all()[0]
        assert stored.id == result["project_id"]
        assert stored.description == "Ship the agentic OS"
        assert stored.github_repo == "maybenot229/KANG"


class TestList:
    """`project.list` (ADR-013, tracking only). The claim: it exposes
    `ProjectStore.list_all()`'s existing contract — name-then-id ordered
    — verbatim, adding no filtering or ordering logic of its own."""

    def test_empty_store_lists_nothing(self, wiring):
        assert _list(wiring) == {"projects": []}

    def test_lists_a_project_with_every_field(self, wiring):
        created = _create(wiring, name="KANG v0.1", description="Ship it")
        (item,) = _list(wiring)["projects"]
        assert item == {
            "id": created["project_id"],
            "name": "KANG v0.1",
            "status": "active",
            "description": "Ship it",
            "vault_folder": None,
            "github_repo": None,
            "goal_id": None,
        }

    def test_name_then_id_ordering(self, wiring):
        _create(wiring, name="Zebra project")
        _create(wiring, name="alpha project")
        names = [p["name"] for p in _list(wiring)["projects"]]
        assert names == ["alpha project", "Zebra project"]


class TestComplete:
    """`project.complete` (ADR-018): `active -> completed`, publishing
    the newly-registered `project.updated` under `kernel:projects`."""

    def test_completes_and_publishes_project_updated(self, wiring):
        created = _create(wiring, name="KANG v0.1")
        result = _complete(wiring, id=created["project_id"])
        assert result["revision"] == 2
        assert wiring["store"].get(created["project_id"]).status == "completed"
        assert _published(wiring) == ["project.created", "project.updated"]

    def test_unknown_id_is_not_found(self, wiring):
        with pytest.raises(ApiError) as exc_info:
            _complete(wiring, id="proj-ghost")
        assert exc_info.value.code == "not_found"

    def test_completing_a_non_active_project_is_invalid_request(self, wiring):
        created = _create(wiring, name="KANG v0.1")
        _complete(wiring, id=created["project_id"])
        with pytest.raises(ApiError) as exc_info:
            _complete(wiring, id=created["project_id"])
        assert exc_info.value.code == "invalid_request"
