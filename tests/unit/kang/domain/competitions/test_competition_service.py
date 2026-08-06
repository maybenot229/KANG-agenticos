"""Competition domain service — invariants for the competition entity.

Claims proven here: 03_ROADMAP M4/M5's "competitions... tracking only"
objective — a competition can be created with a valid name/status, invalid
input is rejected as a typed domain error before persistence, evaluation/
result are never written by this path (Phase 3's own), and the event
payload is self-sufficient (ADR-014/EB-003).
"""

from __future__ import annotations

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.domain.competitions.competition_service import (
    CompetitionDraft,
    CompetitionValidationError,
    competition_event_payload,
    create_competition,
)


def _make(**overrides):
    draft = CompetitionDraft(name=overrides.pop("name", "USACO"), **overrides)
    return create_competition(draft, "comp-1", FakeClock(), device_id="device-test")


class TestCreate:
    def test_new_competition_starts_discovered_at_revision_one(self):
        competition = _make()
        assert competition.status == "discovered"
        assert competition.revision == 1

    def test_empty_name_is_rejected(self):
        with pytest.raises(CompetitionValidationError):
            _make(name="   ")

    def test_unknown_status_is_rejected(self):
        with pytest.raises(CompetitionValidationError):
            _make(status="bogus")

    @pytest.mark.parametrize(
        "status",
        [
            "discovered",
            "evaluating",
            "entered",
            "skipped",
            "submitted",
            "judged",
            "archived",
        ],
    )
    def test_every_declared_status_is_accepted(self, status):
        assert _make(status=status).status == status

    def test_evaluation_and_result_are_never_written_by_this_path(self):
        # 07 §5.2: those columns are Phase 3's own write path.
        competition = _make()
        assert competition.evaluation is None
        assert competition.result is None

    def test_optional_fields_are_carried_through(self):
        competition = _make(url="https://usaco.org", project_id="proj-1")
        assert competition.url == "https://usaco.org"
        assert competition.project_id == "proj-1"


class TestEventPayload:
    def test_payload_carries_every_column(self):
        # EB-003: recovery-grade payloads must reconstruct the row exactly
        payload = competition_event_payload(_make())
        assert set(payload) == {
            "id",
            "name",
            "url",
            "status",
            "evaluation",
            "result",
            "project_id",
            "created_at",
            "updated_at",
            "device_id",
            "revision",
        }

    def test_payload_is_json_shaped(self):
        payload = competition_event_payload(_make())
        assert isinstance(payload["created_at"], str)
        assert isinstance(payload["revision"], int)
