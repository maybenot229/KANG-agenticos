"""Held-action port — consequential actions as data, awaiting Kang's hand.

Layer: domain/ports. Ports own their datatypes (17 §7).
Constitutional home: 12_API §7 (a consequential command returns
`confirmation_required` + a held_action resource: what/who/why/reversibility;
`held_action.approve {id}`; 24h expiry ⇒ expired), 09_UI §7 (the dialog
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

`cancelled` vs. `expired` (ADR-024): `cancelled` is Kang explicitly
declining (`cancel()`); `expired` is the 24h window closing with no
decision (`expire_due()`'s sweep, ADR-022). Before ADR-024 both wrote the
same literal — deliberate at the time (the sweep had no scheduled caller),
no longer accurate once ADR-022 wired it as a real job.

Transition provenance (ADR-025): every transition OUT OF `pending`
records `decided_at` + `decided_by`. `mark_executed` deliberately does
not — `executed` inherits the approve step's provenance, because the
decision was the approval; execution is the effect landing. `reason` and
`correlation_id` describe the original REQUEST and are never rewritten,
which is exactly why the transition needed its own two fields.
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

HELD_ACTION_STATUSES = ("pending", "approved", "executed", "cancelled", "expired")


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
    decided_at: str | None = None  # ADR-025: when this row left `pending`
    decided_by: str | None = None  # ADR-025: the principal who decided.
    #   NULL on a `pending` row means "not decided yet"; NULL on a
    #   TERMINAL row means "predates ADR-025", never "nobody decided".


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

    def approve(self, held_action_id: str, now: str, decided_by: str) -> HeldAction:
        """Transition pending → approved, stamping `decided_at=now` and
        `decided_by` (ADR-025). Raises HeldActionExpired if `now` is past
        expiry (the window closed), HeldActionNotFound if absent.
        `approved` records intent only — the effect has not necessarily
        committed yet (ADR 001); the caller drives it to `executed`."""
        ...

    def cancel(self, held_action_id: str, now: str, decided_by: str) -> HeldAction:
        """Transition pending → cancelled (Kang declined, or superseded),
        stamping `decided_at=now` and `decided_by` (ADR-025 — `now` and
        `decided_by` are both new here; this method previously took
        neither, because nothing recorded when or by whom)."""
        ...

    def mark_executed(self, held_action_id: str) -> HeldAction:
        """Transition approved → executed: the held effect committed
        (ADR 001). Raises HeldActionNotFound if the action is not currently
        `approved` (guards against marking a pending or cancelled action
        executed).

        Deliberately takes no provenance (ADR-025): this is not a
        transition out of `pending`. The row keeps the `decided_at`/
        `decided_by` its approve step already stamped — the decision was
        the approval; execution is the effect landing."""
        ...

    def approve_in_txn(
        self, held_action_id: str, now: str, decided_by: str
    ) -> HeldAction:
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
        `approve_in_txn`). Takes no provenance, for the same reason
        `mark_executed` does not (ADR-025)."""
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

    def expire_due(self, now: str, decided_by: str) -> int:
        """Expire every pending held action past its expiry as of `now`
        (the 24h sweep, ADR-022), stamping `decided_at=now` and
        `decided_by` on each (ADR-025). Returns how many were expired.
        Writes `expired`, not `cancelled` (ADR-024) — distinct from Kang
        explicitly declining via `cancel()`.

        `decided_by` is the sweep's own principal, passed in rather than
        assumed here: the caller is the API handler, which reads it from
        the dispatching session — `kernel:scheduler` when the job runs
        this, `kang` if Kang invokes it by hand. A store must not know
        principal names."""
        ...

    def pending(self) -> list[HeldAction]:
        """All pending held actions, oldest first — the approval queue."""
        ...
