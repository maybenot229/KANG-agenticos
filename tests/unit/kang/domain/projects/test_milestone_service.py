"""Milestone domain service — invariants for the milestone entity.

Claims proven here: ADR-015's tracking-only scope — a milestone can be
created with a valid project_id/title/status, invalid input is rejected
as a typed domain error before persistence, and the event payload is
self-sufficient (ADR-015/EB-003).
"""

from __future__ import annotations

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.domain.projects.milestone_service import (
    MilestoneDraft,
    MilestoneValidationError,
    create_milestone,
    mark_dropped,
    mark_missed,
    mark_reached,
    milestone_event_payload,
)


def _make(**overrides):
    draft = MilestoneDraft(
        project_id=overrides.pop("project_id", "proj-1"),
        title=overrides.pop("title", "Working prototype"),
        **overrides,
    )
    return create_milestone(draft, "ms-1", FakeClock(), device_id="device-test")


class TestCreate:
    def test_new_milestone_starts_pending_at_revision_one(self):
        milestone = _make()
        assert milestone.status == "pending"
        assert milestone.revision == 1

    def test_empty_project_id_is_rejected(self):
        with pytest.raises(MilestoneValidationError):
            _make(project_id="   ")

    def test_empty_title_is_rejected(self):
        with pytest.raises(MilestoneValidationError):
            _make(title="   ")

    def test_unknown_status_is_rejected(self):
        with pytest.raises(MilestoneValidationError):
            _make(status="bogus")

    def test_non_iso_due_is_rejected_as_a_domain_error(self):
        with pytest.raises(MilestoneValidationError):
            _make(due="next tuesday")

    def test_due_is_optional(self):
        assert _make().due is None

    @pytest.mark.parametrize("status", ["pending", "reached", "missed", "dropped"])
    def test_every_declared_status_is_accepted(self, status):
        assert _make(status=status).status == status

    def test_project_id_is_carried_through_verbatim(self):
        assert _make(project_id="proj-42").project_id == "proj-42"


class TestTransitions:
    @pytest.mark.parametrize(
        "transition,expected",
        [(mark_reached, "reached"), (mark_missed, "missed"), (mark_dropped, "dropped")],
    )
    def test_transition_from_pending_sets_status_and_updated_at(
        self, transition, expected
    ):
        milestone = _make()
        clock = FakeClock()
        clock.advance(3600)
        transitioned = transition(milestone, clock)
        assert transitioned.status == expected
        assert transitioned.updated_at == clock.now()
        assert milestone.status == "pending"  # snapshots are immutable

    @pytest.mark.parametrize("transition", [mark_reached, mark_missed, mark_dropped])
    def test_transition_from_a_non_pending_status_is_rejected(self, transition):
        reached = mark_reached(_make(), FakeClock())
        with pytest.raises(MilestoneValidationError):
            transition(reached, FakeClock())


class TestEventPayload:
    def test_payload_carries_every_column(self):
        # EB-003: recovery-grade payloads must reconstruct the row exactly
        payload = milestone_event_payload(_make())
        assert set(payload) == {
            "id",
            "project_id",
            "title",
            "due",
            "status",
            "created_at",
            "updated_at",
            "device_id",
            "revision",
        }

    def test_payload_is_json_shaped(self):
        payload = milestone_event_payload(_make())
        assert isinstance(payload["created_at"], str)
        assert isinstance(payload["revision"], int)
