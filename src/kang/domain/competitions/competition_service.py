"""Competition domain service — invariants for the competition entity.

Layer: domain/competitions (capability service; deterministic, zero I/O).
Constitutional home: 07_DATABASE §5.2 (competition shape, status enum);
ADR-014 (competition.created, the entity's first write path).

Tracking only this pass: `create_competition` is the entity's whole
surface — no status-transition function exists yet (mirrors
project_service.py's own precedent exactly).
"""

from __future__ import annotations

from dataclasses import dataclass

from kang.domain.ports.clock import Clock
from kang.domain.ports.competition_store import COMPETITION_STATUSES, Competition

__all__ = [
    "CompetitionDraft",
    "CompetitionValidationError",
    "competition_event_payload",
    "create_competition",
]


class CompetitionValidationError(Exception):
    """A competition invariant was violated. Raised before anything is
    persisted."""


@dataclass(frozen=True)
class CompetitionDraft:
    """What Kang states about a competition he already knows of; the
    system stamps the rest (11 §4: beyond four parameters, it's a
    dataclass). No `evaluation`/`result` field: those are Phase 3's own
    write path, not this draft's (see the store port's docstring)."""

    name: str
    url: str | None = None
    status: str = "discovered"
    project_id: str | None = None


def _validate(draft: CompetitionDraft) -> None:
    if not draft.name.strip():
        raise CompetitionValidationError("name must be non-empty")
    if draft.status not in COMPETITION_STATUSES:
        raise CompetitionValidationError(
            f"status must be one of {COMPETITION_STATUSES}"
        )


def create_competition(
    draft: CompetitionDraft, competition_id: str, clock: Clock, device_id: str
) -> Competition:
    """Build a valid new Competition with the sync quartet stamped (D009):
    created_at/updated_at from the injected clock, device_id, revision 1.
    `evaluation`/`result` are always None here — Phase 3's write path, not
    this one's."""
    _validate(draft)
    now = clock.now()
    return Competition(
        id=competition_id,
        name=draft.name,
        url=draft.url,
        status=draft.status,
        project_id=draft.project_id,
        evaluation=None,
        result=None,
        created_at=now,
        updated_at=now,
        device_id=device_id,
        revision=1,
    )


def competition_event_payload(competition: Competition) -> dict:
    """The self-sufficient competition payload for `competition.created`
    (EB-003, ADR-014): the full field set, so a recovery-grade replay
    reconstructs the row exactly. Mirrors `project_event_payload`."""
    return {
        "id": competition.id,
        "name": competition.name,
        "url": competition.url,
        "status": competition.status,
        "evaluation": competition.evaluation,
        "result": competition.result,
        "project_id": competition.project_id,
        "created_at": competition.created_at.isoformat(),
        "updated_at": competition.updated_at.isoformat(),
        "device_id": competition.device_id,
        "revision": competition.revision,
    }
