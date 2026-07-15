"""Scope parsing + covering (SEC-004 / 05 §8 vocabulary)."""

from __future__ import annotations

import pytest

from kang.kernel.permissions.scope import parse_scope


def test_parses_family_and_qualifier():
    scope = parse_scope("events.publish:kang")
    assert scope.family == "events.publish"
    assert scope.qualifier == "kang"
    assert not scope.is_wildcard


def test_parses_bare_family():
    scope = parse_scope("vault.read")
    assert scope.family == "vault.read"
    assert scope.qualifier is None


def test_wildcard_is_recognised():
    assert parse_scope("*").is_wildcard
    assert parse_scope("events.publish:*").is_wildcard


def test_empty_scope_rejected():
    with pytest.raises(ValueError):
        parse_scope("   ")


def test_empty_qualifier_rejected():
    with pytest.raises(ValueError):
        parse_scope("events.publish:")


def test_exact_scope_covers_itself():
    grant = parse_scope("events.publish:kang")
    assert grant.covers(parse_scope("events.publish:kang"))


def test_different_qualifier_not_covered():
    grant = parse_scope("events.publish:kang")
    assert not grant.covers(parse_scope("events.publish:plugin.x"))


def test_different_family_not_covered():
    grant = parse_scope("events.publish:kang")
    assert not grant.covers(parse_scope("memory.read:planning"))


def test_bare_wildcard_covers_everything():
    grant = parse_scope("*")
    assert grant.covers(parse_scope("events.publish:kang"))
    assert grant.covers(parse_scope("memory.read:sensitive"))


def test_qualifier_wildcard_covers_its_family_only():
    grant = parse_scope("events.publish:*")
    assert grant.covers(parse_scope("events.publish:plugin.x"))
    assert not grant.covers(parse_scope("memory.read:planning"))
