"""Pairing lints — over-privilege refused at load (05 §8, 10 §2.6)."""

from __future__ import annotations

import pytest

from kang.kernel.permissions.pairing import PairingViolation, lint_grants


def test_clean_grants_pass():
    lint_grants(
        {
            "kang": ("*",),
            "agent:planner": ("events.publish:kang", "memory.read:planning"),
            "agent:researcher": ("web.fetch:any", "memory.read:planning"),
        }
    )


def test_non_kang_wildcard_is_refused():
    with pytest.raises(PairingViolation, match="wildcard"):
        lint_grants({"agent:planner": ("*",)})


def test_non_kang_qualifier_wildcard_is_refused():
    with pytest.raises(PairingViolation, match="wildcard"):
        lint_grants({"agent:planner": ("events.publish:*",)})


def test_kang_may_hold_wildcard():
    lint_grants({"kang": ("*",)})


def test_web_fetch_with_sensitive_memory_is_refused():
    with pytest.raises(PairingViolation, match="web.fetch"):
        lint_grants({"agent:x": ("web.fetch:any", "memory.read:sensitive")})


def test_web_fetch_with_vault_write_is_refused():
    with pytest.raises(PairingViolation, match="web.fetch"):
        lint_grants({"agent:x": ("web.fetch:any", "vault.write:notes")})


def test_web_fetch_with_nonsensitive_memory_is_fine():
    lint_grants({"agent:x": ("web.fetch:any", "memory.read:planning")})


@pytest.mark.parametrize("scope", ["memory.propose:rule", "memory.propose:profile"])
def test_ungrantable_scopes_refused_for_anyone(scope):
    with pytest.raises(PairingViolation, match="grantable to"):
        lint_grants({"agent:x": (scope,)})
    with pytest.raises(PairingViolation):
        lint_grants({"kang": ("*", scope)})
