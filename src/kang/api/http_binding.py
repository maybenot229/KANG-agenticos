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


def _write_json(handler: BaseHTTPRequestHandler, status: int, body: dict) -> None:
    payload = json.dumps(body).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


def make_server(dispatcher: Dispatcher, host: str, port: int) -> HTTPServer:
    """Build (do not start) a local HTTP server bound to host:port that
    routes POST /op through the dispatcher. Single-threaded by design: the
    kang.db connection is single-writer (DB-001) and thread-confined, so all
    requests are served in the connection-owning thread. Caller runs
    serve_forever."""

    class _Handler(BaseHTTPRequestHandler):
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
    return HTTPServer((host, port), _Handler)
