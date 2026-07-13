"""EventLog port-contract suite — run identically against FakeEventLog and
SqliteEventLog (13 §2.3). Subclasses provide ``log`` wired to ``clock``.
"""

from __future__ import annotations

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.domain.ports.eventlog import (
    EnvelopeValidationError,
    EventEnvelope,
    EventNotFoundError,
)


def make_envelope(index: int = 0, **overrides) -> EventEnvelope:
    fields = dict(
        event_id=f"event-{index:04d}",
        type="task.created",
        occurred_at="2026-01-01T00:00:00+00:00",
        principal="kang",
        correlation_id=f"corr-{index:04d}",
        device_id="device-test",
        payload={"id": f"task-{index:04d}", "title": "prove the log"},
        recovery_grade=True,
        entity_refs=({"kind": "task", "id": f"task-{index:04d}"},),
    )
    fields.update(overrides)
    return EventEnvelope(**fields)


class EventLogContract:
    @pytest.fixture
    def clock(self) -> FakeClock:
        return FakeClock()

    # -- append ----------------------------------------------------------

    def test_append_assigns_monotonic_seq(self, log):
        assert log.append(make_envelope(0)) == 1
        assert log.append(make_envelope(1)) == 2
        assert log.last_seq() == 2

    def test_appended_events_start_pending(self, log):
        seq = log.append(make_envelope(0))
        (stored,) = log.pending()
        assert stored.seq == seq
        assert stored.state == "pending"

    def test_envelope_round_trips_every_field(self, log):
        envelope = make_envelope(0, causation_id="event-parent")
        log.append(envelope)
        (stored,) = log.pending()
        assert stored.envelope == envelope

    def test_recorded_at_comes_from_the_injected_clock(self, log, clock):
        log.append(make_envelope(0))
        (stored,) = log.pending()
        assert stored.recorded_at == clock.now().isoformat()

    # -- validation (15 §5.1 closed list; nothing invalid enters the log) --

    def test_invalid_provenance_is_rejected(self, log):
        with pytest.raises(EnvelopeValidationError, match="provenance"):
            log.append(make_envelope(0, provenance="trusted"))
        assert log.last_seq() == 0

    def test_command_shaped_type_is_rejected(self, log):
        with pytest.raises(EnvelopeValidationError, match="type"):
            log.append(make_envelope(0, type="DoTheThing"))

    def test_empty_recovery_grade_payload_is_rejected(self, log):
        with pytest.raises(EnvelopeValidationError, match="self-sufficient"):
            log.append(make_envelope(0, payload={}, recovery_grade=True))

    def test_malformed_entity_refs_are_rejected(self, log):
        with pytest.raises(EnvelopeValidationError, match="entity_refs"):
            log.append(make_envelope(0, entity_refs=({"kind": "task"},)))

    def test_empty_principal_is_rejected(self, log):
        with pytest.raises(EnvelopeValidationError, match="principal"):
            log.append(make_envelope(0, principal=""))

    # -- state machine (15 §4) --------------------------------------------

    def test_confirm_removes_from_the_pending_window(self, log):
        seq = log.append(make_envelope(0))
        log.confirm(seq)
        assert log.pending() == []

    def test_orphaned_events_leave_pending_but_are_never_deleted(self, log):
        seq = log.append(make_envelope(0))
        log.mark_orphaned(seq)
        assert log.pending() == []
        (stored,) = log.read_from(0)
        assert stored.state == "orphaned"

    def test_confirming_an_unknown_seq_raises(self, log):
        with pytest.raises(EventNotFoundError):
            log.confirm(99)

    def test_pending_window_is_oldest_first(self, log):
        for index in range(3):
            log.append(make_envelope(index))
        assert [event.seq for event in log.pending()] == [1, 2, 3]

    # -- gap-fill reads (EB-009 form 2) ------------------------------------

    def test_read_from_returns_only_events_after_the_watermark(self, log):
        for index in range(4):
            seq = log.append(make_envelope(index))
            log.confirm(seq)
        after = log.read_from(2)
        assert [event.seq for event in after] == [3, 4]

    def test_last_seq_is_zero_on_an_empty_log(self, log):
        assert log.last_seq() == 0
