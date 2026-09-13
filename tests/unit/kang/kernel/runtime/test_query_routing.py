"""ADR-036 D4 (resumed) / ADR-037 — query routing's own module: the
per-call query-handler factories and the async orchestration that
threads a query dispatch across the write-executor and read pool.
Proves the SEQUENCING (which phase runs on which pool, what happens on
failure) against fake executors and a fake `Dispatcher` double — the
pipeline's own correctness (auth, validation, bookkeeping) is proven in
`tests/unit/kang/api/test_dispatch.py`, not re-proven here.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from kang.api.dispatch import ApiRequest, HandlerContext
from kang.api.errors import ApiError
from kang.kernel.runtime.query_routing import _build_query_handlers, _dispatch_query

# The exact 16 query operations ADR-036 D4 routes to the read pool —
# every registered "query" operation except system.health (its
# SqliteBackupService dependency needs both kang.db and events.db;
# ReadPool opens one connection type per worker).
EXPECTED_QUERY_HANDLER_NAMES = frozenset(
    {
        "registry.get",
        "permission.list",
        "task.get",
        "deadline.list",
        "explain.invocation",
        "explain.plan_item",
        "explain.notification",
        "explain.suggestion",
        "explain.memory",
        "audit.list",
        "invocation.list",
        "held_action.list",
        "project.list",
        "competition.list",
        "milestone.list",
        "goal.list",
    }
)


@dataclass
class _FakeHandlerWiring:
    clock: object = None
    audit: object = None
    permission_engine: object = None


def test_build_query_handlers_covers_exactly_the_16_read_pool_operations():
    handlers = _build_query_handlers(_FakeHandlerWiring())
    assert set(handlers) == EXPECTED_QUERY_HANDLER_NAMES
    assert "system.health" not in handlers  # the one named exception


def test_every_query_handler_factory_builds_a_callable_without_touching_a_real_db():
    # Store constructors only save their connection reference (no query
    # runs at construction time), so a plain sentinel stands in fine here
    # — this proves the FACTORY shape, not the handler's own behavior
    # against real data (that's each operation's own handler test).
    handlers = _build_query_handlers(_FakeHandlerWiring())
    sentinel_connection = object()
    for name, factory in handlers.items():
        handler = factory(sentinel_connection)
        assert callable(handler), f"{name}'s factory did not build a Handler"


class _RecordingSubmitter:
    """Stands in for WriteExecutor.submit/ReadPool.submit: runs `fn`
    inline against a fixed value, recording which pool ran it."""

    def __init__(self, value: object, log: list[str], label: str) -> None:
        self._value = value
        self._log = log
        self._label = label

    async def submit(self, fn):
        self._log.append(self._label)
        return fn(self._value)


class _FakeDispatcher:
    """Records the phase calls `_dispatch_query` makes, without
    exercising the real pipeline (that's test_dispatch.py's job)."""

    def __init__(self, *, prepare_raises=None, handler_raises=None) -> None:
        self.calls: list[tuple] = []
        self._prepare_raises = prepare_raises
        self._handler_raises = handler_raises

    def prepare_query(self, request: ApiRequest, correlation_id: str):
        self.calls.append(("prepare_query", correlation_id))
        if self._prepare_raises is not None:
            raise self._prepare_raises
        entry = {"name": request.operation}
        context = HandlerContext(
            principal="kang",
            correlation_id=correlation_id,
            trigger="cli",
            first_party=True,
        )
        return entry, context

    def run_query_handler(self, name, connection, context, params):
        self.calls.append(("run_query_handler", name, connection))
        if self._handler_raises is not None:
            raise self._handler_raises
        return {"echo": params}

    def finish_query(self, context: HandlerContext, result):
        self.calls.append(("finish_query", context.correlation_id))
        return {"ok": True, "result": result, "correlation_id": context.correlation_id}

    def fail_query(self, correlation_id: str) -> None:
        self.calls.append(("fail_query", correlation_id))

    def error_envelope(self, exc: Exception, correlation_id: str):
        self.calls.append(("error_envelope", correlation_id))
        code = exc.code if isinstance(exc, ApiError) else "internal"
        return {"ok": False, "error": {"code": code, "correlation_id": correlation_id}}


class _FakeCore:
    def __init__(self, dispatcher: _FakeDispatcher) -> None:
        self.dispatcher = dispatcher
        self._ids = iter(f"cid-{n}" for n in range(1, 10))

    def new_id(self) -> str:
        return next(self._ids)


def _run(core, request, write_executor, read_pool):
    return asyncio.run(_dispatch_query(core, request, write_executor, read_pool))


def test_dispatch_query_runs_prepare_and_finish_on_write_and_handler_on_read():
    dispatcher = _FakeDispatcher()
    core = _FakeCore(dispatcher)
    log: list[str] = []
    sentinel_read_connection = object()
    write_executor = _RecordingSubmitter(core, log, "write")
    read_pool = _RecordingSubmitter(sentinel_read_connection, log, "read")

    response = _run(
        core, ApiRequest("task.get", {"id": "t-1"}, "tok"), write_executor, read_pool
    )

    assert log == ["write", "read", "write"]  # prepare, handler, finish — in order
    assert response == {
        "ok": True,
        "result": {"echo": {"id": "t-1"}},
        "correlation_id": "cid-1",
    }
    assert dispatcher.calls[1] == (
        "run_query_handler",
        "task.get",
        sentinel_read_connection,  # never the write connection
    )


def test_dispatch_query_calls_fail_query_then_error_envelope_on_handler_apierror():
    dispatcher = _FakeDispatcher(handler_raises=ApiError("not_found", "gone"))
    core = _FakeCore(dispatcher)
    log: list[str] = []
    write_executor = _RecordingSubmitter(core, log, "write")
    read_pool = _RecordingSubmitter(object(), log, "read")

    response = _run(
        core, ApiRequest("task.get", {"id": "t-1"}, "tok"), write_executor, read_pool
    )

    # prepare, handler, fail_query, error_envelope
    assert log == ["write", "read", "write", "write"]
    names = [call[0] for call in dispatcher.calls]
    assert names == [
        "prepare_query",
        "run_query_handler",
        "fail_query",
        "error_envelope",
    ]
    assert response["error"]["code"] == "not_found"


def test_dispatch_query_wraps_a_prepare_failure_as_error_envelope_without_fail_query():
    # A failure before record_start (e.g. a bad session) never reaches
    # finish_query/fail_query — mirrors dispatch()'s own behavior for a
    # failure before _execute.
    dispatcher = _FakeDispatcher(prepare_raises=ApiError("permission_denied", "no"))
    core = _FakeCore(dispatcher)
    log: list[str] = []
    write_executor = _RecordingSubmitter(core, log, "write")
    read_pool = _RecordingSubmitter(object(), log, "read")

    response = _run(
        core, ApiRequest("task.get", {"id": "t-1"}, "tok"), write_executor, read_pool
    )

    assert log == ["write", "write"]  # prepare (fails), then error_envelope — no read
    names = [call[0] for call in dispatcher.calls]
    assert names == ["prepare_query", "error_envelope"]
    assert response["error"]["code"] == "permission_denied"
