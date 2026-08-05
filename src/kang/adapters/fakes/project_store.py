"""FakeProjectStore — in-memory ProjectStore, contract-paired (13 §2.3).

Layer: adapters/fakes.
Constitutional home: 11_CODING §5/§7 (every port has an in-memory fake).
"""

from __future__ import annotations

from kang.domain.ports.project_store import Project

__all__ = ["FakeProjectStore"]


class FakeProjectStore:
    """ProjectStore over a dict."""

    def __init__(self) -> None:
        self._projects: dict[str, Project] = {}

    def create(self, project: Project) -> None:
        if project.id in self._projects:
            raise ValueError(f"duplicate project {project.id}")
        self._projects[project.id] = project

    def list_all(self) -> list[Project]:
        return sorted(self._projects.values(), key=lambda p: (p.name.casefold(), p.id))
