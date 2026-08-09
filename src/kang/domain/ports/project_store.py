"""Project store port — persistence contract for the project entity.

Layer: domain/ports. Ports own their datatypes (17 §7): the Project shape
lives here so both sides of the firewall may import it; project
*invariants and services* live in domain/projects.
Constitutional home: 07_DATABASE §5.2 (project table), DB-002 (SQL confined
to the store layer behind this port), ADR-013 (project.created — the
entity's first write path).

`complete` (ADR-018, 2026-08-09) is the entity's first status transition:
`get`/`update` join `create`/`list_all`, mirroring `TaskStore`'s exact
optimistic-concurrency contract. `pause`/`resume`/`archive`/`abandon`
stay unbuilt — ADR-018's own scope ruling: no prior document names a
specific verb set for project the way milestone/goal's own ADRs did,
and building all five transitions with no named consumer beyond "the
enum allows it" would be the speculative-structure anti-pattern this
project rejects everywhere else.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

__all__ = [
    "PROJECT_STATUSES",
    "Project",
    "ProjectNotFoundError",
    "ProjectRevisionConflictError",
    "ProjectStore",
    "ProjectStoreError",
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


class ProjectStoreError(Exception):
    """Base of the project-store failure hierarchy (11 §9: typed errors)."""


class ProjectNotFoundError(ProjectStoreError):
    """No project with the given id exists."""


class ProjectRevisionConflictError(ProjectStoreError):
    """Optimistic concurrency check failed: expected revision is stale."""


class ProjectStore(Protocol):
    """Persistence port for projects. Implementations: SqliteProjectStore
    (real), FakeProjectStore (adapters/fakes — contract-tested against the
    real one, 13 §2.3). `get`/`update` (ADR-018) join `create`/`list_all`;
    delete still has no caller."""

    def create(self, project: Project) -> None:
        """Persist a new project. The change is capture-logged (07 §5.6,
        ADR-013's trigger)."""
        ...

    def get(self, project_id: str) -> Project:
        """Return the project or raise ProjectNotFoundError."""
        ...

    def update(self, project: Project) -> Project:
        """Persist a status transition; `project.revision` is the
        expected current revision. Returns the committed snapshot
        (revision bumped, `updated_at` stamped). Raises
        ProjectRevisionConflictError on staleness, ProjectNotFoundError
        if the id no longer exists."""
        ...

    def list_all(self) -> list[Project]:
        """Every project, regardless of status — the tracking view has no
        "active only" horizon the way deadlines do (there's no natural due
        date to filter by). Deterministic total order: (name, id) case-
        insensitively, so identical state always yields byte-identical
        output (13 §2.6), same discipline as `DeadlineStore.active()`."""
        ...
