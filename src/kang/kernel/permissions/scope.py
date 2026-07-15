"""Capability scopes — the vocabulary of authority (SEC-004).

Layer: kernel/permissions.
Constitutional home: 04_ARCHITECTURE D013 §14.1 (capability-based scopes with
qualifiers), 05_AGENTS §8 (scope strings `family:qualifier`; wildcards
forbidden except for `kang`). A scope is `family:qualifier` (split on the
first colon); the bare `*` is the all-authority wildcard reserved for
`kang`. Grant `G` covers request `R` iff G is `*`, or same family and G's
qualifier is R's or `*`.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Scope", "WILDCARD", "parse_scope"]

WILDCARD = "*"


@dataclass(frozen=True)
class Scope:
    """A parsed capability. `family` is the part before the first colon
    (`events.publish`, `memory.read`); `qualifier` is the rest (`kang`,
    `sensitive`), or None for a bare family / the wildcard."""

    raw: str
    family: str
    qualifier: str | None

    @property
    def is_wildcard(self) -> bool:
        """True if this scope contains a `*` (bare or qualifier) — the
        pairing lint restricts these to principal `kang` (05 §8)."""
        return self.raw == WILDCARD or self.qualifier == WILDCARD

    def covers(self, requested: Scope) -> bool:
        """Whether holding this granted scope authorizes `requested`."""
        if self.raw == WILDCARD:
            return True
        if self.family != requested.family:
            return False
        return self.qualifier == WILDCARD or self.qualifier == requested.qualifier


def parse_scope(raw: str) -> Scope:
    """Parse a scope string. `family:qualifier` splits on the first colon;
    `*` is the wildcard; a bare family has no qualifier."""
    text = raw.strip()
    if not text:
        raise ValueError("scope must be non-empty")
    if text == WILDCARD:
        return Scope(raw=text, family=WILDCARD, qualifier=None)
    family, sep, qualifier = text.partition(":")
    if sep and not qualifier:
        raise ValueError(f"scope {raw!r} has an empty qualifier")
    return Scope(raw=text, family=family, qualifier=qualifier or None)
