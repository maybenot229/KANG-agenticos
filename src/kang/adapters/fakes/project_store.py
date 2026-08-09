"""FakeProjectStore — in-memory ProjectStore, contract-paired (13 §2.3).

Layer: adapters/fakes.
Constitutional home: 11_CODING §5/§7 (every port has an in-memory fake).
"""

from __future__ import annotations

from dataclasses import replace

from kang.domain.ports.clock import Clock
from kang.domain.ports.project_store import (
    Project,
    ProjectNotFoundError,
    ProjectRevisionConflictError,
)

__all__ = ["FakeProjectStore"]


class FakeProjectStore:
    """ProjectStore over a dict. Mirrors the port contract exactly:
    optimistic revision checks, bump-on-update."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._projects: dict[str, Project] = {}

    def create(self, project: Project) -> None:
        if project.id in self._projects:
            raise ValueError(f"duplicate project {project.id}")
        self._projects[project.id] = project

    def get(self, project_id: str) -> Project:
        try:
            return self._projects[project_id]
        except KeyError:
            raise ProjectNotFoundError(project_id) from None

    def update(self, project: Project) -> Project:
        current = self.get(project.id)
        if current.revision != project.revision:
            raise ProjectRevisionConflictError(
                f"project {project.id}: expected revision {project.revision}, "
                f"store has {current.revision}"
            )
        committed = replace(
            project, updated_at=self._clock.now(), revision=project.revision + 1
        )
        self._projects[project.id] = committed
        return committed

    def list_all(self) -> list[Project]:
        return sorted(self._projects.values(), key=lambda p: (p.name.casefold(), p.id))
