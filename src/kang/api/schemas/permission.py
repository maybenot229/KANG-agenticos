"""Request/response schemas for `permission.list` (ADR-010 Ruling 1).

Layer: api.
Constitutional home: 09_UI §7 ("Permission management (System domain):
every grant per principal, in the same scope language as permissions.toml,
with plain-language consequence lines (08_PLUGIN Appendix B style); ...
MUST answer 'what can KANG touch?' in under a minute"), SEC-004 (capability
visibility for the human overseeing the system — this screen is the
transparency half of default-deny, not a leak).

Added 2026-08-05 for the System-domain permission screen. Read-only:
viewing grants is not itself consequential (09_UI §7 draws that line at
*changing* a grant, which this operation does not do and this session
does not build — no `grant.modify` exists).
"""

from __future__ import annotations

from pydantic import BaseModel

__all__ = [
    "PermissionListRequest",
    "PermissionListResponse",
    "PrincipalGrants",
    "ScopeGrant",
]


class PermissionListRequest(BaseModel):
    """`permission.list` params
    (operations.py::make_permission_list_handler). No fields: the handler
    takes none, mirroring `DeadlineSweepRequest`."""


class ScopeGrant(BaseModel):
    """One granted scope, in `permissions.toml`'s own string form, plus
    the 08_PLUGIN Appendix B-style plain-language sentence describing what
    holding it lets the principal do. `consequence` is the honest fallback
    sentence when a scope has no hand-written description yet (never a
    fabricated one — 09_UI §4's "never pad" rule applies here too)."""

    scope: str
    consequence: str


class PrincipalGrants(BaseModel):
    """One principal's full grant set. Principals are in `permissions.
    toml`'s own file order (whatever `load_grants` returned); `scopes` is
    sorted (`PermissionEngine.snapshot()`), not file order — the engine
    stores a principal's scopes as a `frozenset` internally, which has no
    stable order to preserve, so sorting is what makes this deterministic
    across runs rather than incidental hash order."""

    principal: str
    scopes: list[ScopeGrant]


class PermissionListResponse(BaseModel):
    """`permission.list` result: every principal currently holding a
    grant, none omitted — 09_UI §7's "what can KANG touch?" is a
    completeness question, not a filtered one."""

    grants: list[PrincipalGrants]
