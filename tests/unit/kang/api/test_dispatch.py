"""API request lifecycle (12 §5) against fakes — the pipeline in isolation.

Proves the constitutional order and its guarantees without a transport:
authentication refusal, unknown-operation, idempotency-key requirement,
permission handoff to the M3 engine, idempotent replay, invocation + audit
recording, and the API-006 error model on every path.
"""

from __future__ import annotations

import itertools

from kang.adapters.fakes.api_stores import (
    FakeIdempotencyStore,
    FakeInvocationStore,
    FakeSessionStore,
)
from kang.adapters.fakes.audit_log import FakeAuditLog
from kang.adapters.fakes.clock import FakeClock
from kang.api.dispatch import ApiRequest, Dispatcher, DispatcherDeps
from kang.api.errors import ApiError
from kang.domain.ports.session import Session
from kang.kernel.audit.service import AuditService
from kang.kernel.permissions.engine import PermissionEngine

VALID_TOKEN = "tok-kang"
PLUGIN_TOKEN = "tok-plugin"


def _build(grants=None):
    clock = FakeClock()
    sessions = FakeSessionStore()
    sessions.create(
        Session(token=VALID_TOKEN, principal="kang", first_party=True, created_at="t")
    )
    sessions.create(
        Session(
            token=PLUGIN_TOKEN,
            principal="plugin:sample",
            first_party=False,
            created_at="t",
        )
    )
    audit_log = FakeAuditLog()
    invocations = FakeInvocationStore()
    ids = (f"id-{n}" for n in itertools.count())
    calls: list = []

    def ok_handler(context, params):
        calls.append((context.principal, context.correlation_id, params))
        return {"echo": params.get("value")}

    handlers = {
        # borrow registered operation names so registry lookup succeeds
        "registry.get": ok_handler,
        "task.create": ok_handler,
        "task.get": ok_handler,
        "held_action.approve": ok_handler,
    }
    dispatcher = Dispatcher(
        handlers,
        DispatcherDeps(
            sessions=sessions,
            permissions=PermissionEngine(grants or {"kang": ("*",)}),
            idempotency=FakeIdempotencyStore(),
            invocations=invocations,
            audit=AuditService(audit_log, clock),
            clock=clock,
            new_id=lambda: next(ids),
        ),
    )
    return dispatcher, invocations, audit_log, calls


def test_no_session_is_refused():
    dispatcher, *_ = _build()
    response = dispatcher.dispatch(
        ApiRequest("registry.get", {}, session_token="bogus")
    )
    assert response["ok"] is False
    assert response["error"]["code"] == "permission_denied"
    assert "correlation_id" in response["error"]


def test_unknown_operation_is_not_found():
    dispatcher, *_ = _build()
    response = dispatcher.dispatch(ApiRequest("task.teleport", {}, VALID_TOKEN))
    assert response["error"]["code"] == "not_found"


def test_command_without_idempotency_key_is_invalid():
    dispatcher, *_ = _build()
    response = dispatcher.dispatch(ApiRequest("task.create", {}, VALID_TOKEN))
    assert response["error"]["code"] == "invalid_request"


def test_query_succeeds_and_records_invocation_and_audit():
    dispatcher, invocations, audit_log, calls = _build()
    response = dispatcher.dispatch(
        ApiRequest("registry.get", {"value": 7}, VALID_TOKEN)
    )
    assert response["ok"] is True
    assert response["result"] == {"echo": 7}
    correlation_id = response["correlation_id"]
    # invocation recorded, finished ok
    invocation = invocations.by_correlation(correlation_id)
    assert invocation.operation == "registry.get"
    assert invocation.outcome == "ok"
    # audit chain threaded by the same correlation id
    actions = [
        r.entry.action
        for m in audit_log.months()
        for r in audit_log.records(m)
        if r.entry.correlation_id == correlation_id
    ]
    assert "registry.get.dispatched" in actions and "registry.get.ok" in actions


def test_permission_denied_names_the_scope():
    # task.get requires task.read; a principal without it is denied.
    dispatcher, *_ = _build(grants={"kang": ()})
    # re-point the session principal-less grant: kang has no scopes here
    response = dispatcher.dispatch(
        ApiRequest("task.get", {"id": "task-1"}, VALID_TOKEN)
    )
    assert response["error"]["code"] == "permission_denied"
    assert response["error"]["details"]["scope"] == "task.read"


