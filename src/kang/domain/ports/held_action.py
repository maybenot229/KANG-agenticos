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

Lifecycle per ADR 001 (held-action crash-semantics): `approved` means Kang
said yes, not that the effect happened. `executed` is the terminal state
recording the effect actually committed. Which of the two `commit_mode`s
(`transactional` | `redrive`, ADR 001 Amendment) governs the approved→executed
step is registry metadata for `operation` — not stored on the row.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

__all__ = [
    "HeldAction",
    "HeldActionError",
    "HeldActionExpired",
    "HeldActionNotFound",
    "HeldActionStore",
]

HELD_ACTION_STATUSES = ("pending", "approved", "executed", "cancelled")


@dataclass(frozen=True)
class HeldAction:
    """A consequential action held pending confirmation (12 §7 fields)."""

    id: str
    operation: str  # registry operation name (e.g. 'memory.delete') —
    #   resolves `commit_mode` on approval/recovery (ADR 001 Amendment);
    #   distinct from `action`'s free-text description below
    action: str  # what: the command/effect held (e.g. 'task.delete task-1')
    principal: str  # who asked
    reason: str  # why: the requester's stated reasoning (one paragraph)
    reversibility: str  # the reversibility statement shown in the dialog
    correlation_id: str
    created_at: str
    expires_at: str  # created_at + 24h (12 §7)
    status: str = "pending"
    params: dict[str, Any] = field(default_factory=dict)  # ADR-021: the
    #   original request's params, carried so approval can replay the
    #   effect — the schema delta ADR-001's Consequences called "owed"


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
        is past expiry (the window closed), HeldActionNotFound if absent.
        `approved` records intent only — the effect has not necessarily
        committed yet (ADR 001); the caller drives it to `executed`."""
        ...

    def cancel(self, held_action_id: str) -> HeldAction:
        """Transition pending → cancelled (Kang declined, or superseded)."""
        ...

    def mark_executed(self, held_action_id: str) -> HeldAction:
        """Transition approved → executed: the held effect committed
        (ADR 001). Raises HeldActionNotFound if the action is not currently
        `approved` (guards against marking a pending or cancelled action
        executed)."""
        ...

    def approve_in_txn(self, held_action_id: str, now: str) -> HeldAction:
        """Same as `approve`, but assumes the caller already opened a
        transaction on the shared connection (ADR-021: `transactional`
        commit_mode's approve-flip and effect share one `BEGIN`/`COMMIT`) —
        does not open or close one of its own. The real adapter writes on
        its own already-held connection; the fake mutates its dict, which
        needs no transaction at all. Only `held_action.approve`'s handler
        (the one place permitted to own that transaction boundary) calls
        this — never a generic caller."""
        ...

    def mark_executed_in_txn(self, held_action_id: str) -> HeldAction:
        """Same as `mark_executed`, transaction-participating (see
        `approve_in_txn`)."""
        ...

    def approved_not_executed(self) -> list[HeldAction]:
        """Every action stuck at `approved` — the redrive-mode reconciliation
        sweep's input on restart (ADR 001 Amendment). Transactional-mode
        actions never appear here: their approve step and effect commit
        together, so a crash before commit leaves them `approved` with
        nothing to redrive, indistinguishable from freshly-approved — the
        sweep re-attempts those too, which is safe by definition of
        transactional mode (§Amendment)."""
        ...

    def expire_due(self, now: str) -> int:
        """Cancel every pending held action past its expiry as of `now`
        (the 24h sweep). Returns how many were expired."""
        ...

    def pending(self) -> list[HeldAction]:
        """All pending held actions, oldest first — the approval queue."""
        ...
