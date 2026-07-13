"""Delivery (EB-007): per-subscriber cursors, FIFO, retries, dead letters.

Includes the poison-event obligation (§16.4): a permanently failing handler
dead-letters at attempt 5 and its subscriber's stream continues past it;
siblings never observe the failure.
"""

from __future__ import annotations

import itertools

import pytest

from kang.adapters.fakes.audit_log import FakeAuditLog
from kang.adapters.fakes.clock import FakeClock
from kang.adapters.fakes.delivery_store import FakeDeliveryStore
from kang.adapters.fakes.event_log import FakeEventLog
from kang.kernel.audit.service import AuditService
from kang.kernel.bus.delivery import MAX_ATTEMPTS, Delivery, retry_delay_seconds
from tests.fixtures.event_log_contract import make_envelope


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def event_log(clock) -> FakeEventLog:
    return FakeEventLog(clock)


@pytest.fixture
def delivery_store(clock) -> FakeDeliveryStore:
    return FakeDeliveryStore(clock)


@pytest.fixture
def delivery(event_log, delivery_store, clock) -> Delivery:
    ids = (f"dl-{n}" for n in itertools.count())
    return Delivery(
        event_log,
        delivery_store,
        AuditService(FakeAuditLog(), clock),
        clock,
        dead_letter_id=lambda: next(ids),
    )


def _confirm_all(event_log):
    for stored in event_log.pending():
        event_log.confirm(stored.seq)


def test_delivers_confirmed_events_in_seq_order(delivery, event_log):
    for index in range(3):
        event_log.append(make_envelope(index))
    _confirm_all(event_log)
    seen = []
    delivery.deliver("s", lambda env: seen.append(env.event_id))
    assert seen == ["event-0000", "event-0001", "event-0002"]


def test_cursor_advances_so_redelivery_does_not_repeat(delivery, event_log):
    event_log.append(make_envelope(0))
    _confirm_all(event_log)
    seen = []
    delivery.deliver("s", lambda env: seen.append(env.event_id))
    delivery.deliver("s", lambda env: seen.append(env.event_id))
    assert seen == ["event-0000"]  # second sweep delivers nothing new


def test_pending_event_stops_the_sweep_to_preserve_fifo(delivery, event_log):
    event_log.append(make_envelope(0))  # seq 1
    event_log.append(make_envelope(1))  # seq 2
    event_log.confirm(2)  # seq 2 confirmed, seq 1 still pending
    seen = []
    delivery.deliver("s", lambda env: seen.append(env.event_id))
    assert seen == []  # stopped at the pending seq-1, never skipped ahead to 2


def test_orphaned_event_is_never_delivered_but_cursor_advances(delivery, event_log):
    seq = event_log.append(make_envelope(0))
    event_log.mark_orphaned(seq)
    seen = []
    advanced = delivery.deliver("s", lambda env: seen.append(env.event_id))
    assert seen == []
    assert advanced == 1  # advanced past the orphan


def test_cursors_are_independent_per_subscriber(delivery, event_log):
    event_log.append(make_envelope(0))
    _confirm_all(event_log)
    a_seen, b_seen = [], []
    delivery.deliver("a", lambda env: a_seen.append(env.event_id))
    delivery.deliver("b", lambda env: b_seen.append(env.event_id))
    assert a_seen == b_seen == ["event-0000"]


def test_poison_event_dead_letters_and_stream_continues(
    delivery, event_log, delivery_store
):
    for index in range(3):
        event_log.append(make_envelope(index))
    _confirm_all(event_log)
    attempts = {"count": 0}

    def handler(env):
        if env.event_id == "event-0001":
            attempts["count"] += 1
            raise RuntimeError("poison")

    delivered = []
    original = handler

    def recording(env):
        if env.event_id != "event-0001":
            delivered.append(env.event_id)
        original(env)

    delivery.deliver("s", recording)
    # poison event tried exactly MAX_ATTEMPTS, then dead-lettered
    assert attempts["count"] == MAX_ATTEMPTS
    dead = delivery_store.dead_letters()
    assert len(dead) == 1 and dead[0].event_seq == 2
    # the stream continued past it
    assert delivered == ["event-0000", "event-0002"]
    # cursor advanced to the end despite the poison
    assert delivery_store.cursor("s") == 3


def test_retry_delay_is_exponential():
    delays = [retry_delay_seconds(n) for n in range(1, 5)]
    assert delays == [0.5, 1.0, 2.0, 4.0]
    with pytest.raises(ValueError):
        retry_delay_seconds(0)
