"""`require_confirmation` — the shared consequential-command gate (ADR-021).

Layer: api.
Constitutional home: 12_API §7 ("the command returns `confirmation_required`
+ a `held_action` resource"), 05_AGENTS Appendix D (the closed consequential
list), ADR-001/ADR-002 (the lifecycle and channel this gate feeds).

12_API §2's thinness rule keeps the dispatcher itself domain-ignorant, so
each consequential handler owns its own gate check and calls this rather
than the dispatcher deciding generically ("this operation is consequential")
— only the handler knows the right `action`/`reversibility` text. This
helper exists so that decision doesn't get reinvented per operation: it is
the one place that builds a `HeldAction`, persists it, and raises the
`confirmation_required` envelope — every future consequential command's
gate should call this, not hand-roll the same four steps again.

`job.disable`/`job.enable` (ADR-021) are this helper's first callers.

`ConfirmationDeps`/`ConfirmationRequest` (11 §4: beyond a few parameters, a
dataclass — this split is what keeps `require_confirmation` under the size
lint's hard parameter limit): `Deps` groups the collaborators any caller
wires once; `Request` groups the held action's own content, which is
exactly `HeldAction`'s own field set minus what this helper computes
itself (id, correlation_id, timestamps, status).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Callable, NoReturn

from kang.api.dispatch import HandlerContext
from kang.api.errors import ApiError
from kang.domain.ports.clock import Clock
from kang.domain.ports.held_action import HeldAction, HeldActionStore

__all__ = ["ConfirmationDeps", "ConfirmationRequest", "require_confirmation"]

EXPIRY = timedelta(hours=24)  # 12 §7


@dataclass(frozen=True)
class ConfirmationDeps:
    held_actions: HeldActionStore
    clock: Clock
    new_id: Callable[[], str]


@dataclass(frozen=True)
class ConfirmationRequest:
    operation: str  # registry name — resolves commit_mode on approval
    action: str  # free-text: what will happen
    reason: str  # the requester's stated reasoning
    reversibility: str
    params: dict[str, Any]  # replayed against `operation` once approved


def require_confirmation(
    deps: ConfirmationDeps, context: HandlerContext, request: ConfirmationRequest
) -> NoReturn:
    """Create a pending held action and raise `confirmation_required`
    (API-006: "returns the held-action reference")."""
    now = deps.clock.now()
    held = HeldAction(
        id=deps.new_id(),
        operation=request.operation,
        action=request.action,
        principal=context.principal,
        reason=request.reason,
        reversibility=request.reversibility,
        correlation_id=context.correlation_id,
        created_at=now.isoformat(),
        expires_at=(now + EXPIRY).isoformat(),
        params=request.params,
    )
    deps.held_actions.create(held)
    raise ApiError(
        "confirmation_required",
        f"{request.operation} requires confirmation: {request.action}",
        details={
            "id": held.id,
            "operation": held.operation,
            "action": held.action,
            "principal": held.principal,
            "reason": held.reason,
            "reversibility": held.reversibility,
            "correlation_id": held.correlation_id,
            "created_at": held.created_at,
            "expires_at": held.expires_at,
            "status": held.status,
        },
    )
