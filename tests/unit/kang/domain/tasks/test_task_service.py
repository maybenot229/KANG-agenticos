"""Task service invariants (07 §5.2 CHECK constraints, mirrored in domain)."""

from __future__ import annotations

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.domain.tasks import (
    TaskDraft,
    TaskValidationError,
    complete_task,
    create_task,
)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def _task(clock: FakeClock, **draft_overrides):
    draft = TaskDraft(**{"title": "a title", **draft_overrides})
    return create_task(draft, task_id="task-0001", clock=clock, device_id="device-test")


def test_create_stamps_the_sync_quartet(clock):
    task = _task(clock)
    assert task.created_at == clock.now()
    assert task.updated_at == clock.now()
    assert task.device_id == "device-test"
    assert task.revision == 1


def test_create_defaults_match_schema_defaults(clock):
    task = _task(clock)
    assert task.status == "open"
    assert task.priority == 3


def test_empty_title_rejected(clock):
    with pytest.raises(TaskValidationError):
        _task(clock, title="   ")


def test_unknown_status_rejected(clock):
    with pytest.raises(TaskValidationError):
        _task(clock, status="paused")


@pytest.mark.parametrize("priority", [0, 6, -1])
def test_priority_out_of_bounds_rejected(clock, priority):
    with pytest.raises(TaskValidationError):
        _task(clock, priority=priority)


def test_complete_sets_status_and_completion_time(clock):
    task = _task(clock)
    clock.advance(3600)
    done = complete_task(task, clock)
    assert done.status == "done"
    assert done.completed_at == clock.now()
    assert done.updated_at == clock.now()  # a real mutation, not just completed_at
    assert task.status == "open"  # snapshots are immutable


def test_completing_a_done_task_rejected(clock):
    done = complete_task(_task(clock), clock)
    with pytest.raises(TaskValidationError):
        complete_task(done, clock)
