"""API request lifecycle (12_API §5) — thin: session, validation, dispatch.

Layer: api.
Constitutional home: 12_API §5 (session → principal resolution → schema
validation → registry dispatch → idempotency check → permission check →
kernel execution → response, with a correlation_id minted at ingress and
returned on every response), API-003 (authentication only; authorization is
the engine's), API-004 (idempotency), API-006 (one error model), §12 (every
operation is recorded as an invocation for `explain`), ADR-010 Ruling 4
(schema validation lives in `_validate`, a `ValidationError` maps to
`invalid_request` with a sanitized `details.field_errors` — never the
raw offending value, which could be private-tier content).

Thinness (12 §2): this layer contains NO domain logic. Handlers are the glue
to domain services; an `if` here about tasks or memory would be a defect.
The dispatcher wires the constitutional pipeline once, for every operation.

ADR-036 D4 (resumed, 2026-09-14): read-pool-routed query operations don't
go through `dispatch()` at all. `composition.py`'s `_dispatch_query` calls
`prepare_query`/`run_query_handler`/`finish_query`/`fail_query` instead,
across the write-executor and read pool — the same pipeline steps
`dispatch()` itself uses, in the same order, just not fused into one
atomic call the way a command's `dispatch()` still is. `dispatch()`'s own
behavior and signature are completely unchanged by this; every existing
caller (including ~900 tests calling it directly, synchronously) is
unaffected.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from pydantic import ValidationError

from kang.api.errors import ApiError
from kang.api.registry import operation as registry_operation
from kang.domain.ports.clock import Clock
from kang.domain.ports.idempotency import IdempotencyStore
from kang.domain.ports.invocation import Invocation, InvocationStore
from kang.domain.ports.session import SessionInvalid, SessionStore
from kang.kernel.audit.service import AuditService
from kang.kernel.permissions.engine import PermissionDenied, PermissionEngine

__all__ = ["ApiRequest", "Dispatcher", "DispatcherDeps", "Handler", "HandlerContext"]


@dataclass(frozen=True)
class HandlerContext:
    """What a handler is told about its caller (never the raw session)."""

    principal: str
    correlation_id: str
    trigger: str
    first_party: bool


@dataclass(frozen=True)
class ApiRequest:
    operation: str
    params: dict[str, Any]
    session_token: str
    idempotency_key: str | None = None


# A handler is the glue to a domain service: (context, params) → result dict.
Handler = Callable[[HandlerContext, dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class DispatcherDeps:
    """The pipeline's injected collaborators (11 §4: beyond a few params, a
    dataclass). Wired once at the composition root."""

    sessions: SessionStore
    permissions: PermissionEngine
    idempotency: IdempotencyStore
    invocations: InvocationStore
    audit: AuditService
    clock: Clock
    new_id: Callable[[], str]


def _sanitized_field_errors(exc: ValidationError) -> list[dict[str, str]]:
    """ADR-010 Ruling 4: Pydantic's raw `.errors()` includes `input` (the
    exact offending value — a leakage risk if a `private`-tier field ever
    reaches this path, per D010/PRD §10.14's threat model) and `ctx`
    (internal, implementation-specific). Keep only field path + message
    type — enough to fix the request, never enough to leak the value."""
    return [
        {"field": ".".join(str(part) for part in err["loc"]), "message": err["msg"]}
        for err in exc.errors()
    ]


class Dispatcher:
    """Runs the §5 pipeline for every operation.

    `query_handlers` (ADR-036 D4, resumed) is a second, optional table:
    `name -> Callable[[connection], Handler]`, a per-call factory rather
    than a ready-made `Handler` — for query-kind operations composition.py
    routes to the read pool instead of the write-executor. Defaults to
    `{}` so every existing caller (~900 tests, and `dispatch()` itself)
    is completely unaffected; nothing in `dispatch()`'s own body reads
    it. Only `composition.py`'s `_dispatch_query` (a new, separate
    caller) uses `query_handler_names`/`prepare_query`/`run_query_handler`/
    `finish_query`/`fail_query` below — `dispatch()` remains the sole
    entry point for commands and for `system.health` (the one query op
    excluded from read-pool routing; see ADR-036 D4's own note on why)."""

    def __init__(
        self,
        handlers: dict[str, Handler],
        deps: DispatcherDeps,
        query_handlers: dict[str, Callable[[Any], Handler]] | None = None,
    ) -> None:
        self._handlers = handlers
        self._query_handlers = query_handlers or {}
        self._sessions = deps.sessions
        self._permissions = deps.permissions
        self._idempotency = deps.idempotency
        self._invocations = deps.invocations
        self._audit = deps.audit
        self._clock = deps.clock
        self._new_id = deps.new_id

    @property
    def query_handler_names(self) -> frozenset[str]:
        """The operations `composition.py` should route to the read pool
        instead of `dispatch()`'s own write-executor submission."""
        return frozenset(self._query_handlers)

    def dispatch(self, request: ApiRequest) -> dict[str, Any]:
        """Execute one request; return a success or API-006 error envelope.
        A correlation_id is minted here and returned on every path."""
        correlation_id = self._new_id()
        try:
            return self._run(request, correlation_id)
        except Exception as exc:  # API ingress: every failure → one model
            # API-006: an unexpected failure returns the `internal` envelope,
            # honestly (never a synthesized success, never a dropped
            # connection). The API boundary is a supervision point (11 §9).
            return self.error_envelope(exc, correlation_id)

    def error_envelope(self, exc: Exception, correlation_id: str) -> dict[str, Any]:
        """The API-006 envelope for any exception, by kind — shared by
        `dispatch()`'s own top-level catch above and composition.py's
        read-pool orchestration (`_dispatch_query`), which cannot reuse
        `dispatch()` itself: `dispatch()` always runs a query's handler
        on the write-executor, defeating the read pool's whole purpose."""
        if isinstance(exc, ApiError):
            return {"ok": False, "error": exc.to_envelope(correlation_id)}
        error = ApiError("internal", f"internal error: {exc}")
        return {"ok": False, "error": error.to_envelope(correlation_id)}

    def prepare_query(
        self, request: ApiRequest, correlation_id: str
    ) -> tuple[dict[str, Any], HandlerContext]:
        """Phase 1 of a read-pool-routed query dispatch (ADR-036 D4,
        resumed): everything `_run` does up through `_record_start`,
        unchanged in substance — registry lookup, session auth, schema
        validation, scope + channel checks, the invocation/audit
        'dispatched' bookkeeping. `composition.py` runs this on the
        write-executor (every step here touches a write-connection-bound
        store), then hands the handler call itself to the read pool
        (`run_query_handler`) before returning here for
        `finish_query`/`fail_query` — the three-phase split finding 1
        agreed on. `correlation_id` is minted by the caller (`Core.new_id`
        is pure — no DB touch — so composition.py mints it directly,
        outside any executor submission, exactly once per request).
        Authenticate-before-registered, matching `_run`'s own order
        exactly (defensive: composition.py only ever calls this for a
        name already in `query_handler_names`, so `_registered` cannot
        actually fail here today — but the order still shouldn't drift
        from `_run`'s)."""
        principal, first_party = self._authenticate(request.session_token)
        entry = self._registered(request.operation)
        self._validate(entry, request)
        self._authorize(entry, principal)
        self._authorize_channel(entry, first_party)
        context = HandlerContext(
            principal=principal,
            correlation_id=correlation_id,
            trigger="cli" if first_party else principal,
            first_party=first_party,
        )
        self._record_start(entry, context)
        return entry, context

    def run_query_handler(
        self,
        name: str,
        connection: Any,
        context: HandlerContext,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Phase 2: build the query handler fresh against whichever
        read-pool connection the caller checked out for this call, then
        run it — never against a boot-time, write-connection-bound
        instance (D4's per-call-construction finding: the whole point of
        moving a query here is that a handler closed over one connection
        forever would only ever use that one pool worker, not all four)."""
        return self._query_handlers[name](connection)(context, params)

    def finish_query(
        self, context: HandlerContext, result: dict[str, Any]
    ) -> dict[str, Any]:
        """Phase 3, success path — mirrors `_execute`'s own success
        branch. No `_store_idempotent` call: query operations never carry
        an idempotency key (`_validate`'s own gate is command-only), so
        it would always be a no-op."""
        self._finish(context.correlation_id, "ok")
        return {
            "ok": True,
            "result": result,
            "correlation_id": context.correlation_id,
        }

    def fail_query(self, correlation_id: str) -> None:
        """Phase 3, failure path — mirrors `_execute`'s own
        `except ApiError: self._finish(..., 'failed'); raise` branch."""
        self._finish(correlation_id, "failed")

    def _run(self, request: ApiRequest, correlation_id: str) -> dict[str, Any]:
        principal, first_party = self._authenticate(request.session_token)
        entry = self._registered(request.operation)
        self._validate(entry, request)
        if entry["kind"] == "command":
            cached = self._idempotent_replay(request)
            if cached is not None:
                return cached
        self._authorize(entry, principal)
        self._authorize_channel(entry, first_party)
        context = HandlerContext(
            principal=principal,
            correlation_id=correlation_id,
            trigger="cli" if first_party else principal,
            first_party=first_party,
        )
        return self._execute(entry, request, context)

    def _authenticate(self, token: str) -> tuple[str, bool]:
        try:
            session = self._sessions.resolve(token)
        except SessionInvalid as exc:
            raise ApiError("permission_denied", "no valid session") from exc
        return session.principal, session.first_party

    def _registered(self, operation: str) -> dict[str, Any]:
        entry = registry_operation(operation)
        if entry is None:
            raise ApiError("not_found", f"unknown operation {operation!r}")
        return entry

    def _validate(self, entry: dict[str, Any], request: ApiRequest) -> None:
        if entry["kind"] == "command" and not request.idempotency_key:
            raise ApiError(
                "invalid_request",
                f"command {entry['name']} requires an idempotency key (API-004)",
            )
        self._validate_schema(entry, request)

    def _validate_schema(self, entry: dict[str, Any], request: ApiRequest) -> None:
        """ADR-010 Ruling 4: when the operation has an attached
        `request_schema` (a raw Pydantic class — see `registry/__init__.py`'s
        `OperationSchemas`), validate `request.params` against it. Applies to
        commands and queries alike, whenever a schema is attached; operations
        without one (most of the registry, still — Ruling 1's rollout is
        additive) are untouched. The handler still receives the original,
        unmodified `request.params` — this is a gate, not a transform."""
        schema = entry.get("request_schema")
        if schema is None:
            return
        try:
            schema.model_validate(request.params)
        except ValidationError as exc:
            raise ApiError(
                "invalid_request",
                f"{entry['name']} request failed schema validation",
                details={"field_errors": _sanitized_field_errors(exc)},
            ) from exc

    def _idempotent_replay(self, request: ApiRequest) -> dict[str, Any] | None:
        import json

        cached = self._idempotency.get(request.idempotency_key or "")
        return json.loads(cached) if cached is not None else None

    def _authorize(self, entry: dict[str, Any], principal: str) -> None:
        scope = entry["scope"]
        if scope is None:
            return
        try:
            self._permissions.check(principal, scope)
        except PermissionDenied as denied:
            raise ApiError(
                "permission_denied",
                f"missing scope {scope}",
                details={"scope": scope},
            ) from denied

    def _authorize_channel(self, entry: dict[str, Any], first_party: bool) -> None:
        """ADR 002: first_party_only is a CHANNEL control, checked here after
        _authorize's capability check — independent of it, both required.
        Deliberately a distinct error code from permission_denied (ADR 002
        Amendment §3): collapsing the two would hide which gate refused."""
        if not entry["first_party_only"]:
            return
        if not first_party:
            raise ApiError(
                "first_party_required",
                f"{entry['name']} may only be approved from a first-party session",
            )

    def _execute(
        self, entry: dict[str, Any], request: ApiRequest, context: HandlerContext
    ) -> dict[str, Any]:
        self._record_start(entry, context)
        try:
            result = self._handlers[entry["name"]](context, request.params)
        except ApiError:
            self._finish(context.correlation_id, "failed")
            raise
        self._finish(context.correlation_id, "ok")
        response = {
            "ok": True,
            "result": result,
            "correlation_id": context.correlation_id,
        }
        self._store_idempotent(entry, request, response)
        return response

    def _record_start(self, entry: dict[str, Any], context: HandlerContext) -> None:
        now = self._clock.now().isoformat()
        self._invocations.start(
            Invocation(
                id=self._new_id(),
                correlation_id=context.correlation_id,
                kind=entry["kind"],
                operation=entry["name"],
                principal=context.principal,
                trigger=context.trigger,
                started=now,
                finished=None,
                outcome=None,
            )
        )
        self._audit.record(
            context.principal,
            f"{entry['name']}.dispatched",
            {"trigger": context.trigger},
            correlation_id=context.correlation_id,
        )

    def _finish(self, correlation_id: str, outcome: str) -> None:
        invocation = self._invocations.by_correlation(correlation_id)
        now = self._clock.now().isoformat()
        self._invocations.finish(invocation.id, outcome, now)
        self._audit.record(
            invocation.principal,
            f"{invocation.operation}.{outcome}",
            None,
            correlation_id=correlation_id,
        )

    def _store_idempotent(
        self, entry: dict[str, Any], request: ApiRequest, response: dict[str, Any]
    ) -> None:
        if entry["kind"] == "command" and request.idempotency_key:
            import json

            self._idempotency.put(
                request.idempotency_key,
                json.dumps(response),
                self._clock.now().isoformat(),
            )
