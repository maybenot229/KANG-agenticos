"""Competition store port — persistence contract for the competition entity.

Layer: domain/ports. Ports own their datatypes (17 §7): the Competition
shape lives here so both sides of the firewall may import it; competition
*invariants and services* live in domain/competitions.
Constitutional home: 07_DATABASE §5.2 (competition table), DB-002 (SQL
confined to the store layer behind this port), ADR-014 (competition.created
— the entity's first write path).

Tracking only (03_ROADMAP M4/M5 objective: "competitions... tracking
only"): this pass's port surface is create + list, nothing more.
`evaluation`/`result` are real columns (07 §5.2) but belong to Phase 3
(discovery/evaluation) — this port carries them (so a future write path
has somewhere to land) but nothing here ever writes a non-null value into
either, matching the table's own comment: "columns awaiting those
consumers, deliberately unwritten until then."
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

__all__ = [
    "COMPETITION_STATUSES",
    "Competition",
    "CompetitionStore",
]

COMPETITION_STATUSES = (
    "discovered",
    "evaluating",
    "entered",
    "skipped",
    "submitted",
    "judged",
    "archived",
)


@dataclass(frozen=True)
class Competition:
    """One competition row (07 §5.2), sync quartet included (D009).
    Immutable snapshot, matching Project's own shape/reasoning
    (`project_store.py`)."""

    id: str
    name: str
    status: str
    created_at: datetime
    updated_at: datetime
    device_id: str
    revision: int
    url: str | None = None
    evaluation: str | None = None  # JSON: fit/feasibility/effort/risk brief (Phase 3)
    result: str | None = None  # JSON: outcome after judging (Phase 3)
    project_id: str | None = None


class CompetitionStore(Protocol):
    """Persistence port for competitions. Implementations:
    SqliteCompetitionStore (real), FakeCompetitionStore (adapters/fakes —
    contract-tested against the real one, 13 §2.3). Tracking-only surface:
    create + list; see module docstring for why get/update/delete aren't
    here yet."""

    def create(self, competition: Competition) -> None:
        """Persist a new competition. The change is capture-logged (07
        §5.6, ADR-014's trigger)."""
        ...

    def list_all(self) -> list[Competition]:
        """Every competition, regardless of status — same "no natural due-
        date horizon" reasoning as `ProjectStore.list_all()`. Deterministic
        total order: (name, id) case-insensitively (13 §2.6)."""
        ...
