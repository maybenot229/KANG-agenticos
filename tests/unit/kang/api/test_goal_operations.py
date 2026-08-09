"""Goal API handlers — the entity's first write path (ADR-016).

The claim under test: `goal.create` publishes `goal.created`
(recovery-grade, full row) under `kernel:goals`, and the write commits
only inside that publish (EB-004) — there is no path to a committed goal
row that skips the bus.
"""

from __future__ import annotations

import itertools

import pytest

from kang.adapters.fakes.audit_log import FakeAuditLog
from kang.adapters.fakes.clock import FakeClock
from kang.adapters.fakes.delivery_store import FakeDeliveryStore
from kang.adapters.fakes.event_log import FakeEventLog
from kang.adapters.fakes.goal_store import FakeGoalStore
from kang.adapters.fakes.recovery import FakeRecoveryApplier
from kang.adapters.fakes.sleeper import FakeSleeper
from kang.api.dispatch import HandlerContext
from kang.api.errors import ApiError
from kang.api.operations import (
    make_goal_achieve_handler,
    make_goal_create_handler,
    make_goal_list_handler,
    make_goal_retire_handler,
    make_goal_revise_handler,
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
        PermissionEngine({"kernel:goals": ("events.publish:kang",)}),
        audit,
    )
    store = FakeGoalStore(clock)
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
    handler = make_goal_create_handler(
        wiring["bus"], wiring["store"], wiring["clock"], wiring["new_id"], DEVICE
    )
    return handler(wiring["context"], params)


def _list(wiring):
    handler = make_goal_list_handler(wiring["store"])
    return handler(wiring["context"], {})


def _published(wiring) -> list[str]:
    return [s.envelope.type for s in wiring["log"].read_from(0)]


def _achieve(wiring, **params):
    handler = make_goal_achieve_handler(
        wiring["bus"], wiring["store"], wiring["clock"], wiring["new_id"], DEVICE
    )
    return handler(wiring["context"], params)


def _revise(wiring, **params):
    handler = make_goal_revise_handler(
        wiring["bus"], wiring["store"], wiring["clock"], wiring["new_id"], DEVICE
    )
    return handler(wiring["context"], params)


def _retire(wiring, **params):
    handler = make_goal_retire_handler(
        wiring["bus"], wiring["store"], wiring["clock"], wiring["new_id"], DEVICE
    )
    return handler(wiring["context"], params)


class TestCreate:
    def test_creates_and_publishes_goal_created(self, wiring):
        result = _create(wiring, title="Ship KANG v0.1", horizon="quarter")
        assert wiring["store"].list_all()[0].id == result["goal_id"]
        assert _published(wiring) == ["goal.created"]

    def test_created_event_is_recovery_grade_with_the_full_row(self, wiring):
        _create(wiring, title="Ship KANG v0.1", horizon="quarter")
        (stored,) = wiring["log"].read_from(0)
        assert stored.envelope.recovery_grade is True
        assert stored.envelope.payload["title"] == "Ship KANG v0.1"
        assert stored.envelope.payload["horizon"] == "quarter"
        assert stored.envelope.payload["status"] == "active"

    def test_invalid_draft_is_an_api_error_not_a_domain_leak(self, wiring):
        with pytest.raises(ApiError):
            _create(wiring, title="   ", horizon="quarter")

    def test_missing_horizon_is_refused(self, wiring):
        with pytest.raises(ApiError):
            _create(wiring, title="Ship KANG v0.1")

    def test_unknown_horizon_is_refused(self, wiring):
        with pytest.raises(ApiError):
            _create(wiring, title="Ship KANG v0.1", horizon="bogus")

    def test_unknown_status_is_refused(self, wiring):
        with pytest.raises(ApiError):
            _create(wiring, title="Ship KANG v0.1", horizon="quarter", status="bogus")

    def test_optional_fields_round_trip(self, wiring):
        result = _create(
            wiring,
            title="Ship KANG v0.1",
            horizon="quarter",
            description="This quarter's aim",
        )
        stored = wiring["store"].list_all()[0]
        assert stored.id == result["goal_id"]
        assert stored.description == "This quarter's aim"


class TestList:
    """`goal.list` (ADR-016, tracking only). The claim: it exposes
    `GoalStore.list_all()`'s existing contract — title-then-id ordered —
    verbatim, adding no filtering or ordering logic of its own."""

    def test_empty_store_lists_nothing(self, wiring):
        assert _list(wiring) == {"goals": []}

    def test_lists_a_goal_with_every_field(self, wiring):
        created = _create(
            wiring,
            title="Ship KANG v0.1",
            horizon="quarter",
            description="This quarter's aim",
        )
        (item,) = _list(wiring)["goals"]
        assert item == {
            "id": created["goal_id"],
            "title": "Ship KANG v0.1",
            "horizon": "quarter",
            "status": "active",
            "description": "This quarter's aim",
        }

    def test_title_then_id_ordering(self, wiring):
        _create(wiring, title="Zebra goal", horizon="year")
        _create(wiring, title="alpha goal", horizon="year")
        titles = [g["title"] for g in _list(wiring)["goals"]]
        assert titles == ["alpha goal", "Zebra goal"]


class TestAchieveReviseRetire:
    """`goal.achieve`/`.revise`/`.retire` (ADR-018). Each transitions
    `active -> <terminal>`, publishing the newly-registered `goal.updated`
    under `kernel:goals`."""

    @pytest.mark.parametrize(
        "call,expected_status",
        [(_achieve, "achieved"), (_revise, "revised"), (_retire, "retired")],
    )
    def test_transitions_and_publishes_goal_updated(
        self, wiring, call, expected_status
    ):
        created = _create(wiring, title="Ship KANG v0.1", horizon="quarter")
        result = call(wiring, id=created["goal_id"])
        assert result["revision"] == 2
        assert wiring["store"].get(created["goal_id"]).status == expected_status
        assert _published(wiring) == ["goal.created", "goal.updated"]

    def test_unknown_id_is_not_found(self, wiring):
        with pytest.raises(ApiError) as exc_info:
            _achieve(wiring, id="goal-ghost")
        assert exc_info.value.code == "not_found"

    def test_achieving_a_non_active_goal_is_invalid_request(self, wiring):
        created = _create(wiring, title="Ship KANG v0.1", horizon="quarter")
        _achieve(wiring, id=created["goal_id"])
        with pytest.raises(ApiError) as exc_info:
            _achieve(wiring, id=created["goal_id"])
        assert exc_info.value.code == "invalid_request"
