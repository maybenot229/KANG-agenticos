"""competition.create / competition.list handlers.

Layer: api.
Constitutional home: 12_API §2/§7/§8, ADR-014 (competition.created — the
Competitions domain's first write path).
"""

from __future__ import annotations

from typing import Any, Callable

from kang.api.dispatch import Handler, HandlerContext
from kang.api.errors import ApiError
from kang.domain.competitions.competition_service import (
    CompetitionDraft,
    CompetitionValidationError,
    competition_event_payload,
    create_competition,
)
from kang.domain.ports.clock import Clock
from kang.domain.ports.competition_store import CompetitionStore
from kang.domain.ports.eventlog import EventEnvelope
from kang.kernel.bus.bus import EventBus

__all__ = [
    "COMPETITIONS_PRINCIPAL",
    "make_competition_create_handler",
    "make_competition_list_handler",
]

COMPETITIONS_PRINCIPAL = (
    "kernel:competitions"  # owns competition truth (EB-010, ADR-014)
)


def make_competition_create_handler(
    bus: EventBus,
    competition_store: CompetitionStore,
    clock: Clock,
    new_id: Callable[[], str],
    device_id: str,
) -> Handler:
    """`competition.create` (ADR-014): the Competitions domain's first
    write path — tracking only, mirrors `make_project_create_handler`'s
    exact shape. Publishes `competition.created` (recovery-grade, full
    row) under `kernel:competitions` — `commit_state` only runs inside
    `bus.publish` (EB-004), so this is the only way the write can commit
    at all."""

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        try:
            competition = create_competition(
                CompetitionDraft(
                    name=params.get("name", ""),
                    url=params.get("url"),
                    status=params.get("status", "discovered"),
                    project_id=params.get("project_id"),
                ),
                competition_id=new_id(),
                clock=clock,
                device_id=device_id,
            )
        except CompetitionValidationError as exc:
            raise ApiError("invalid_request", str(exc)) from exc
        bus.publish(
            EventEnvelope(
                event_id=new_id(),
                type="competition.created",
                occurred_at=competition.updated_at.isoformat(),
                principal=COMPETITIONS_PRINCIPAL,
                correlation_id=context.correlation_id,
                device_id=device_id,
                payload=competition_event_payload(competition),
                recovery_grade=True,
                entity_refs=({"kind": "competition", "id": competition.id},),
            ),
            commit_state=lambda: competition_store.create(competition),
        )
        return {"competition_id": competition.id, "revision": competition.revision}

    return handler


def make_competition_list_handler(competition_store: CompetitionStore) -> Handler:
    """`competition.list` (ADR-014, tracking only): every competition,
    name-then-id ordered — `CompetitionStore.list_all()`'s existing
    contract, exposed verbatim. No new domain logic."""

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "competitions": [
                {
                    "id": c.id,
                    "name": c.name,
                    "status": c.status,
                    "url": c.url,
                    "evaluation": c.evaluation,
                    "result": c.result,
                    "project_id": c.project_id,
                }
                for c in competition_store.list_all()
            ]
        }

    return handler
