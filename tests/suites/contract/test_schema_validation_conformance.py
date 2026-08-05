"""Contract conformance suite (13 §2.4) — ADR-010 Ruling 4's mandated case.

Constitutional home: ADR-010's Consequences: "the test suite (13_TESTING's
conformance class) MUST include a case asserting that no `field_errors`
entry in an `invalid_request` response ever contains raw field values —
only field path + message type." This is that case, run generically
against every registered operation that currently carries a
`request_schema` (`kang.api.registry.OPERATIONS`) — so an operation joining
Ruling 1's rollout later is covered automatically, not by remembering to
add a new test per operation.

Poisons every declared field with a deliberately wrong-typed value, which
is what makes Pydantic's *built-in* type-coercion errors include a raw
`input` key in `.errors()` (the leakage vector this whole ruling exists to
close — a custom field_validator's own rejection is fine too; either path
must still come out sanitized).
"""

from __future__ import annotations

import itertools
import json

from kang.adapters.fakes.api_stores import (
    FakeIdempotencyStore,
    FakeInvocationStore,
    FakeSessionStore,
)
from kang.adapters.fakes.audit_log import FakeAuditLog
from kang.adapters.fakes.clock import FakeClock
from kang.api.dispatch import ApiRequest, Dispatcher, DispatcherDeps
from kang.api.registry import OPERATIONS
from kang.domain.ports.session import Session
from kang.kernel.audit.service import AuditService
from kang.kernel.permissions.engine import PermissionEngine

VALID_TOKEN = "tok-kang"
LEAK_MARKER = "PRIVATE-TIER-LEAK-CANARY-4f8a9c"

SCHEMA_OPERATIONS = tuple(
    entry for entry in OPERATIONS if entry["request_schema"] is not None
)


def _build_dispatcher() -> Dispatcher:
    clock = FakeClock()
    sessions = FakeSessionStore()
    sessions.create(
        Session(token=VALID_TOKEN, principal="kang", first_party=True, created_at="t")
    )
    ids = (f"id-{n}" for n in itertools.count())
    handlers = {entry["name"]: (lambda c, p: {}) for entry in OPERATIONS}
    return Dispatcher(
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


def _declared_type(prop: dict) -> str | None:
    if "type" in prop:
        return prop["type"]
    for option in prop.get("anyOf", ()):
        if "type" in option and option["type"] != "null":
            return option["type"]
    return None


def _poison_params(json_schema: dict) -> dict:
    """One deliberately wrong-typed value per declared property: an
    integer-typed field gets a string; anything else gets a dict — both
    guaranteed type mismatches regardless of the field's own constraints."""
    params = {}
    for name, prop in json_schema.get("properties", {}).items():
        if _declared_type(prop) == "integer":
            params[name] = LEAK_MARKER
        else:
            params[name] = {"poison": LEAK_MARKER}
    return params


class TestSchemaValidationNeverLeaksRawValues:
    """ADR-010 Consequences' mandated conformance case."""

    def test_the_sweep_has_operations_to_cover(self):
        # A silently-empty sweep would defeat the point — assert there is
        # at least one schema-attached operation to actually exercise.
        assert len(SCHEMA_OPERATIONS) >= 1

    def test_no_field_error_ever_contains_a_raw_value(self):
        dispatcher = _build_dispatcher()
        checked = 0
        for entry in SCHEMA_OPERATIONS:
            poisoned = _poison_params(entry["request_schema"].model_json_schema())
            idem_key = f"k-{entry['name']}" if entry["kind"] == "command" else None
            response = dispatcher.dispatch(
                ApiRequest(
                    entry["name"], poisoned, VALID_TOKEN, idempotency_key=idem_key
                )
            )
            if response["ok"]:
                # Every declared field was poisoned; a schema with no
                # fields (e.g. deadline.sweep) genuinely produced no
                # failure — nothing to check for this one operation.
                continue
            checked += 1
            assert response["error"]["code"] == "invalid_request", entry["name"]
            field_errors = response["error"]["details"]["field_errors"]
            assert field_errors, entry["name"]
            for field_error in field_errors:
                assert set(field_error.keys()) == {"field", "message"}, entry["name"]
                serialized = json.dumps(field_error)
                assert LEAK_MARKER not in serialized, (
                    f"{entry['name']}: raw poisoned value leaked into "
                    f"field_errors: {field_error}"
                )
        # Guards against the sweep going silently toothless (e.g. poisoning
        # stops working and every operation starts hitting the `ok` skip
        # branch above) — at least every field-bearing schema must actually
        # have been exercised and failed. Computed rather than hardcoded
        # (deadline.sweep and deadline.list both have zero declared
        # properties today; a future field-less operation joining the
        # registry shouldn't require touching this arithmetic too).
        fieldless = sum(
            1
            for entry in SCHEMA_OPERATIONS
            if not entry["request_schema"].model_json_schema().get("properties")
        )
        assert checked >= len(SCHEMA_OPERATIONS) - fieldless
