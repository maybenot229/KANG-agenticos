"""Fan-out re-entrancy — a subscriber MAY publish (15 §5.1's causation_id
defines the parent of an event that "exists because a handler/job reacted to
another event", so reacting-by-publishing is the designed case).

Regression guard. `Delivery.deliver` calls the handler BEFORE advancing the
cursor, because the advance is the at-least-once ack (EB-007.2). A naive
nested fan-out therefore re-reads the event still in flight and recurses
without bound — which hangs the process rather than failing loudly. This
suite pins the guard so the defect cannot return silently.
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
from kang.kernel.bus.bus import EventBus, FanOutDepthExceeded, Subscriber
from kang.kernel.bus.delivery import Delivery
from kang.kernel.bus.reconciliation import Reconciliation
from kang.kernel.permissions.engine import PermissionEngine
from tests.fixtures.event_log_contract import make_envelope, task_payload

GRANTS = {"kang": ("events.publish:kang",)}


def _bus(subscribers):
    clock = FakeClock()
    event_log = FakeEventLog(clock)
    audit = AuditService(FakeAuditLog(), clock)
    ids = (f"dl-{n}" for n in itertools.count())
    return (
        EventBus(
            event_log,
            Delivery(
                event_log,
                FakeDeliveryStore(clock),
                audit,
                dead_letter_id=lambda: next(ids),
                sleeper=FakeSleeper(),
            ),
            Reconciliation(event_log, FakeRecoveryApplier(), audit, clock),
            PermissionEngine(GRANTS),
            audit,
            subscribers,
        ),
        event_log,
    )


def test_a_handler_may_publish_without_recursing_forever():
    """The defect this guards: before the fix, this test hung the process."""
    seen: list[str] = []
    reacted: list[str] = []
    bus_holder: dict = {}

    def reactor(envelope):
        seen.append(envelope.type)
        if envelope.type == "task.created" and not reacted:
            reacted.append(envelope.event_id)
            bus_holder["bus"].publish(
                make_envelope(
                    9,
                    type="task.updated",
                    payload=task_payload(9, status="done", revision=2),
                    causation_id=envelope.event_id,
                ),
                commit_state=lambda: None,
            )

    bus, event_log = _bus([Subscriber("reactor", reactor)])
    bus_holder["bus"] = bus
    bus.publish(make_envelope(0), commit_state=lambda: None)

    # both events landed in the log, and the reaction was delivered too
    assert [s.envelope.type for s in event_log.read_from(0)] == [
        "task.created",
        "task.updated",
    ]
    assert seen == ["task.created", "task.updated"]


def test_the_reaction_is_delivered_within_the_same_fan_out():
    """Not deferred to the next publish: the drain loop keeps going until no
    subscriber advanced, so a reaction reaches every subscriber promptly."""
    downstream: list[str] = []
    bus_holder: dict = {}

    def reactor(envelope):
        if envelope.type == "task.created":
            bus_holder["bus"].publish(
                make_envelope(
                    9,
                    type="task.updated",
                    payload=task_payload(9, status="done", revision=2),
                    causation_id=envelope.event_id,
                ),
                commit_state=lambda: None,
            )

    bus, _ = _bus(
        [
            Subscriber("reactor", reactor),
            Subscriber("downstream", lambda e: downstream.append(e.type)),
        ]
    )
    bus_holder["bus"] = bus
    bus.publish(make_envelope(0), commit_state=lambda: None)
    assert downstream == ["task.created", "task.updated"]


def test_a_quiet_stream_terminates():
    """No subscriber advancing ends the loop — the termination condition."""
    bus, _ = _bus([Subscriber("noop", lambda e: None)])
    bus.publish(make_envelope(0), commit_state=lambda: None)
    assert bus.pending_count() == 0


def test_an_endlessly_publishing_handler_fails_loudly_and_is_bounded():
    """The drain loop is bounded INDEPENDENTLY of EB-011.2.

    This handler republishes forever WITHOUT threading causation_id, so
    `causation_depth` sees 0 every time and the depth guard never fires —
    the exact case where relying on EB-011.2 alone would spin forever. The
    fan-out's own pass cap must stop it, and stop it LOUDLY: a bus that
    silently quits draining silently drops notifications (SEC-009).
    """
    counter = itertools.count(100)
    bus_holder: dict = {}

    def loop_forever(envelope):
        index = next(counter)
        bus_holder["bus"].publish(
            make_envelope(index, type="task.updated", payload=task_payload(index)),
            commit_state=lambda: None,
        )  # note: no causation_id — the depth guard cannot see this chain

    bus, _ = _bus([Subscriber("looper", loop_forever)])
    bus_holder["bus"] = bus
    with pytest.raises(FanOutDepthExceeded):
        bus.publish(make_envelope(0), commit_state=lambda: None)


def test_two_independent_reaction_chains_keep_per_subscriber_seq_order():
    """EB-007.2: delivery to one subscriber is strictly FIFO by seq.

    Two independent publishers each trigger their own reaction, interleaved
    in the same drain window. Per-subscriber ordering must still be
    ascending seq — the guarantee EB-007 actually makes. (Cross-subscriber
    interleaving is explicitly NOT guaranteed, EB-007.3, so this asserts
    per-subscriber order only.)
    """
    observer_seqs: list[int] = []
    bus_holder: dict = {}
    reacted: set[str] = set()

    def reactor(envelope):
        # each of the two roots spawns exactly one reaction
        if envelope.type == "task.created" and envelope.event_id not in reacted:
            reacted.add(envelope.event_id)
            index = 50 + len(reacted)
            bus_holder["bus"].publish(
                make_envelope(
                    index,
                    type="task.updated",
                    payload=task_payload(index),
                    causation_id=envelope.event_id,
                ),
                commit_state=lambda: None,
            )

    def observer(envelope):
        observer_seqs.append(envelope.event_id)

    bus, event_log = _bus(
        [Subscriber("reactor", reactor), Subscriber("observer", observer)]
    )
    bus_holder["bus"] = bus

    bus.publish(make_envelope(0), commit_state=lambda: None)  # root A (+reaction)
    bus.publish(make_envelope(1), commit_state=lambda: None)  # root B (+reaction)

    # the observer saw every event exactly once, in ascending seq order
    log_order = [s.envelope.event_id for s in event_log.read_from(0)]
    assert observer_seqs == log_order
    assert len(observer_seqs) == 4  # two roots + two reactions
    assert len(set(observer_seqs)) == 4  # no duplicate delivery
