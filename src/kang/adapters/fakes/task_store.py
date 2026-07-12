"""FakeTaskStore — in-memory TaskStore, contract-paired with SqliteTaskStore.

Layer: adapters/fakes (shipped, versioned; fakes that lie are red — 13 §2.3:
the same contract suite runs against this and the real adapter).
Constitutional home: 11_CODING §5/§7 (every port has an in-memory fake).
"""

from __future__ import annotations

from dataclasses import replace

from kang.domain.ports.clock import Clock
from kang.domain.ports.task_store import (
    RevisionConflictError,
    Task,
    TaskNotFoundError,
)

__all__ = ["FakeTaskStore"]


class FakeTaskStore:
    """TaskStore over a dict. Mirrors the port contract exactly: optimistic
    revision checks, bump-on-update, tombstones on delete."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._tasks: dict[str, Task] = {}
        self.tombstones: list[tuple[str, str, str]] = []  # (id, entity, by)

    def create(self, task: Task) -> None:
        if task.id in self._tasks:
            raise ValueError(f"duplicate task id {task.id}")
        self._tasks[task.id] = task

    def get(self, task_id: str) -> Task:
        try:
            return self._tasks[task_id]
        except KeyError:
            raise TaskNotFoundError(task_id) from None

    def update(self, task: Task) -> Task:
        current = self.get(task.id)
        if current.revision != task.revision:
            raise RevisionConflictError(
                f"task {task.id}: expected revision {task.revision}, "
                f"store has {current.revision}"
            )
        committed = replace(
            task, updated_at=self._clock.now(), revision=task.revision + 1
        )
        self._tasks[task.id] = committed
        return committed

    def delete(self, task_id: str, deleted_by: str) -> None:
        if task_id not in self._tasks:
            raise TaskNotFoundError(task_id)
        del self._tasks[task_id]
        self.tombstones.append((task_id, "task", deleted_by))
