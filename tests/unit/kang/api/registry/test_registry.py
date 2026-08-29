"""Operation/event/error registry — served, deterministic, the contract's
source of truth (12 §16)."""

from __future__ import annotations

import json

from kang.api.errors import ERROR_CODES
from kang.api.registry import (
    OPERATIONS,
    operation,
    registry_json,
    registry_snapshot,
)


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


# ---- ADR-027: scope=None is a decision, not a default --------------------

# The ONLY operations permitted to declare no scope, each for a written
# reason in the registry (ADR-027 D2). `Dispatcher._authorize` SKIPS the
# permission engine entirely for these — it is not default-deny, so the
# set must stay closed and deliberate rather than growing by habit.
UNSCOPED_BY_DECISION = {
    # The contract itself: a client must read it before it can call
    # anything, including to learn what scopes exist. Gating it is
    # circular, and it leaks shape, never state.
    "registry.get",
    # 05_AGENTS:475 is explicit that these two are channel-gated, NOT
    # scope-gated: "the first-party channel check (not a permission scope
    # — §8) is what stands in for that second layer." Adding a scope here
    # would contradict a normative sentence.
    "held_action.approve",
    "held_action.cancel",
}


def test_only_three_operations_are_unscoped_and_each_is_deliberate():
    """ADR-027's central claim. A new operation registered with
    scope=None is reachable by ANY authenticated principal with no
    capability check at all — including, once M7 lands, an `agent:{id}`
    principal (05_AGENTS §8). This test fails on the next accidental one
    so the decision has to be made explicitly."""
    unscoped = {op["name"] for op in OPERATIONS if op["scope"] is None}
    assert unscoped == UNSCOPED_BY_DECISION


def test_the_system_metadata_reads_are_scoped():
    """Each was scope=None before ADR-027 on the reasoning that system
    metadata is not a domain resource — sound while every session
    principal was fully trusted, unsound once agent principals exist."""
    assert operation("audit.list")["scope"] == "audit.read"
    assert operation("invocation.list")["scope"] == "invocations.read"
    assert operation("permission.list")["scope"] == "permissions.read"
    assert operation("system.health")["scope"] == "system.read"
    assert operation("notification.ack")["scope"] == "notifications.ack"


def test_every_explain_operation_shares_one_scope():
    """One capability ("reconstruct why KANG did something"), not five —
    splitting them would invent authority vocabulary no consumer
    distinguishes (ADR-027 D1)."""
    explains = [op for op in OPERATIONS if op["name"].startswith("explain.")]
    assert len(explains) == 5
    assert {op["scope"] for op in explains} == {"explain.read"}


def test_kang_still_reaches_every_new_scope_through_the_wildcard():
    """ADR-027 adds authority vocabulary without granting or revoking
    anything: `kang` holds `*`, which covers each new scope."""
    from pathlib import Path

    from kang.adapters.config.permissions_loader import load_grants
    from kang.kernel.permissions.engine import build_checked_engine

    root = Path(__file__).resolve().parents[5]
    engine = build_checked_engine(
        load_grants(root / "config" / "defaults" / "permissions.toml")
    )
    for scope in (
        "audit.read",
        "invocations.read",
        "permissions.read",
        "system.read",
        "explain.read",
        "notifications.ack",
    ):
        assert engine.allows("kang", scope), scope
        # ...and a principal without the grant is refused, proving the
        # check is real rather than vacuous.
        assert not engine.allows("agent:researcher", scope), scope
