"""Permission engine — default-deny capability checks (SEC-004, D013).

Layer: kernel/permissions.
Constitutional home: 10_SECURITY SEC-004 (capabilities are the only
authority model; default-deny; checked at the enforcement point; no code
path exempt but `kang`), 05_AGENTS §8 (denials are typed, audited, never
silent, never retried). The engine holds the loaded grant snapshot; the
file (`permissions.toml`) is truth and the load lints pairings (pairing.py)
before an engine is trusted.

This is the enforcement mechanism; per-call audit of denials is the caller's
duty (the executor / the bus records the denial with principal +
correlation id — SEC-006). The engine stays pure and synchronous so a
permission check can never itself fail open.
"""

from __future__ import annotations

from collections.abc import Mapping

from kang.kernel.permissions.pairing import lint_grants
from kang.kernel.permissions.scope import Scope, parse_scope

__all__ = ["Grants", "PermissionDenied", "PermissionEngine", "build_checked_engine"]

# principal -> the raw scope strings granted to it (permissions.toml shape).
Grants = Mapping[str, tuple[str, ...]]


class PermissionDenied(Exception):
    """A principal lacks the scope for an action. Names the missing scope
    (12_API §6: `permission_denied` names the missing scope). Non-retryable
    (05 §8: retrying a denial is probing)."""

    def __init__(self, principal: str, scope: str) -> None:
        self.principal = principal
        self.scope = scope
        super().__init__(
            f"principal {principal!r} lacks scope {scope!r} (default-deny)"
        )


class PermissionEngine:
    """Checks capability grants. Constructed from a grant snapshot; the
    snapshot is immutable for the engine's lifetime (05 §8: per-invocation
    snapshots, grants do not change mid-flight)."""

    def __init__(self, grants: Grants) -> None:
        self._granted: dict[str, frozenset[Scope]] = {
            principal: frozenset(parse_scope(s) for s in scopes)
            for principal, scopes in grants.items()
        }

    def allows(self, principal: str, scope: str) -> bool:
        """Whether `principal` holds a grant covering `scope`. Default-deny:
        an unknown principal holds nothing."""
        requested = parse_scope(scope)
        return any(
            granted.covers(requested)
            for granted in self._granted.get(principal, frozenset())
        )

    def check(self, principal: str, scope: str) -> None:
        """Raise PermissionDenied unless `principal` is authorized."""
        if not self.allows(principal, scope):
            raise PermissionDenied(principal, scope)


def build_checked_engine(grants: Grants) -> PermissionEngine:
    """Pairing-lint the grants (10 §2.6, 05 §8 — the "lint at load" step,
    kept in the kernel where the scope policy lives), then construct the
    engine. Raises PairingViolation on a forbidden grant set; the caller
    (composition root) fails closed to Kang-only on failure (07 F8)."""
    lint_grants(grants)
    return PermissionEngine(grants)
