"""Supervised task creation — the kernel's one sanctioned way to spawn an
asyncio Task (ADR-036 Slice 0).

Layer: kernel/runtime (17_PROJECT_STRUCTURE §4.1: "supervised task helper,
backoff" lives in `kernel/runtime/`; infrastructure belongs to the kernel,
domain never needs it — `:315`).

Constitutional home: 11_CODING_STANDARDS §12 — "All concurrency passes
through the kernel's supervised-task primitives (timeout, cancellation,
naming) — bare `create_task` outside the kernel is lint-banned." This is
that primitive; `tools/lint_banned_patterns.py` is the enforcement half,
landing in the same slice.

This module has no callers yet. ADR-036 D2 names the scheduler's own
tick task (Slice 2, not yet built) as the first real one — Slice 0 is
deliberately standalone, so it can be reviewed and merged without
touching, or risking, anything that exists today (mirroring Slice 1's
own "zero existing callers" shape for the connection executor/pool).

Retry-with-backoff is deliberately NOT part of this primitive — it is
its own RESERVED item (03_ROADMAP §8: "ruled not ripe 2026-08-13... a
job with a genuine transient-failure mode"), with no code anywhere
today. Bundling it in here would be building ahead of its own trigger.
What IS in scope, and load-bearing on its own: naming (every task is
identifiable, never anonymous — SEC-005's "no hidden execution"), an
optional real timeout (enforced by genuine cancellation, not the
post-hoc reporting `Job.timeout_s` gives today — ADR-028 C1's own
finding), and loud failure (DB-P7: a task's unhandled exception must
not disappear silently until Python's own garbage collector eventually
logs it with no context attached).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

__all__ = ["SupervisedTaskError", "create_supervised_task"]

_logger = logging.getLogger(__name__)


class SupervisedTaskError(Exception):
    """The primitive's own bookkeeping failed (e.g. no name given) — never
    the supervised task's own business exception, which the returned
    `Task` carries normally (awaitable; inspectable via `.exception()`)."""


def create_supervised_task(
    coro: Coroutine[Any, Any, Any],
    *,
    name: str,
    timeout_s: float | None = None,
) -> asyncio.Task[Any]:
    """Create the one kind of asyncio `Task` this kernel permits.

    `name` is mandatory, not optional — plain `asyncio.create_task` allows
    an anonymous task, but naming is how a future debug surface answers
    "why is KANG doing that?" without tracing the event loop by hand
    (SEC-005, P5). `timeout_s`, when given, wraps `coro` in
    `asyncio.wait_for` so an overrunning task is genuinely cancelled, not
    merely reported after the fact.

    Must be called from a running event loop, exactly like
    `asyncio.create_task` itself — this wraps it, it does not lift its
    preconditions.
    """
    if not name:
        raise SupervisedTaskError("create_supervised_task requires a name")
    wrapped = coro if timeout_s is None else asyncio.wait_for(coro, timeout_s)
    task = asyncio.create_task(wrapped, name=name)
    task.add_done_callback(_log_unhandled_failure)
    return task


def _log_unhandled_failure(task: asyncio.Task[Any]) -> None:
    """DB-P7 (fail visibly): a supervised task's exception must not
    disappear silently until garbage collection eventually logs "Task
    exception was never retrieved" with no context. A caller that DOES
    retrieve the result/exception (via `await`, or its own call to
    `.exception()`) sees this fire too — a harmless double-report, not a
    hidden failure. If the caller never retrieves it at all, this
    callback is the failure's only voice, so it must not stay silent.

    A cancelled task (deliberate, e.g. graceful shutdown) is not a
    failure and is not logged here — `task.cancelled()` covers both an
    externally-cancelled task and, importantly, does NOT cover a
    `timeout_s` overrun: `asyncio.wait_for`'s own `TimeoutError` surfaces
    as this task's exception, not as this task being cancelled, so a
    silent timeout is loud here exactly like any other unhandled failure.
    """
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        _logger.error("supervised task %r failed", task.get_name(), exc_info=exc)
