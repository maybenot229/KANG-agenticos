"""Held-action port — consequential actions as data, awaiting Kang's hand.

Layer: domain/ports. Ports own their datatypes (17 §7).
Constitutional home: 12_API §7 (a consequential command returns
`confirmation_required` + a held_action resource: what/who/why/reversibility;
`held_action.approve {id}`; 24h expiry ⇒ cancelled), 09_UI §7 (the dialog
contents), 10_SECURITY §5.4 / SEC-003 (approval is out-of-band, Kang-only
from a first-party session — enforced at the API/session layer, M4; this
port is the data plumbing beneath it, built now per 18 M3).

The store transitions status; it does NOT decide who may approve — that
authority check is the API's (a plugin session MUST NOT approve, 12 §7).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

__all__ = [
    "HeldAction",
    "HeldActionError",
    "HeldActionExpired",
    "HeldActionNotFound",
    "HeldActionStore",
]

HELD_ACTION_STATUSES = ("pending", "approved", "cancelled")


@dataclass(frozen=True)
class HeldAction:
    """A consequential action held pending confirmation (12 §7 fields)."""

    id: str
    action: str  # what: the command/effect held (e.g. 'task.delete task-1')
    principal: str  # who asked
    reason: str  # why: the requester's stated reasoning (one paragraph)
    reversibility: str  # the reversibility statement shown in the dialog
    correlation_id: str
    created_at: str
    expires_at: str  # created_at + 24h (12 §7)
    status: str = "pending"


class HeldActionError(Exception):
    """Base of the held-action failure hierarchy (11 §9)."""


class HeldActionNotFound(HeldActionError):
    """No held action with the given id."""


class HeldActionExpired(HeldActionError):
    """The held action's 24h window has passed; it cannot be approved."""


class HeldActionStore(Protocol):
    """Persistence for held actions. Append-then-transition: create pending,
    then approve / cancel / expire — never edit the action's substance."""

    def create(self, held_action: HeldAction) -> None:
        """Persist a new pending held action."""
        ...

    def get(self, held_action_id: str) -> HeldAction:
        """Return the held action or raise HeldActionNotFound."""
        ...

    def approve(self, held_action_id: str, now: str) -> HeldAction:
        """Transition pending → approved. Raises HeldActionExpired if `now`
        is past expiry (the window closed), HeldActionNotFound if absent."""
        ...

    def cancel(self, held_action_id: str) -> HeldAction:
        """Transition pending → cancelled (Kang declined, or superseded)."""
        ...

    def expire_due(self, now: str) -> int:
        """Cancel every pending held action past its expiry as of `now`
        (the 24h sweep). Returns how many were expired."""
        ...

    def pending(self) -> list[HeldAction]:
        """All pending held actions, oldest first — the approval queue."""
        ...
