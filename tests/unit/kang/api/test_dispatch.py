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


def _build(grants=None, query_handlers=None):
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
        query_handlers=query_handlers,
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


# --- ADR-036 D4 (resumed): the read-pool-routed phase methods. `dispatch()`
# itself is proven unchanged by every test above still passing verbatim;
# these prove the new methods composition.py's query_routing._dispatch_query
# calls instead, in isolation from any real executor/pool.


def test_query_handler_names_reflects_the_query_handlers_table():
    dispatcher, *_ = _build(query_handlers={"task.get": lambda conn: None})
    assert dispatcher.query_handler_names == frozenset({"task.get"})


def test_query_handler_names_is_empty_by_default():
    dispatcher, *_ = _build()
    assert dispatcher.query_handler_names == frozenset()


def test_prepare_query_authenticates_validates_and_records_start():
    dispatcher, invocations, audit_log, _ = _build(
        query_handlers={"task.get": lambda conn: None}
    )
    entry, context = dispatcher.prepare_query(
        ApiRequest("task.get", {"id": "t-1"}, VALID_TOKEN), "cid-1"
    )
    assert entry["name"] == "task.get"
    assert context.principal == "kang"
    assert context.correlation_id == "cid-1"
    invocation = invocations.by_correlation("cid-1")
    assert invocation.operation == "task.get" and invocation.outcome is None
    actions = [
        r.entry.action
        for m in audit_log.months()
        for r in audit_log.records(m)
        if r.entry.correlation_id == "cid-1"
    ]
    assert "task.get.dispatched" in actions


def test_prepare_query_refuses_a_bad_session_before_registry_lookup():
    # Mirrors _run's own order: authenticate before registered, so a bad
    # session never leaks whether an unrelated operation name is valid.
    dispatcher, *_ = _build(query_handlers={"task.get": lambda conn: None})
    try:
        dispatcher.prepare_query(
            ApiRequest("task.get", {}, "bogus-token"), "cid-2"
        )
        raise AssertionError("expected ApiError")
    except ApiError as exc:
        assert exc.code == "permission_denied"


def test_run_query_handler_builds_fresh_against_the_given_connection():
    seen_connections = []

    def factory(conn):
        seen_connections.append(conn)

        def handler(context, params):
            return {"echo": params.get("value"), "principal": context.principal}

        return handler

    dispatcher, *_ = _build(query_handlers={"task.get": factory})
    context = dispatcher.prepare_query(
        ApiRequest("task.get", {"id": "t-1", "value": 9}, VALID_TOKEN), "cid-3"
    )[1]
    sentinel_connection = object()
    result = dispatcher.run_query_handler(
        "task.get", sentinel_connection, context, {"value": 9}
    )
    assert seen_connections == [sentinel_connection]  # never the write conn
    assert result == {"echo": 9, "principal": "kang"}


def test_finish_query_marks_invocation_ok_and_builds_the_response_envelope():
    dispatcher, invocations, audit_log, _ = _build(
        query_handlers={"task.get": lambda conn: None}
    )
    _, context = dispatcher.prepare_query(
        ApiRequest("task.get", {"id": "t-1"}, VALID_TOKEN), "cid-4"
    )
    response = dispatcher.finish_query(context, {"echo": 1})
    assert response == {"ok": True, "result": {"echo": 1}, "correlation_id": "cid-4"}
    assert invocations.by_correlation("cid-4").outcome == "ok"
    actions = [
        r.entry.action
        for m in audit_log.months()
        for r in audit_log.records(m)
        if r.entry.correlation_id == "cid-4"
    ]
    assert "task.get.ok" in actions


def test_fail_query_marks_invocation_failed():
    dispatcher, invocations, audit_log, _ = _build(
        query_handlers={"task.get": lambda conn: None}
    )
    dispatcher.prepare_query(
        ApiRequest("task.get", {"id": "t-1"}, VALID_TOKEN), "cid-5"
    )
    dispatcher.fail_query("cid-5")
    assert invocations.by_correlation("cid-5").outcome == "failed"
    actions = [
        r.entry.action
        for m in audit_log.months()
        for r in audit_log.records(m)
        if r.entry.correlation_id == "cid-5"
    ]
    assert "task.get.failed" in actions


def test_error_envelope_wraps_apierror_verbatim():
    dispatcher, *_ = _build()
    envelope = dispatcher.error_envelope(
        ApiError("conflict", "revision mismatch"), "cid-6"
    )
    assert envelope == {
        "ok": False,
        "error": {
            "code": "conflict",
            "message": "revision mismatch",
            "correlation_id": "cid-6",
            "retryable": False,
        },
    }


def test_error_envelope_wraps_an_unexpected_exception_as_internal():
    dispatcher, *_ = _build()
    envelope = dispatcher.error_envelope(RuntimeError("kaboom"), "cid-7")
    assert envelope["error"]["code"] == "internal"
    assert envelope["error"]["retryable"] is True


def test_prepare_run_finish_query_together_match_dispatch_shape():
    # Proves the phased path and dispatch()'s own single-call path produce
    # the identical response shape for an equivalent successful query —
    # the split changes threading, never the observable contract.
    def factory(conn):
        return lambda context, params: {"echo": params.get("value")}

    dispatcher, invocations, _, _ = _build(query_handlers={"task.get": factory})
    entry, context = dispatcher.prepare_query(
        ApiRequest("task.get", {"id": "t-1", "value": 5}, VALID_TOKEN), "cid-8"
    )
    result = dispatcher.run_query_handler(
        entry["name"], object(), context, {"value": 5}
    )
    response = dispatcher.finish_query(context, result)

    baseline = dispatcher.dispatch(ApiRequest("registry.get", {}, VALID_TOKEN))
    assert set(response) == set(baseline)  # {"ok", "result", "correlation_id"}
    assert response["ok"] is True
    assert invocations.by_correlation("cid-8").outcome == "ok"
