"""Competition API handlers — the Competitions domain's first write path
(ADR-014).

The claim under test: `competition.create` publishes `competition.created`
(recovery-grade, full row) under `kernel:competitions`, and the write
commits only inside that publish (EB-004) — there is no path to a
committed competition row that skips the bus.
"""

from __future__ import annotations

import itertools

import pytest

from kang.adapters.fakes.audit_log import FakeAuditLog
from kang.adapters.fakes.clock import FakeClock
from kang.adapters.fakes.competition_store import FakeCompetitionStore
from kang.adapters.fakes.delivery_store import FakeDeliveryStore
from kang.adapters.fakes.event_log import FakeEventLog
from kang.adapters.fakes.recovery import FakeRecoveryApplier
from kang.adapters.fakes.sleeper import FakeSleeper
from kang.api.dispatch import HandlerContext
from kang.api.errors import ApiError
from kang.api.operations import (
    make_competition_create_handler,
    make_competition_list_handler,
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
        PermissionEngine({"kernel:competitions": ("events.publish:kang",)}),
        audit,
    )
    store = FakeCompetitionStore()
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
    handler = make_competition_create_handler(
        wiring["bus"], wiring["store"], wiring["clock"], wiring["new_id"], DEVICE
    )
    return handler(wiring["context"], params)


def _list(wiring):
    handler = make_competition_list_handler(wiring["store"])
    return handler(wiring["context"], {})


def _published(wiring) -> list[str]:
    return [s.envelope.type for s in wiring["log"].read_from(0)]


class TestCreate:
    def test_creates_and_publishes_competition_created(self, wiring):
        result = _create(wiring, name="USACO")
        assert wiring["store"].list_all()[0].id == result["competition_id"]
        assert _published(wiring) == ["competition.created"]

    def test_created_event_is_recovery_grade_with_the_full_row(self, wiring):
        _create(wiring, name="USACO")
        (stored,) = wiring["log"].read_from(0)
        assert stored.envelope.recovery_grade is True
        assert stored.envelope.payload["name"] == "USACO"
        assert stored.envelope.payload["status"] == "discovered"
        assert stored.envelope.payload["evaluation"] is None
        assert stored.envelope.payload["result"] is None

    def test_invalid_draft_is_an_api_error_not_a_domain_leak(self, wiring):
        with pytest.raises(ApiError):
            _create(wiring, name="   ")

    def test_unknown_status_is_refused(self, wiring):
        with pytest.raises(ApiError):
            _create(wiring, name="USACO", status="bogus")

    def test_optional_fields_round_trip(self, wiring):
        result = _create(wiring, name="USACO", url="https://usaco.org")
        stored = wiring["store"].list_all()[0]
        assert stored.id == result["competition_id"]
        assert stored.url == "https://usaco.org"


class TestList:
    """`competition.list` (ADR-014, tracking only). The claim: it exposes
    `CompetitionStore.list_all()`'s existing contract — name-then-id
    ordered — verbatim, adding no filtering or ordering logic of its own."""

    def test_empty_store_lists_nothing(self, wiring):
        assert _list(wiring) == {"competitions": []}

    def test_lists_a_competition_with_every_field(self, wiring):
        created = _create(wiring, name="USACO", url="https://usaco.org")
        (item,) = _list(wiring)["competitions"]
        assert item == {
            "id": created["competition_id"],
            "name": "USACO",
            "status": "discovered",
            "url": "https://usaco.org",
            "evaluation": None,
            "result": None,
            "project_id": None,
        }

    def test_name_then_id_ordering(self, wiring):
        _create(wiring, name="Zebra open")
        _create(wiring, name="alpha open")
        names = [c["name"] for c in _list(wiring)["competitions"]]
        assert names == ["alpha open", "Zebra open"]
