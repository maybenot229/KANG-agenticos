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
    """Runs the §5 pipeline for every operation."""

    def __init__(self, handlers: dict[str, Handler], deps: DispatcherDeps) -> None:
        self._handlers = handlers
        self._sessions = deps.sessions
        self._permissions = deps.permissions
        self._idempotency = deps.idempotency
        self._invocations = deps.invocations
        self._audit = deps.audit
        self._clock = deps.clock
        self._new_id = deps.new_id

    def dispatch(self, request: ApiRequest) -> dict[str, Any]:
        """Execute one request; return a success or API-006 error envelope.
        A correlation_id is minted here and returned on every path."""
        correlation_id = self._new_id()
        try:
            return self._run(request, correlation_id)
        except ApiError as error:
            return {"ok": False, "error": error.to_envelope(correlation_id)}
        except Exception as unexpected:  # API ingress: every failure → one model
            # API-006: an unexpected failure returns the `internal` envelope,
            # honestly (never a synthesized success, never a dropped
            # connection). The API boundary is a supervision point (11 §9).
            error = ApiError("internal", f"internal error: {unexpected}")
            return {"ok": False, "error": error.to_envelope(correlation_id)}

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
