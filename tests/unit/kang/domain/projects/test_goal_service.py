"""Goal domain service — invariants for the goal entity.

Claims proven here: ADR-016's "goal.create... tracking only" scope — a
goal can be created with a valid title/horizon/status, invalid input is
rejected as a typed domain error before persistence, and the event
payload is self-sufficient (ADR-016/EB-003).
"""

from __future__ import annotations

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.domain.projects.goal_service import (
    GoalDraft,
    GoalValidationError,
    achieve_goal,
    create_goal,
    goal_event_payload,
    retire_goal,
    revise_goal,
)


def _make(**overrides):
    draft = GoalDraft(
        title=overrides.pop("title", "Ship KANG v0.1"),
        horizon=overrides.pop("horizon", "quarter"),
        **overrides,
    )
    return create_goal(draft, "goal-1", FakeClock(), device_id="device-test")


class TestCreate:
    def test_new_goal_starts_active_at_revision_one(self):
        goal = _make()
        assert goal.status == "active"
        assert goal.revision == 1

    def test_empty_title_is_rejected(self):
        with pytest.raises(GoalValidationError):
            _make(title="   ")

    def test_unknown_horizon_is_rejected(self):
        with pytest.raises(GoalValidationError):
            _make(horizon="bogus")

    def test_unknown_status_is_rejected(self):
        with pytest.raises(GoalValidationError):
            _make(status="bogus")

    @pytest.mark.parametrize("horizon", ["quarter", "year", "life"])
    def test_every_declared_horizon_is_accepted(self, horizon):
        assert _make(horizon=horizon).horizon == horizon

    @pytest.mark.parametrize("status", ["active", "achieved", "revised", "retired"])
    def test_every_declared_status_is_accepted(self, status):
        assert _make(status=status).status == status

    def test_optional_fields_default_to_none(self):
        goal = _make()
        assert goal.description is None

    def test_optional_fields_are_carried_through(self):
        goal = _make(description="First real milestone for the OS")
        assert goal.description == "First real milestone for the OS"


class TestTransitions:
    @pytest.mark.parametrize(
        "transition,expected",
        [
            (achieve_goal, "achieved"),
            (revise_goal, "revised"),
            (retire_goal, "retired"),
        ],
    )
    def test_transition_from_active_sets_status_and_updated_at(
        self, transition, expected
    ):
        goal = _make()
        clock = FakeClock()
        clock.advance(3600)
        transitioned = transition(goal, clock)
        assert transitioned.status == expected
        assert transitioned.updated_at == clock.now()
        assert goal.status == "active"  # snapshots are immutable

    @pytest.mark.parametrize("transition", [achieve_goal, revise_goal, retire_goal])
    def test_transition_from_a_non_active_status_is_rejected(self, transition):
        achieved = achieve_goal(_make(), FakeClock())
        with pytest.raises(GoalValidationError):
            transition(achieved, FakeClock())


class TestEventPayload:
    def test_payload_carries_every_column(self):
        # EB-003: recovery-grade payloads must reconstruct the row exactly
        payload = goal_event_payload(_make())
        assert set(payload) == {
            "id",
            "title",
            "description",
            "horizon",
            "status",
            "created_at",
            "updated_at",
            "device_id",
            "revision",
        }

    def test_payload_is_json_shaped(self):
        payload = goal_event_payload(_make())
        assert isinstance(payload["created_at"], str)
        assert isinstance(payload["revision"], int)
