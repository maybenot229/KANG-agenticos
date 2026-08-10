"""Local HTTP binding — one concrete binding of the API contract (D002).

Layer: api (the transport-adapter role; 17 §4.2 permits the api layer its
transport machinery — here stdlib http.server, no dependency).
Constitutional home: 12_API API-002 (concrete bindings map the operation
channel to a transport; contract semantics MUST NOT depend on transport
features), §1.3 (local-only: binds 127.0.0.1 exclusively). This binding
carries the operation channel: POST /op with a JSON body → one dispatch →
one JSON envelope. The event channel (§6) is a later binding (needs the bus
subscription surface exposed to clients — M5+).

The request maps 1:1 to `ApiRequest`; the response is the dispatcher's
envelope verbatim. No domain logic lives here — it is glue to the pipeline.

CORS (found real, session 2026-08-04): a browser-engine client (Tauri's
webview is WebView2 — a real Chromium engine, not exempt from the web
platform's CORS rules) sends a preflight OPTIONS before any POST carrying
a custom header (`X-Session-Token`), and refuses the response entirely
without `Access-Control-Allow-*` headers — confirmed by an actual failed
`fetch()` from a real running UI client against a real running Core, not
assumed. Headers are permissive (`*`) rather than origin-checked: the
server already binds 127.0.0.1 exclusively (enforced below), so the real
perimeter is "who can reach this loopback port," identical to the
session-token file's own accepted limit (10_SECURITY §2.2 — OS-account
access is the honest boundary, not an origin string a same-machine
process can set to whatever it wants anyway).
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from kang.api.dispatch import ApiRequest, Dispatcher

__all__ = ["make_server"]


def _read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0"))
    if length == 0:
        return {}
    return json.loads(handler.rfile.read(length).decode("utf-8"))


def _send_cors_headers(handler: BaseHTTPRequestHandler) -> None:
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type, X-Session-Token")


def _write_json(handler: BaseHTTPRequestHandler, status: int, body: dict) -> None:
    payload = json.dumps(body).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(payload)))
    _send_cors_headers(handler)
    handler.end_headers()
    handler.wfile.write(payload)


def make_server(
    dispatcher: Dispatcher,
    host: str,
    port: int,
    server_class: type[HTTPServer] = HTTPServer,
) -> HTTPServer:
    """Build (do not start) a local HTTP server bound to host:port that
    routes POST /op through the dispatcher. Single-threaded by design: the
    kang.db connection is single-writer (DB-001) and thread-confined, so all
    requests are served in the connection-owning thread. Caller runs
    serve_forever.

    `server_class` defaults to plain `HTTPServer` and stays this module's
    only concession to the caller — this module still knows nothing about
    the scheduler. The composition root (ADR-019) passes a subclass that
    overrides `service_actions()` to re-run the scheduler's catch-up on a
    tick, reusing `serve_forever`'s existing per-poll-cycle hook rather
    than a second thread (which DB-001's thread-confined connection
    forbids)."""

    class _Handler(BaseHTTPRequestHandler):
        def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib callback name
            # The CORS preflight every browser-engine client sends before
            # a POST carrying X-Session-Token. No body, no dispatch — just
            # the headers that tell the browser the real POST is allowed.
            self.send_response(204)
            _send_cors_headers(self)
            self.end_headers()

        def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
            if self.path != "/op":
                _write_json(self, 404, {"ok": False, "error": {"code": "not_found"}})
                return
            try:
                body = _read_json(self)
                request = ApiRequest(
                    operation=body["operation"],
                    params=body.get("params", {}),
                    session_token=self.headers.get("X-Session-Token", ""),
                    idempotency_key=body.get("idempotency_key"),
                )
            except (KeyError, ValueError):
                _write_json(
                    self, 400, {"ok": False, "error": {"code": "invalid_request"}}
                )
                return
            _write_json(self, 200, dispatcher.dispatch(request))

        def log_message(self, *args: Any) -> None:  # silence stdlib stderr noise
            return

    if host not in ("127.0.0.1", "localhost"):
        raise ValueError("the API binds 127.0.0.1 exclusively (12 §1.3)")
    return server_class((host, port), _Handler)
