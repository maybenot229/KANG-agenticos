"""The local HTTP binding (API-002, 12_API §1.3), against `aiohttp`
(ADR-035) via its own in-process test client — no real socket, no thread.

Each test wraps its own body in `asyncio.run()` rather than depending on
`pytest-asyncio`/`pytest-aiohttp` — the same no-new-test-dependency
pattern `test_supervised_task.py`/`test_connection_pool.py` already
established (ADR-036 Slice 0/1).

The CORS coverage here traces back to a real browser client failing a
real `fetch()` against a real running Core (session 2026-08-04) — the
exact class of defect a binding with no test coverage lets through.
"""

from __future__ import annotations

import asyncio
import itertools
import json
from collections.abc import Awaitable, Callable
from typing import TypeVar

import pytest
from aiohttp.test_utils import TestClient, TestServer

from kang.adapters.fakes.api_stores import (
    FakeIdempotencyStore,
    FakeInvocationStore,
    FakeSessionStore,
)
from kang.adapters.fakes.audit_log import FakeAuditLog
from kang.adapters.fakes.clock import FakeClock
from kang.api.dispatch import ApiRequest, Dispatcher, DispatcherDeps
from kang.api.http_binding import make_app
from kang.domain.ports.session import Session
from kang.kernel.audit.service import AuditService
from kang.kernel.permissions.engine import PermissionEngine

VALID_TOKEN = "tok-kang"

T = TypeVar("T")


def _dispatcher() -> Dispatcher:
    clock = FakeClock()
    sessions = FakeSessionStore()
    sessions.create(
        Session(token=VALID_TOKEN, principal="kang", first_party=True, created_at="t")
    )
    ids = (f"id-{n}" for n in itertools.count())
    return Dispatcher(
        {"registry.get": lambda ctx, params: {"echo": params}},
        DispatcherDeps(
            sessions=sessions,
            permissions=PermissionEngine({"kang": ("*",)}),
            idempotency=FakeIdempotencyStore(),
            invocations=FakeInvocationStore(),
            audit=AuditService(FakeAuditLog(), clock),
            clock=clock,
            new_id=lambda: next(ids),
        ),
    )


def _with_client(body: Callable[[TestClient], Awaitable[T]]) -> T:
    """Build a fresh app (backed by a fresh Dispatcher+fakes) and run
    `body` against it via aiohttp's own in-process test client."""

    async def scenario() -> T:
        dispatcher = _dispatcher()

        async def dispatch(request: ApiRequest) -> dict:
            # The real binding wraps this in write_executor.submit(...)
            # (ADR-036 D4); a direct, synchronous call is equivalent here
            # — this suite tests the HTTP mapping, not the executor.
            return dispatcher.dispatch(request)

        app = await make_app(dispatch, "127.0.0.1")
        async with TestClient(TestServer(app)) as client:
            return await body(client)

    return asyncio.run(scenario())


def test_options_preflight_returns_204_with_cors_headers():
    # Found by a real browser fetch() from a real running UI client
    # failing outright — a browser sends this preflight before any POST
    # carrying a custom header (X-Session-Token), and refuses the whole
    # exchange without a matching response to it.
    async def body(client):
        response = await client.options("/op")
        assert response.status == 204
        assert response.headers["Access-Control-Allow-Origin"] == "*"
        assert "POST" in response.headers["Access-Control-Allow-Methods"]
        assert "X-Session-Token" in response.headers["Access-Control-Allow-Headers"]

    _with_client(body)


def test_post_response_carries_cors_headers():
    async def body(client):
        response = await client.post(
            "/op",
            data=json.dumps({"operation": "registry.get", "params": {}}),
            headers={
                "Content-Type": "application/json",
                "X-Session-Token": VALID_TOKEN,
            },
        )
        assert response.headers["Access-Control-Allow-Origin"] == "*"
        envelope = await response.json()
        assert envelope["ok"] is True

    _with_client(body)


def test_error_response_also_carries_cors_headers():
    # A denied/failed request is exactly the case a browser client most
    # needs the header on — an error response without it is invisible to
    # the page's own error handling (a generic "Failed to fetch", not the
    # real API-006 envelope), which is the actual bug this suite pins.
    async def body(client):
        response = await client.post(
            "/op",
            data=json.dumps({"operation": "task.teleport", "params": {}}),
            headers={
                "Content-Type": "application/json",
                "X-Session-Token": VALID_TOKEN,
            },
        )
        assert response.headers["Access-Control-Allow-Origin"] == "*"
        envelope = await response.json()
        assert envelope["error"]["code"] == "not_found"

    _with_client(body)


def test_an_empty_body_is_invalid_request_not_a_crash():
    async def body(client):
        response = await client.post("/op")
        assert response.status == 400
        envelope = await response.json()
        assert envelope["error"]["code"] == "invalid_request"

    _with_client(body)


def test_a_body_missing_operation_is_invalid_request():
    async def body(client):
        response = await client.post(
            "/op",
            data=json.dumps({"params": {}}),
            headers={"Content-Type": "application/json"},
        )
        assert response.status == 400
        envelope = await response.json()
        assert envelope["error"]["code"] == "invalid_request"

    _with_client(body)


def test_unknown_path_is_404_and_still_carries_cors_headers():
    async def body(client):
        response = await client.post("/nope")
        assert response.status == 404
        assert response.headers["Access-Control-Allow-Origin"] == "*"

    _with_client(body)


def test_make_app_rejects_a_non_local_host():
    async def scenario():
        with pytest.raises(ValueError, match="127.0.0.1"):
            await make_app(lambda request: None, "0.0.0.0")

    asyncio.run(scenario())
