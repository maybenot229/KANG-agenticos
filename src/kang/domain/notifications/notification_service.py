"""Notification domain service — the ladder policy and queue semantics.

Layer: domain/notifications (17 §2: "ladder policy, queue semantics").
Deterministic, zero I/O: every decision is a pure function of its inputs, so
the determinism suite can replay a week and get the same rows (13 §2.6).
Constitutional home: 09_UI §9 (the ladder→behaviour bindings), 05_AGENTS §13
(the interruption ladder and its examples), 15_EVENT_BUS §6.2 (the queue row
is the work item), docs/adr/005-notification-queue-schema.md.

═══════════════════════════════════════════════════════════════════════════
TWO DELIBERATE SIMPLIFICATIONS LIVE IN THIS MODULE (M5, Increment 3).
Both are marked `RESERVED(trigger)` at their site — the sanctioned marker
for a deferral with a named activation trigger (11 §8) — and both are
registered in 03_ROADMAP §8's consolidated trigger registry, so they are
reviewed at every version boundary (03 §9) rather than quietly calcifying
into permanent behaviour. Neither is a guess dressed as a decision: each is
the simplest *correct-for-now* reading, with the real decision named and
deferred to the milestone that can actually make it.
═══════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

from datetime import datetime, timedelta

from kang.domain.ports.notification_store import (
    NOTIFICATION_PRIORITIES,
    Notification,
)

__all__ = [
    "DEDUP_WINDOW",
    "NotificationValidationError",
    "decide_state",
    "dedup_window_start",
    "is_duplicate",
    "notification_requested_payload",
]

# 09_UI §9: "re-notification of an unchanged item within 24h is forbidden
# (core-enforced)". Core-enforced means here, not in the UI.
DEDUP_WINDOW = timedelta(hours=24)

# The ladder→state table, assuming the most permissive product state.
#
# RESERVED(M6 product-state machine): 09_UI §9 binds two of these rows to
# product state — `critical` "never fires in Sleeping; it queues at the wake
# boundary", and `attention` gets an OS notification "only in
# Idle/Planning/Reviewing" (FR-074). The product-state machine does not
# exist until M6, so this table assumes state == Idle, the most permissive
# row of that table. That is a deliberate over-delivery, not an oversight:
# under-delivering a critical deadline alert is the failure mode this
# product cannot have (R9), and Idle is the state whose behaviour is
# unambiguous today. When M6 lands the state machine, `decide_state` gains a
# product-state parameter and these two rows become state-dependent; the
# other two (`digest`, `silent`) are state-independent and will not change.
_LADDER_ASSUMING_IDLE = {
    "critical": "delivered",  # OS notification + persistent beacon
    "attention": "delivered",  # beacon + Zone 2; OS notification in Idle
    "digest": "batched",  # never an OS notification; digest surfaces
    "silent": "suppressed",  # health panel / logs only
}


class NotificationValidationError(Exception):
    """A notification invariant was violated, before anything is persisted."""


def decide_state(priority: str) -> str:
    """The ladder's delivery decision for a queued notification.

    Pure and total over the priority enum: an unknown priority raises rather
    than defaulting, because a silent default would mean a notification
    quietly not being delivered — the failure this product least tolerates
    (09_UI §13: never dress a failure as an empty success).
    """
    if priority not in NOTIFICATION_PRIORITIES:
        raise NotificationValidationError(
            f"priority must be one of {NOTIFICATION_PRIORITIES}, got {priority!r}"
        )
    return _LADDER_ASSUMING_IDLE[priority]


def is_duplicate(
    candidate_refs: tuple[dict[str, str], ...],
    candidate_priority: str,
    recent: list[Notification],
) -> bool:
    """Whether this notification repeats an unchanged item inside the 24h
    window (09_UI §9). `recent` is the store's already-windowed lookup; this
    function stays pure so the rule is testable without a database.

    RESERVED(real notification volume + an ADR): 09_UI §9 forbids
    "re-notification of an unchanged item within 24h" but never defines
    *unchanged*. This implements the narrowest defensible reading — same
    entity refs AND same priority — which cannot produce a false suppression
    of a genuinely different notification, only a false *delivery* of one
    that a richer similarity rule would have caught. That asymmetry is
    deliberate: over-notifying is annoying, under-notifying loses a deadline.
    A content-similarity or escalation-aware definition needs real volume to
    design against, and is a future ADR with data, not a guess now.
    Deliberately NOT implemented here: treating a priority escalation
    (attention → critical for the same item) as "changed" and therefore
    deliverable. That is the most likely first refinement.
    """
    return any(
        n.entity_refs == candidate_refs and n.priority == candidate_priority
        for n in recent
    )


def dedup_window_start(now: datetime) -> datetime:
    """The lower bound of the no-re-notification window (09_UI §9)."""
    return now - DEDUP_WINDOW


def notification_requested_payload(notification: Notification) -> dict:
    """The `notification.requested` payload (ADR-004: non-recovery-grade, so
    ids + refs only — the durable work item is the row, not this event)."""
    return {
        "notification_id": notification.id,
        "priority": notification.priority,
    }
