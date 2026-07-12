"""TaskStore port-contract suite — run identically against the fake and the
real adapter (13 §2.3: divergence between fake and real is itself a red
build; fakes that lie invalidate every unit test above them).

Subclasses provide a ``store`` fixture wired to a ``clock`` (FakeClock).
"""

from __future__ import annotations

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.domain.ports.task_store import (
    RevisionConflictError,
    Task,
    TaskNotFoundError,
)
from kang.domain.tasks import TaskDraft, complete_task, create_task

DEVICE = "device-test"


class TaskStoreContract:
    @pytest.fixture
    def clock(self) -> FakeClock:
        return FakeClock()

    def _new_task(self, clock: FakeClock, task_id: str = "task-0001") -> Task:
        return create_task(
            TaskDraft(title="prove the quartet"),
            task_id=task_id,
            clock=clock,
            device_id=DEVICE,
        )

    def test_create_then_get_roundtrips_every_field(self, store, clock):
        task = self._new_task(clock)
        store.create(task)
        assert store.get(task.id) == task

    def test_get_unknown_id_raises_typed_not_found(self, store, clock):
        with pytest.raises(TaskNotFoundError):
            store.get("task-none")

    def test_new_task_carries_the_sync_quartet(self, store, clock):
        task = self._new_task(clock)
        store.create(task)
        stored = store.get(task.id)
        assert stored.created_at == clock.now()
        assert stored.updated_at == clock.now()
        assert stored.device_id == DEVICE
        assert stored.revision == 1

    def test_update_bumps_revision_and_updated_at(self, store, clock):
        task = self._new_task(clock)
        store.create(task)
        clock.advance(60)
        committed = store.update(complete_task(task, clock))
        assert committed.revision == 2
        assert committed.updated_at == clock.now()
        assert committed.status == "done"
        assert store.get(task.id) == committed

    def test_update_with_stale_revision_conflicts(self, store, clock):
        task = self._new_task(clock)
        store.create(task)
        store.update(complete_task(task, clock))
        with pytest.raises(RevisionConflictError):
            store.update(complete_task(task, clock))  # still revision 1

    def test_update_unknown_id_raises_not_found(self, store, clock):
        with pytest.raises(TaskNotFoundError):
            store.update(self._new_task(clock, task_id="task-ghost"))

    def test_delete_removes_the_row(self, store, clock):
        task = self._new_task(clock)
        store.create(task)
        store.delete(task.id, deleted_by="kang")
        with pytest.raises(TaskNotFoundError):
            store.get(task.id)

    def test_delete_unknown_id_raises_not_found(self, store, clock):
        with pytest.raises(TaskNotFoundError):
            store.delete("task-none", deleted_by="kang")
