"""The local HTTP binding (API-002, 12_API §1.3) — zero coverage existed
before this suite (found by grepping tests/ for http_binding/make_server,
session 2026-08-04: no hits). The CORS gap this suite pins down was found
the same way — a real browser client, not a code read — which is exactly
the class of defect a binding with no test coverage at all lets through.
"""

from __future__ import annotations

import itertools
import json
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer

import pytest

from kang.adapters.fakes.api_stores import (
    FakeIdempotencyStore,
    FakeInvocationStore,
    FakeSessionStore,
)
from kang.adapters.fakes.audit_log import FakeAuditLog
from kang.adapters.fakes.clock import FakeClock
from kang.api.dispatch import Dispatcher, DispatcherDeps
from kang.api.http_binding import make_server
from kang.domain.ports.session import Session
from kang.kernel.audit.service import AuditService
from kang.kernel.permissions.engine import PermissionEngine

VALID_TOKEN = "tok-kang"


@pytest.fixture
def running_server():
    clock = FakeClock()
    sessions = FakeSessionStore()
    sessions.create(
        Session(token=VALID_TOKEN, principal="kang", first_party=True, created_at="t")
    )
    ids = (f"id-{n}" for n in itertools.count())
    handlers = {"registry.get": lambda ctx, params: {"echo": params}}
    dispatcher = Dispatcher(
        handlers,
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
    server = make_server(dispatcher, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _url(address: tuple[str, int]) -> str:
    host, port = address
    return f"http://{host}:{port}/op"


def test_options_preflight_returns_204_with_cors_headers(running_server):
    # Found by a real browser fetch() from a real running UI client
    # failing outright — a browser sends this preflight before any POST
    # carrying a custom header (X-Session-Token), and refuses the whole
    # exchange without a matching response to it.
    request = urllib.request.Request(_url(running_server), method="OPTIONS")
    with urllib.request.urlopen(request) as response:
        assert response.status == 204
        assert response.headers["Access-Control-Allow-Origin"] == "*"
        assert "POST" in response.headers["Access-Control-Allow-Methods"]
        assert "X-Session-Token" in response.headers["Access-Control-Allow-Headers"]


def test_post_response_carries_cors_headers(running_server):
    body = json.dumps({"operation": "registry.get", "params": {}}).encode()
    request = urllib.request.Request(
        _url(running_server),
        data=body,
        headers={"Content-Type": "application/json", "X-Session-Token": VALID_TOKEN},
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        assert response.headers["Access-Control-Allow-Origin"] == "*"
        envelope = json.loads(response.read())
        assert envelope["ok"] is True


def test_error_response_also_carries_cors_headers(running_server):
    # A denied/failed request is exactly the case a browser client most
    # needs the header on — an error response without it is invisible to
    # the page's own error handling (a generic "Failed to fetch", not the
    # real API-006 envelope), which is the actual bug this suite pins.
    request = urllib.request.Request(
        _url(running_server),
        data=json.dumps({"operation": "task.teleport", "params": {}}).encode(),
        headers={"Content-Type": "application/json", "X-Session-Token": VALID_TOKEN},
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        assert response.headers["Access-Control-Allow-Origin"] == "*"
        envelope = json.loads(response.read())
        assert envelope["error"]["code"] == "not_found"


def test_make_server_honors_a_custom_server_class():
    # ADR-019: the composition root passes a service_actions()-overriding
    # HTTPServer subclass to drive the live tick loop. make_server stays
    # scheduler-ignorant — it just has to build whatever class it's given.
    class _MarkedServer(HTTPServer):
        pass

    dispatcher = Dispatcher(
        {},
        DispatcherDeps(
            sessions=FakeSessionStore(),
            permissions=PermissionEngine({}),
            idempotency=FakeIdempotencyStore(),
            invocations=FakeInvocationStore(),
            audit=AuditService(FakeAuditLog(), FakeClock()),
            clock=FakeClock(),
            new_id=lambda: "id",
        ),
    )
    server = make_server(dispatcher, "127.0.0.1", 0, server_class=_MarkedServer)
    try:
        assert isinstance(server, _MarkedServer)
    finally:
        server.server_close()


def test_unknown_path_is_404_and_still_carries_cors_headers(running_server):
    host, port = running_server
    request = urllib.request.Request(f"http://{host}:{port}/nope", method="POST")
    try:
        urllib.request.urlopen(request)
        pytest.fail("expected HTTPError")
    except urllib.error.HTTPError as exc:
        assert exc.code == 404
        assert exc.headers["Access-Control-Allow-Origin"] == "*"
