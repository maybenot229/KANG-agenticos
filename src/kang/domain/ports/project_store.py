"""Project store port — persistence contract for the project entity.

Layer: domain/ports. Ports own their datatypes (17 §7): the Project shape
lives here so both sides of the firewall may import it; project
*invariants and services* live in domain/projects.
Constitutional home: 07_DATABASE §5.2 (project table), DB-002 (SQL confined
to the store layer behind this port), ADR-013 (project.created — the
entity's first write path).

Tracking only (03_ROADMAP M4/M5 objective: "projects... tracking only"):
this pass's port surface is create + list, nothing more. `milestone`,
status transitions, and any update/delete path are real schema (0006
already shapes `milestone`) but have no operation yet — added when one
exists, not speculatively widened now (PS-006).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

__all__ = [
    "PROJECT_STATUSES",
    "Project",
    "ProjectStore",
]

PROJECT_STATUSES = ("active", "paused", "completed", "archived", "abandoned")


@dataclass(frozen=True)
class Project:
    """One project row (07 §5.2), sync quartet included (D009). Immutable
    snapshot, matching Deadline's own shape/reasoning (`deadline_store.py`)."""

    id: str
    name: str
    status: str
    created_at: datetime
    updated_at: datetime
    device_id: str
    revision: int
    description: str | None = None
    vault_folder: str | None = None  # path within vault (reference, not content)
    github_repo: str | None = None  # owner/name
    goal_id: str | None = None


class ProjectStore(Protocol):
    """Persistence port for projects. Implementations: SqliteProjectStore
    (real), FakeProjectStore (adapters/fakes — contract-tested against the
    real one, 13 §2.3). Tracking-only surface: create + list; see module
    docstring for why get/update/delete aren't here yet."""

    def create(self, project: Project) -> None:
        """Persist a new project. The change is capture-logged (07 §5.6,
        ADR-013's trigger)."""
        ...

    def list_all(self) -> list[Project]:
        """Every project, regardless of status — the tracking view has no
        "active only" horizon the way deadlines do (there's no natural due
        date to filter by). Deterministic total order: (name, id) case-
        insensitively, so identical state always yields byte-identical
        output (13 §2.6), same discipline as `DeadlineStore.active()`."""
        ...
