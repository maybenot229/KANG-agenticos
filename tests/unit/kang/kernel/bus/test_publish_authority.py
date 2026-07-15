"""Publish authority on the bus (EB-010 checkpoint 1) — closes the M2
deferred `events.publish:{ns}` gap.

Proves: publishing without the `events.publish:{namespace}` grant is denied
at step 1, and nothing is appended (default-deny; an unauthorized publish
never enters the log). An authorized principal publishes normally.
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
from kang.kernel.audit.service import AuditService
from kang.kernel.bus.bus import EventBus, Subscriber
from kang.kernel.bus.delivery import Delivery
from kang.kernel.bus.reconciliation import Reconciliation
from kang.kernel.permissions.engine import PermissionDenied, PermissionEngine
from tests.fixtures.event_log_contract import make_envelope


def _build_bus(grants) -> tuple[EventBus, FakeEventLog, list, FakeAuditLog]:
    clock = FakeClock()
    event_log = FakeEventLog(clock)
    audit_log = FakeAuditLog()
    audit = AuditService(audit_log, clock)
    ids = (f"dl-{n}" for n in itertools.count())
    delivery = Delivery(
        event_log,
        FakeDeliveryStore(clock),
        audit,
        dead_letter_id=lambda: next(ids),
        sleeper=FakeSleeper(),
    )
    reconciliation = Reconciliation(event_log, FakeRecoveryApplier(), audit, clock)
    delivered: list[str] = []
    bus = EventBus(
        event_log,
        delivery,
        reconciliation,
        PermissionEngine(grants),
        audit,
        [Subscriber("recorder", lambda env: delivered.append(env.event_id))],
    )
    return bus, event_log, delivered, audit_log


def test_publish_without_the_grant_is_denied_and_nothing_is_appended():
    bus, event_log, delivered, audit_log = _build_bus({"agent:rogue": ()})
    envelope = make_envelope(0, principal="agent:rogue")
    committed = {"ran": False}
    with pytest.raises(PermissionDenied, match="events.publish:kang"):
        bus.publish(envelope, commit_state=lambda: committed.__setitem__("ran", True))
    assert event_log.last_seq() == 0  # nothing entered the log
    assert committed["ran"] is False  # state commit never ran
    assert delivered == []
    # the denial is audited, never silent (05 §8, SEC-006)
    records = list(audit_log.records(make_envelope(0).occurred_at[:7]))
    assert [r.entry.action for r in records] == ["events.publish.denied"]
    assert records[0].entry.principal == "agent:rogue"


def test_publish_with_the_core_namespace_grant_succeeds():
    bus, event_log, delivered, _ = _build_bus({"kernel:bus": ("events.publish:kang",)})
    envelope = make_envelope(0, principal="kernel:bus")
    seq = bus.publish(envelope, commit_state=lambda: None)
    assert seq == 1
    assert delivered == [envelope.event_id]


def test_grant_for_a_different_namespace_does_not_authorize_core():
    bus, event_log, _, _ = _build_bus({"plugin:x": ("events.publish:plugin.x",)})
    envelope = make_envelope(0, principal="plugin:x")  # core type task.created
    with pytest.raises(PermissionDenied, match="events.publish:kang"):
        bus.publish(envelope, commit_state=lambda: None)
    assert event_log.last_seq() == 0


def test_kang_wildcard_may_publish_core():
    bus, _, delivered, _ = _build_bus({"kang": ("*",)})
    envelope = make_envelope(0, principal="kang")
    bus.publish(envelope, commit_state=lambda: None)
    assert delivered == [envelope.event_id]
