"""Deadline domain service — invariants, transitions, lead-threshold math.

Claims proven here: FR-030 (deadlines are tracked with their alert
schedule), FR-031 (lead-time alerting is configurable and deterministic),
07 §5.2's anchor CHECK expressed as a typed domain error before it can
become an sqlite IntegrityError.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.domain.deadlines import (
    DeadlineDraft,
    DeadlineValidationError,
    create_deadline,
    deadline_event_payload,
    due_lead_thresholds,
    mark_alerted,
    mark_met,
    mark_missed,
)

AT = "2026-03-01T09:00:00+00:00"
AT_MOMENT = datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc)


def _make(**overrides):
    draft = DeadlineDraft(
        title=overrides.pop("title", "Submit entry"),
        at=overrides.pop("at", AT),
        kind=overrides.pop("kind", "custom"),
        **overrides,
    )
    return create_deadline(draft, "dl-1", FakeClock(), device_id="device-test")


class TestCreate:
    def test_new_deadline_starts_tracked_at_revision_one(self):
        deadline = _make()
        assert deadline.status == "tracked"
        assert deadline.revision == 1

    def test_lead_days_are_stored_descending(self):
        deadline = _make(lead_days=(1, 14, 3, 7))
        assert deadline.lead_days == (14, 7, 3, 1)

    def test_empty_title_is_rejected(self):
        with pytest.raises(DeadlineValidationError):
            _make(title="   ")

    def test_unknown_kind_is_rejected(self):
        with pytest.raises(DeadlineValidationError):
            _make(kind="bogus")

    def test_non_iso_at_is_rejected_as_a_domain_error(self):
        with pytest.raises(DeadlineValidationError):
            _make(at="next tuesday")

    def test_negative_lead_days_rejected(self):
        with pytest.raises(DeadlineValidationError):
            _make(lead_days=(7, -1))

    def test_duplicate_lead_days_rejected(self):
        with pytest.raises(DeadlineValidationError):
            _make(lead_days=(7, 7, 1))

    def test_submission_deadline_needs_an_anchor(self):
        # 07 §5.2's CHECK, enforced in the domain first (11 §9: typed error)
        with pytest.raises(DeadlineValidationError):
            _make(kind="submission")

    def test_submission_deadline_with_a_competition_is_valid(self):
        deadline = _make(kind="submission", competition_id="comp-1")
        assert deadline.competition_id == "comp-1"

    @pytest.mark.parametrize("kind", ["school", "custom"])
    def test_self_standing_kinds_need_no_anchor(self, kind):
        assert _make(kind=kind).kind == kind


class TestLeadThresholds:
    def test_nothing_due_when_far_out(self):
        deadline = _make()
        assert due_lead_thresholds(deadline, AT_MOMENT - timedelta(days=30)) == ()

    def test_largest_threshold_crosses_first(self):
        deadline = _make()
        assert due_lead_thresholds(deadline, AT_MOMENT - timedelta(days=10)) == (14,)

    def test_thresholds_accumulate_as_the_date_nears(self):
        deadline = _make()
        crossed = due_lead_thresholds(deadline, AT_MOMENT - timedelta(days=2))
        assert crossed == (14, 7, 3)

    def test_all_thresholds_crossed_at_the_deadline(self):
        deadline = _make()
        assert due_lead_thresholds(deadline, AT_MOMENT) == (14, 7, 3, 1)

    def test_all_thresholds_crossed_after_the_deadline(self):
        deadline = _make()
        assert due_lead_thresholds(deadline, AT_MOMENT + timedelta(days=5)) == (
            14,
            7,
            3,
            1,
        )

    def test_is_pure_across_repeated_calls(self):
        # determinism (13 §2.6): same inputs, same answer, no hidden state
        deadline = _make()
        now = AT_MOMENT - timedelta(days=5)
        assert due_lead_thresholds(deadline, now) == due_lead_thresholds(deadline, now)


class TestTransitions:
    def test_tracked_to_alerted(self):
        assert mark_alerted(_make()).status == "alerted"

    def test_alerting_twice_is_rejected(self):
        alerted = mark_alerted(_make())
        with pytest.raises(DeadlineValidationError):
            mark_alerted(alerted)

    def test_tracked_to_met(self):
        assert mark_met(_make()).status == "met"

    def test_alerted_to_met(self):
        assert mark_met(mark_alerted(_make())).status == "met"

    def test_tracked_to_missed(self):
        assert mark_missed(_make()).status == "missed"

    def test_met_deadline_cannot_be_missed(self):
        met = mark_met(_make())
        with pytest.raises(DeadlineValidationError):
            mark_missed(met)

    def test_transitions_do_not_mutate_the_input(self):
        deadline = _make()
        mark_alerted(deadline)
        assert deadline.status == "tracked"


class TestEventPayload:
    def test_payload_carries_every_column(self):
        # EB-003: recovery-grade payloads must reconstruct the row exactly
        payload = deadline_event_payload(_make())
        assert set(payload) == {
            "id",
            "competition_id",
            "project_id",
            "kind",
            "title",
            "at",
            "lead_days",
            "status",
            "created_at",
            "updated_at",
            "device_id",
            "revision",
        }

    def test_payload_is_json_shaped(self):
        payload = deadline_event_payload(_make())
        assert isinstance(payload["lead_days"], list)
        assert isinstance(payload["created_at"], str)
