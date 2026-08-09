"""Project domain service — invariants for the project entity.

Claims proven here: 03_ROADMAP M4/M5's "projects... tracking only"
objective — a project can be created with a valid name/status, invalid
input is rejected as a typed domain error before persistence, and the
event payload is self-sufficient (ADR-013/EB-003).
"""

from __future__ import annotations

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.domain.projects.project_service import (
    ProjectDraft,
    ProjectValidationError,
    complete_project,
    create_project,
    project_event_payload,
)


def _make(**overrides):
    draft = ProjectDraft(name=overrides.pop("name", "KANG v0.1"), **overrides)
    return create_project(draft, "proj-1", FakeClock(), device_id="device-test")


class TestCreate:
    def test_new_project_starts_active_at_revision_one(self):
        project = _make()
        assert project.status == "active"
        assert project.revision == 1

    def test_empty_name_is_rejected(self):
        with pytest.raises(ProjectValidationError):
            _make(name="   ")

    def test_unknown_status_is_rejected(self):
        with pytest.raises(ProjectValidationError):
            _make(status="bogus")

    @pytest.mark.parametrize(
        "status", ["active", "paused", "completed", "archived", "abandoned"]
    )
    def test_every_declared_status_is_accepted(self, status):
        assert _make(status=status).status == status

    def test_optional_fields_default_to_none(self):
        project = _make()
        assert project.description is None
        assert project.vault_folder is None
        assert project.github_repo is None
        assert project.goal_id is None

    def test_optional_fields_are_carried_through(self):
        project = _make(
            description="Ship the agentic OS",
            vault_folder="KANG OS",
            github_repo="maybenot229/KANG",
            goal_id="goal-1",
        )
        assert project.description == "Ship the agentic OS"
        assert project.vault_folder == "KANG OS"
        assert project.github_repo == "maybenot229/KANG"
        assert project.goal_id == "goal-1"


class TestComplete:
    def test_completes_an_active_project(self):
        project = _make()
        clock = FakeClock()
        clock.advance(3600)
        completed = complete_project(project, clock)
        assert completed.status == "completed"
        assert completed.updated_at == clock.now()
        assert project.status == "active"  # snapshots are immutable

    def test_completing_a_non_active_project_is_rejected(self):
        project = _make(status="paused")
        with pytest.raises(ProjectValidationError):
            complete_project(project, FakeClock())


class TestEventPayload:
    def test_payload_carries_every_column(self):
        # EB-003: recovery-grade payloads must reconstruct the row exactly
        payload = project_event_payload(_make())
        assert set(payload) == {
            "id",
            "name",
            "description",
            "status",
            "vault_folder",
            "github_repo",
            "goal_id",
            "created_at",
            "updated_at",
            "device_id",
            "revision",
        }

    def test_payload_is_json_shaped(self):
        payload = project_event_payload(_make())
        assert isinstance(payload["created_at"], str)
        assert isinstance(payload["revision"], int)
