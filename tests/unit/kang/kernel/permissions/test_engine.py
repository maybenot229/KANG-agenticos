"""Permission engine — default-deny, typed denial naming the scope (SEC-004).

Property suite (13 §2.7): every principal × ungranted scope ⇒ typed denial,
zero side effects (the engine is pure — a denial cannot mutate anything).
"""

from __future__ import annotations

import pytest

from kang.kernel.permissions.engine import (
    PermissionDenied,
    PermissionEngine,
    build_checked_engine,
)
from kang.kernel.permissions.pairing import PairingViolation


@pytest.fixture
def engine() -> PermissionEngine:
    return PermissionEngine(
        {
            "kang": ("*",),
            "kernel:bus": ("events.publish:kang",),
            "agent:planner": ("events.publish:kang", "memory.read:planning"),
        }
    )


def test_exact_grant_allows(engine):
    assert engine.allows("kernel:bus", "events.publish:kang")
    engine.check("kernel:bus", "events.publish:kang")  # does not raise


def test_default_deny_for_ungranted_scope(engine):
    assert not engine.allows("agent:planner", "events.publish:plugin.x")
    with pytest.raises(PermissionDenied) as exc:
        engine.check("agent:planner", "events.publish:plugin.x")
    assert exc.value.scope == "events.publish:plugin.x"
    assert exc.value.principal == "agent:planner"


def test_unknown_principal_holds_nothing(engine):
    assert not engine.allows("agent:rogue", "events.publish:kang")
    with pytest.raises(PermissionDenied):
        engine.check("agent:rogue", "events.publish:kang")


def test_kang_wildcard_allows_anything(engine):
    engine.check("kang", "events.publish:kang")
    engine.check("kang", "memory.read:sensitive")
    engine.check("kang", "vault.write:anywhere")


def test_denial_names_the_missing_scope(engine):
    with pytest.raises(PermissionDenied, match="memory.write:fact"):
        engine.check("agent:planner", "memory.write:fact")


@pytest.mark.parametrize(
    "principal,scope",
    [
        ("agent:planner", "vault.write:notes"),
        ("kernel:bus", "memory.read:planning"),
        ("agent:rogue", "anything:at:all".replace(":", "_") + ":x"),
        ("", "events.publish:kang"),
    ],
)
def test_property_every_ungranted_pair_is_denied(engine, principal, scope):
    with pytest.raises(PermissionDenied):
        engine.check(principal, scope)


def test_snapshot_is_immutable_to_source_mutation():
    source = {"agent:x": ("events.publish:kang",)}
    engine = PermissionEngine(source)
    source["agent:x"] = ("*",)  # mutate the source after construction
    assert not engine.allows("agent:x", "vault.write:anywhere")


def test_build_checked_engine_lints_pairings():
    # "Pairing lint at load" (05 §8, 10 §2.6) runs here, in the kernel — a
    # forbidden grant set is refused before the engine is trusted.
    with pytest.raises(PairingViolation, match="wildcard"):
        build_checked_engine({"agent:x": ("*",)})


def test_build_checked_engine_returns_a_usable_engine():
    engine = build_checked_engine({"kang": ("*",), "agent:x": ("vault.read",)})
    engine.check("agent:x", "vault.read")
    assert not engine.allows("agent:x", "vault.write:notes")


class TestSnapshot:
    """09_UI §7's permission screen ("every grant per principal, in the
    same scope language as permissions.toml") reads through this — the
    claim is that it reflects exactly what's loaded, verbatim, in the
    original string form."""

    def test_returns_every_principal_and_its_raw_scope_strings(self, engine):
        snapshot = engine.snapshot()
        assert snapshot["kang"] == ("*",)
        assert snapshot["kernel:bus"] == ("events.publish:kang",)
        # Sorted, not insertion order — the source frozenset has no stable
        # order to preserve (see snapshot()'s own docstring).
        assert snapshot["agent:planner"] == (
            "events.publish:kang",
            "memory.read:planning",
        )

    def test_matches_every_principal_construction_granted(self, engine):
        assert set(engine.snapshot()) == {"kang", "kernel:bus", "agent:planner"}

    def test_reflects_no_internal_scope_objects_only_strings(self, engine):
        for scopes in engine.snapshot().values():
            for scope in scopes:
                assert isinstance(scope, str)
