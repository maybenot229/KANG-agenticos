"""Pairing lints — over-privilege is a load-time failure, not a judgment.

Layer: kernel/permissions.
Constitutional home: 10_SECURITY §2.6 (least privilege structurally: pairing
constraints make over-privilege a lint failure), 05_AGENTS §8 (the pairing
rules: no principal combines `web.fetch` with `memory.read:sensitive`; no
Tier-0-input tool with `vault.write` outside a quarantined inbox;
`memory.propose:rule|profile` grantable to no one; wildcard scopes only for
`kang`). Run at grant load; a violation refuses the grant set (fail closed).

The scope families these rules name (web.fetch, memory.read, vault.write,
memory.propose) do not all have live grants yet — the LINT exists now so it
guards the moment they do (18 §1.2: disciplines ship before their subjects).
"""

from __future__ import annotations

from collections.abc import Mapping

from kang.kernel.permissions.scope import parse_scope

__all__ = ["PairingViolation", "lint_grants"]

KANG = "kang"

# Forbidden co-grants by family: a single principal MUST NOT hold both
# (05 §8 / 06 §12.2 read/act separation — untrusted input never meets
# sensitive reads or unquarantined writes).
_FORBIDDEN_FAMILY_PAIRS = (
    ("web.fetch", "memory.read:sensitive"),
    ("web.fetch", "vault.write"),
)

# Scopes grantable to no principal at all (the gate enforces independently —
# defense in depth): rule/profile memory proposals (05 §8, M-003 spirit).
_UNGRANTABLE = ("memory.propose:rule", "memory.propose:profile")


class PairingViolation(Exception):
    """A grant set violates a pairing / wildcard / ungrantable rule."""


def _holds(scopes: frozenset[str], needle: str) -> bool:
    """Whether the raw scope set holds `needle`, matched by family+qualifier
    (a family-only needle matches any qualifier of that family)."""
    want = parse_scope(needle)
    for raw in scopes:
        have = parse_scope(raw)
        if have.family != want.family:
            continue
        if want.qualifier is None or have.qualifier == want.qualifier:
            return True
    return False


def lint_grants(grants: Mapping[str, tuple[str, ...]]) -> None:
    """Raise PairingViolation on the first rule a principal breaks."""
    for principal, raw_scopes in grants.items():
        scopes = frozenset(raw_scopes)
        _lint_wildcard(principal, scopes)
        _lint_ungrantable(principal, scopes)
        _lint_forbidden_pairs(principal, scopes)


def _lint_wildcard(principal: str, scopes: frozenset[str]) -> None:
    if principal == KANG:
        return
    for raw in scopes:
        if parse_scope(raw).is_wildcard:
            raise PairingViolation(
                f"{principal!r} holds wildcard scope {raw!r}; wildcards are "
                "reserved for principal 'kang' (05 §8)"
            )


def _lint_ungrantable(principal: str, scopes: frozenset[str]) -> None:
    for ungrantable in _UNGRANTABLE:
        if _holds(scopes, ungrantable):
            raise PairingViolation(
                f"{principal!r} holds {ungrantable!r}, which is grantable to "
                "no principal (05 §8)"
            )


def _lint_forbidden_pairs(principal: str, scopes: frozenset[str]) -> None:
    for left, right in _FORBIDDEN_FAMILY_PAIRS:
        if _holds(scopes, left) and _holds(scopes, right):
            raise PairingViolation(
                f"{principal!r} combines {left!r} with {right!r} — read/act "
                "separation forbids this pairing (05 §8, 06 §12.2)"
            )
