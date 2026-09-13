"""The kernel's supervised-task primitive (11 §12, ADR-036 Slice 0).

The claim: every task this kernel creates is named, an optional timeout
is real cancellation (not post-hoc reporting), and an unhandled failure
is always logged — never left to disappear until garbage collection
eventually reports it with no context (DB-P7).
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from kang.kernel.runtime.supervised_task import (
    SupervisedTaskError,
    create_supervised_task,
)


async def _return_value(value):
    return value


async def _raise(exc: Exception):
    raise exc


async def _sleep_forever():
    await asyncio.sleep(3600)


def test_requires_a_name():
    async def scenario():
        coro = _return_value(1)
        try:
            with pytest.raises(SupervisedTaskError):
                create_supervised_task(coro, name="")
        finally:
            coro.close()  # never scheduled — avoid a "never awaited" warning

    asyncio.run(scenario())


def test_runs_the_coroutine_and_returns_its_result():
    async def scenario():
        task = create_supervised_task(_return_value(42), name="test-task")
        assert await task == 42

    asyncio.run(scenario())


def test_the_task_is_named():
    async def scenario():
        task = create_supervised_task(_return_value(1), name="my-task-name")
        assert task.get_name() == "my-task-name"
        await task

    asyncio.run(scenario())


def test_a_slow_coroutine_is_genuinely_cancelled_by_its_timeout():
    async def scenario():
        task = create_supervised_task(
            _sleep_forever(), name="slow-task", timeout_s=0.01
        )
        with pytest.raises(TimeoutError):
            await task
        # Real cancellation, not post-hoc reporting (ADR-028 C1's own
        # finding about Job.timeout_s) — the task is actually done.
        assert task.done()

    asyncio.run(scenario())


def test_a_timeout_is_logged_as_a_failure_not_silently_swallowed(caplog):
    async def scenario():
        with caplog.at_level(
            logging.ERROR, logger="kang.kernel.runtime.supervised_task"
        ):
            task = create_supervised_task(
                _sleep_forever(), name="timeout-task", timeout_s=0.01
            )
            with pytest.raises(TimeoutError):
                await task

    asyncio.run(scenario())
    assert "timeout-task" in caplog.text
    assert "failed" in caplog.text


def test_an_unhandled_exception_is_logged(caplog):
    async def scenario():
        with caplog.at_level(
            logging.ERROR, logger="kang.kernel.runtime.supervised_task"
        ):
            task = create_supervised_task(
                _raise(ValueError("boom")), name="failing-task"
            )
            with pytest.raises(ValueError):
                await task

    asyncio.run(scenario())
    assert "failing-task" in caplog.text
    assert "ValueError" in caplog.text


def test_deliberate_cancellation_is_not_logged_as_a_failure(caplog):
    """A cancelled task (e.g. graceful shutdown) is not a failure — only
    a genuinely unhandled exception is."""

    async def scenario():
        with caplog.at_level(
            logging.ERROR, logger="kang.kernel.runtime.supervised_task"
        ):
            task = create_supervised_task(_sleep_forever(), name="cancelled-task")
            await asyncio.sleep(0)  # let the task actually start
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(scenario())
    assert "cancelled-task" not in caplog.text
