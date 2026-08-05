"""Deadline API handlers — the create path and the lead-time sweep.

The claim under test is ADR-004's ordering ruling, made concrete: one
`tracked → alerted` flip publishes `deadline.updated` (carrying the state
commit) and then `deadline.approaching` (causally linked, committing
nothing) — in that order, never the reverse, never only one.
"""

from __future__ import annotations

import itertools

import pytest

from kang.adapters.fakes.audit_log import FakeAuditLog
from kang.adapters.fakes.clock import FakeClock
from kang.adapters.fakes.deadline_store import FakeDeadlineStore
from kang.adapters.fakes.delivery_store import FakeDeliveryStore
from kang.adapters.fakes.event_log import FakeEventLog
from kang.adapters.fakes.recovery import FakeRecoveryApplier
from kang.adapters.fakes.sleeper import FakeSleeper
from kang.api.dispatch import HandlerContext
from kang.api.errors import ApiError
from kang.api.operations import (
    make_deadline_create_handler,
    make_deadline_list_handler,
    make_deadline_sweep_handler,
)
from kang.kernel.audit.service import AuditService
from kang.kernel.bus.bus import EventBus
from kang.kernel.bus.delivery import Delivery
from kang.kernel.bus.reconciliation import Reconciliation
from kang.kernel.permissions.engine import PermissionEngine

DEVICE = "device-test"
AT_SOON = "2026-01-05T09:00:00+00:00"  # FakeClock starts 2026-01-01
AT_FAR = "2026-09-01T09:00:00+00:00"


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
        PermissionEngine({"kernel:deadlines": ("events.publish:kang",)}),
        audit,
    )
    store = FakeDeadlineStore(clock)
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
    handler = make_deadline_create_handler(
        wiring["bus"], wiring["store"], wiring["clock"], wiring["new_id"], DEVICE
    )
    return handler(wiring["context"], params)


def _sweep(wiring):
    handler = make_deadline_sweep_handler(
        wiring["bus"], wiring["store"], wiring["clock"], wiring["new_id"], DEVICE
    )
    return handler(wiring["context"], {})


def _list(wiring):
    handler = make_deadline_list_handler(wiring["store"])
    return handler(wiring["context"], {})


def _published(wiring) -> list[str]:
    return [s.envelope.type for s in wiring["log"].read_from(0)]


class TestCreate:
    def test_creates_and_publishes_deadline_created(self, wiring):
        result = _create(wiring, title="Submit entry", at=AT_FAR)
        assert wiring["store"].get(result["deadline_id"]).status == "tracked"
        assert _published(wiring) == ["deadline.created"]

    def test_created_event_is_recovery_grade_with_the_full_row(self, wiring):
        _create(wiring, title="Submit entry", at=AT_FAR)
        (stored,) = wiring["log"].read_from(0)
        assert stored.envelope.recovery_grade is True
        assert stored.envelope.payload["title"] == "Submit entry"
        assert stored.envelope.payload["status"] == "tracked"

    def test_invalid_draft_is_an_api_error_not_a_domain_leak(self, wiring):
        with pytest.raises(ApiError):
            _create(wiring, title="   ", at=AT_FAR)

    def test_unanchored_submission_deadline_is_refused(self, wiring):
        # 07 §5.2's anchor CHECK, surfaced as invalid_request not IntegrityError
        with pytest.raises(ApiError):
            _create(wiring, title="Submit", at=AT_FAR, kind="submission")


class TestSweepOrdering:
    def test_far_deadline_is_not_alerted(self, wiring):
        _create(wiring, title="Far off", at=AT_FAR)
        assert _sweep(wiring)["count"] == 0
        assert _published(wiring) == ["deadline.created"]

    def test_crossed_threshold_publishes_updated_then_approaching(self, wiring):
        _create(wiring, title="Due soon", at=AT_SOON)
        result = _sweep(wiring)
        assert result["count"] == 1
        # ADR-004's ruling: both events, mutation first, fact second.
        assert _published(wiring) == [
            "deadline.created",
            "deadline.updated",
            "deadline.approaching",
        ]

    def test_the_mutation_commits_the_status(self, wiring):
        created = _create(wiring, title="Due soon", at=AT_SOON)
        _sweep(wiring)
        assert wiring["store"].get(created["deadline_id"]).status == "alerted"

    def test_approaching_is_causally_linked_to_the_mutation(self, wiring):
        _create(wiring, title="Due soon", at=AT_SOON)
        _sweep(wiring)
        _, updated, approaching = wiring["log"].read_from(0)
        # 15 §5.1: causation_id is the event_id of the direct parent
        assert approaching.envelope.causation_id == updated.envelope.event_id

    def test_the_two_events_carry_the_right_recovery_grades(self, wiring):
        _create(wiring, title="Due soon", at=AT_SOON)
        _sweep(wiring)
        _, updated, approaching = wiring["log"].read_from(0)
        assert updated.envelope.recovery_grade is True  # the redo record
        assert approaching.envelope.recovery_grade is False  # a pure fact

    def test_an_alerted_deadline_is_not_swept_twice(self, wiring):
        # active() returns only `tracked`, so the second sweep finds nothing —
        # this is what keeps 09_UI §9's no-re-notification rule reachable.
        _create(wiring, title="Due soon", at=AT_SOON)
        _sweep(wiring)
        assert _sweep(wiring)["count"] == 0
        assert _published(wiring).count("deadline.approaching") == 1

    def test_sweep_is_deterministic_across_identical_state(self, wiring):
        _create(wiring, title="B", at=AT_SOON)
        _create(wiring, title="A", at=AT_SOON)
        first = _sweep(wiring)["alerted"]
        # active() orders (at, id); the sweep preserves it (13 §2.6)
        assert first == sorted(first)


class TestList:
    """`deadline.list`, added 2026-08-05 for the dashboard's Zone 2 (09_UI
    §4). The claim: it exposes `DeadlineStore.active()`'s existing contract
    — tracked-only, soonest-first — verbatim, adding no filtering or
    ordering logic of its own."""

    def test_empty_store_lists_nothing(self, wiring):
        assert _list(wiring) == {"deadlines": []}

    def test_lists_a_tracked_deadline_with_the_zone_2_fields(self, wiring):
        created = _create(wiring, title="Submit entry", at=AT_FAR, kind="custom")
        (item,) = _list(wiring)["deadlines"]
        assert item == {
            "id": created["deadline_id"],
            "title": "Submit entry",
            "at": AT_FAR,
            "kind": "custom",
            "status": "tracked",
            "competition_id": None,
            "project_id": None,
        }

    def test_alerted_deadlines_drop_off_the_list_same_as_the_sweep_sees_it(
        self, wiring
    ):
        # active() is tracked-only (TestSweepOrdering's
        # test_an_alerted_deadline_is_not_swept_twice already establishes
        # this) — this handler exposes that contract verbatim rather than
        # widening it to "tracked or alerted", so an alerted deadline drops
        # off Zone 2's horizon the same moment it stops being swept. Real,
        # existing behavior being surfaced, not new behavior introduced
        # here — worth knowing, not this handler's to change.
        _create(wiring, title="Due soon", at=AT_SOON)
        _sweep(wiring)
        assert _list(wiring) == {"deadlines": []}

    def test_soonest_first(self, wiring):
        _create(wiring, title="Later", at=AT_FAR)
        _create(wiring, title="Sooner", at=AT_SOON)
        titles = [d["title"] for d in _list(wiring)["deadlines"]]
        assert titles == ["Sooner", "Later"]