def test_command_replays_the_original_outcome_for_a_repeated_key():
    # task.create now carries a real request_schema (ADR-010); `title` is
    # required for the call to pass _validate at all. `value` is an extra
    # field the schema ignores (Pydantic default) — kept, and varied
    # between calls, to prove a replay short-circuits before the handler
    # (and any re-validation of the second call's own body) ever runs.
    dispatcher, invocations, _, calls = _build()
    first = dispatcher.dispatch(
        ApiRequest(
            "task.create", {"title": "t", "value": 1}, VALID_TOKEN, idempotency_key="k1"
        )
    )
    second = dispatcher.dispatch(
        ApiRequest(
            "task.create",
            {"title": "t", "value": 999},
            VALID_TOKEN,
            idempotency_key="k1",
        )
    )
    assert second == first  # original outcome returned, not re-executed
    assert len(calls) == 1  # the handler ran exactly once


def test_handler_apierror_becomes_the_error_envelope_and_records_failure():
    dispatcher, invocations, _, _ = _build()

    def boom(context, params):
        raise ApiError("conflict", "revision mismatch")

    dispatcher._handlers["registry.get"] = boom  # type: ignore[attr-defined]
    response = dispatcher.dispatch(ApiRequest("registry.get", {}, VALID_TOKEN))
    assert response["error"]["code"] == "conflict"
    invocation = invocations.by_correlation(response["error"]["correlation_id"])
    assert invocation.outcome == "failed"


def test_plugin_session_is_refused_first_party_only_operation():
    # ADR 002: held_action.approve is channel-gated. A plugin session holds
    # no scope for it (scope=None) so a plain permission check would pass —
    # the channel check is what refuses it, with its own distinct code.
    dispatcher, *_ = _build()
    response = dispatcher.dispatch(
        ApiRequest(
            "held_action.approve",
            {"id": "held-1"},
            PLUGIN_TOKEN,
            idempotency_key="k-plugin-approve",
        )
    )
    assert response["error"]["code"] == "first_party_required"
    assert response["error"]["code"] != "permission_denied"


def test_first_party_session_may_call_first_party_only_operation():
    dispatcher, *_ = _build()
    response = dispatcher.dispatch(
        ApiRequest(
            "held_action.approve",
            {"id": "held-1"},
            VALID_TOKEN,
            idempotency_key="k-kang-approve",
        )
    )
    assert response["ok"] is True


def test_unexpected_exception_becomes_internal():
    dispatcher, *_ = _build()

    def crash(context, params):
        raise RuntimeError("kaboom")

    dispatcher._handlers["registry.get"] = crash  # type: ignore[attr-defined]
    response = dispatcher.dispatch(ApiRequest("registry.get", {}, VALID_TOKEN))
    assert response["error"]["code"] == "internal"
    assert response["error"]["retryable"] is True


def test_schema_violation_is_invalid_request_and_never_reaches_the_handler():
    # ADR-010 Ruling 4: task.create carries a real request_schema; a
    # missing required field is refused by _validate before the handler
    # (ok_handler, which would otherwise happily echo it) ever runs.
    dispatcher, *_, calls = _build()
    response = dispatcher.dispatch(
        ApiRequest("task.create", {}, VALID_TOKEN, idempotency_key="k1")
    )
    assert response["ok"] is False
    assert response["error"]["code"] == "invalid_request"
    assert calls == []  # never reached the handler


def test_schema_violation_details_are_sanitized_field_errors():
    # ADR-010 Ruling 4: details.field_errors carries field path + message
    # only — never Pydantic's raw `input`/`ctx` keys, which could echo a
    # private-tier value verbatim (D010/PRD §10.14).
    dispatcher, *_ = _build()
    response = dispatcher.dispatch(
        ApiRequest("task.create", {}, VALID_TOKEN, idempotency_key="k1")
    )
    field_errors = response["error"]["details"]["field_errors"]
    assert field_errors == [{"field": "title", "message": "Field required"}]


def test_schema_less_operation_is_unaffected_by_ruling_4():
    # registry.get has no request_schema attached (Ruling 1's rollout is
    # additive, not universal yet) — arbitrary params pass through untouched.
    dispatcher, *_ = _build()
    response = dispatcher.dispatch(
        ApiRequest("registry.get", {"anything": "goes"}, VALID_TOKEN)
    )
    assert response["ok"] is True
