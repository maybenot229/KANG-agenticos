"""Local HTTP binding — one concrete binding of the API contract (D002).

Layer: api (the transport-adapter role; 17 §4.2 permits the api layer its
transport machinery — `aiohttp`, per ADR-035, replacing stdlib
`http.server`).
Constitutional home: 12_API API-002 (concrete bindings map the operation
channel to a transport; contract semantics MUST NOT depend on transport
features), §1.3 (local-only: binds 127.0.0.1 exclusively). This binding
carries the operation channel: POST /op with a JSON body → one dispatch →
one JSON envelope. The event channel (§6) is a later binding (needs the bus
subscription surface exposed to clients — M5+; `aiohttp`'s own WebSocket
support makes it cheap whenever that lands — ADR-035).

The request maps 1:1 to `ApiRequest`; the response is the dispatcher's
envelope verbatim. No domain logic lives here — it is glue to the pipeline.
`dispatch` is injected as a plain async callable rather than a `Dispatcher`
directly: this module stays ignorant of *how* a request reaches the Core
(today: `ApiRequest -> write_executor.submit(core.dispatcher.dispatch)` —
ADR-036 D4) — matching this module's own original design intent ("stays
fully scheduler-ignorant") extended to stay executor-ignorant too.

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
process can set to whatever it wants anyway). Applied via middleware
(`_cors_middleware`) so it reaches every response uniformly, including
`aiohttp`'s own 404 for an unregistered path — not just the routes this
module defines by hand.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import web

from kang.api.dispatch import ApiRequest

__all__ = ["make_app"]

Dispatch = Callable[[ApiRequest], Awaitable[dict[str, Any]]]

_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-Session-Token",
}


@web.middleware
async def _cors_middleware(
    request: web.Request,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> web.StreamResponse:
    try:
        response = await handler(request)
    except web.HTTPException as exc:
        # aiohttp's own routing failures (404 for an unregistered path,
        # 405 for a wrong method) raise HTTPException subclasses rather
        # than returning a response — still a response by the time it
        # reaches the client, so it still needs the headers.
        exc.headers.update(_CORS_HEADERS)
        raise
    response.headers.update(_CORS_HEADERS)
    return response


async def make_app(dispatch: Dispatch, host: str) -> web.Application:
    """Build (do not start) the aiohttp application serving POST /op.

    `host` is checked here, not deferred to the caller's own TCP bind,
    so a misconfigured host fails loudly at construction (12 §1.3)."""
    if host not in ("127.0.0.1", "localhost"):
        raise ValueError("the API binds 127.0.0.1 exclusively (12 §1.3)")

    async def handle_options(request: web.Request) -> web.Response:
        # The CORS preflight every browser-engine client sends before a
        # POST carrying X-Session-Token. No body, no dispatch — just the
        # headers that tell the browser the real POST is allowed.
        return web.Response(status=204)

    async def handle_op(request: web.Request) -> web.Response:
        try:
            raw = await request.read()
            body = json.loads(raw.decode("utf-8")) if raw else {}
            api_request = ApiRequest(
                operation=body["operation"],
                params=body.get("params", {}),
                session_token=request.headers.get("X-Session-Token", ""),
                idempotency_key=body.get("idempotency_key"),
            )
        except (KeyError, ValueError):
            return web.json_response(
                {"ok": False, "error": {"code": "invalid_request"}}, status=400
            )
        return web.json_response(await dispatch(api_request))

    app = web.Application(middlewares=[_cors_middleware])
    app.router.add_post("/op", handle_op)
    app.router.add_options("/op", handle_options)
    return app
