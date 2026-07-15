"""Operation/event/error registry — served, deterministic, the contract's
source of truth (12 §16)."""

from __future__ import annotations

import json

from kang.api.errors import ERROR_CODES
from kang.api.registry import operation, registry_json, registry_snapshot


def test_registry_serves_the_m4_operations():
    names = {op["name"] for op in registry_snapshot()["operations"]}
    assert {
        "registry.get",
        "task.create",
        "task.get",
        "explain.invocation",
    } <= names


def test_commands_require_idempotency_keys_queries_do_not():
    assert operation("task.create")["idempotency"] == "key-required"
    assert operation("task.create")["kind"] == "command"
    assert operation("task.get")["idempotency"] == "none"
    assert operation("explain.invocation")["kind"] == "query"


def test_error_codes_are_the_closed_api_006_enum():
    codes = set(registry_snapshot()["error_codes"])
    assert codes == set(ERROR_CODES)
    assert "permission_denied" in codes and "confirmation_required" in codes


def test_event_types_mirror_the_bus_vocabulary():
    names = {et["name"] for et in registry_snapshot()["event_types"]}
    assert {"task.created", "task.updated"} <= names


def test_unregistered_operation_is_none():
    assert operation("task.teleport") is None


def test_registry_serves_as_json_deterministically():
    parsed = json.loads(registry_json())
    assert parsed == registry_snapshot()
    assert registry_json() == registry_json()  # byte-stable (13 §2.4)
    assert parsed["contract_version"] == 1
