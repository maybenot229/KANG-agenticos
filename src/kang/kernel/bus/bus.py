"""EventBus — the publish path (EB-004) and startup recovery entry point.

Layer: kernel/bus. The one place the fixed write order is enforced.
Constitutional home: 15_EVENT_BUS EB-004 (the five-step write order:
validate → append pending → commit state → confirm → fan out — event-first,
so a lost state commit becomes a recoverable ghost event, never a silently
missed fact), EB-006 §6.3 (validate registration at publish), EB-011.2
(causation-depth guard before publishing), §4.4 (startup: reconcile, then
resume per-subscriber delivery from cursors).

Publish authority (`events.publish:{namespace}`, EB-010 checkpoint 1) is
enforced here (M3): the publisher principal must hold the scope or the
publish is denied, audited, and nothing is appended. The depth guard
refuses to extend a runaway chain; the "append + alert + suppress would-be
triggers" variant activates when event-triggered jobs exist (M3+ scheduler
wiring).
"""

from __future__ import annotations

from typing import Callable

from kang.domain.ports.eventlog import EventEnvelope, EventLog
from kang.kernel.audit.service import AuditService
from kang.kernel.bus.cycle_defense import MAX_CAUSATION_DEPTH, guard_causation_depth
from kang.kernel.bus.delivery import Delivery, Handler
from kang.kernel.bus.event_registry import namespace_of, validate_registration
from kang.kernel.bus.reconciliation import Reconciliation, ReconciliationReport
from kang.kernel.permissions.engine import PermissionDenied, PermissionEngine

__all__ = ["EventBus", "FanOutDepthExceeded", "Subscriber"]


class FanOutDepthExceeded(Exception):
    """Fan-out kept producing work past the pass cap — a handler is
    publishing in a loop. Distinct from CausationDepthExceeded: that guards
    a *declared* causation chain, this guards *reaction waves*, which a
    publisher can create without threading causation_id at all."""


class Subscriber:
    """A named core subscriber and its handler. Delivery order across core
    subscribers is registration order — deterministic module-load order,
    documented not configurable (§7.7)."""

    def __init__(self, name: str, handler: Handler) -> None:
        self.name = name
        self.handler = handler


class EventBus:
    """Publishes facts in the EB-004 order and drives startup recovery."""

    def __init__(
        self,
        event_log: EventLog,
        delivery: Delivery,
        reconciliation: Reconciliation,
        permissions: PermissionEngine,
        audit: AuditService,
        subscribers: list[Subscriber] | None = None,
    ) -> None:
        self._event_log = event_log
        self._delivery = delivery
        self._reconciliation = reconciliation
        self._permissions = permissions
        self._audit = audit
        self._subscribers = list(subscribers or [])
        self._fanning_out = False  # re-entrancy guard — see _fan_out

    def subscribe(self, subscriber: Subscriber) -> None:
        """Register a core subscriber. Delivery order across core
        subscribers is registration order — deterministic module-load order,
        documented not configurable (§7.7). Registering after construction
        is how the composition root wires subscribers whose dependencies
        need the bus itself (the notifier's publisher, for one)."""
        self._subscribers.append(subscriber)

    def publish(self, envelope: EventEnvelope, commit_state: Callable[[], None]) -> int:
        """The five-step write order (EB-004). `commit_state` is the caller's
        kang.db transaction — the truth the event is about. Returns seq."""
        # 1. validate: publish authority (EB-010 checkpoint 1) + registry
        #    (registered, schema, recovery_grade) + causation-depth guard.
        #    All gate step 1 — an unauthorized or invalid publish never
        #    reaches the log (default-deny; nothing persisted on denial).
        scope = f"events.publish:{namespace_of(envelope.type)}"
        try:
            self._permissions.check(envelope.principal, scope)
        except PermissionDenied:
            # Denials are audited, never silent (05 §8, SEC-006) — then the
            # typed error propagates; nothing was appended.
            self._audit.record(
                envelope.principal,
                "events.publish.denied",
                {"scope": scope, "type": envelope.type},
            )
            raise
        validate_registration(envelope)
        guard_causation_depth(self._event_log, envelope.causation_id)
        # 2. append to eventlog.db (pending; synchronous=FULL; seq assigned)
        seq = self._event_log.append(envelope)
        # 3. commit state transaction in kang.db
        commit_state()
        # 4. mark confirmed
        self._event_log.confirm(seq)
        # 5. fan out to subscribers (per-subscriber cursors)
        self._fan_out()
        return seq

    def recover(self) -> ReconciliationReport:
        """Startup: run the caged reconciliation pass over the pending
        window, then resume per-subscriber delivery from cursors (§4.4)."""
        report = self._reconciliation.run()
        self._fan_out()
        return report

    def pending_count(self) -> int:
        """Size of the unresolved pending window — a health/readiness read
        (zero after a clean recover; the reconciliation report has detail)."""
        return len(self._event_log.pending())

    def _fan_out(self) -> None:
        """Deliver to every subscriber, then keep going until the stream is
        quiet.

        RE-ENTRANCY. A handler MAY publish — 15 §5.1 defines `causation_id`
        as the parent of an event that "exists because a handler/job reacted
        to another event", so reacting-by-publishing is the designed case.
        But `Delivery.deliver` calls the handler *before* advancing the
        cursor (the advance IS the at-least-once ack, EB-007.2), so a naive
        nested fan-out re-reads the event still in flight and recurses
        without bound. The guard below makes a nested publish a no-op: the
        event is already durably appended and confirmed, and the outer loop
        picks it up on its next pass.

        The loop then drains until no subscriber advanced, so an event
        published by a handler is delivered within the same fan-out rather
        than waiting for the next publish.

        BOUNDED INDEPENDENTLY of EB-011.2. Each pass delivers one wave of
        reactions, so passes ≈ reaction depth. The causation-depth guard
        canNOT be relied on to bound this: `causation_depth` returns 0 when
        `causation_id` is None, so a handler that publishes without
        threading causation never raises it — the chain looks like an
        unbroken series of root causes. Nothing forces publishers to thread
        it, so the drain needs its own cap. It reuses MAX_CAUSATION_DEPTH
        rather than inventing a second number (11 §3: one concept, one
        name) and fails LOUDLY when reached, because a bus that silently
        stops draining is a bus that silently drops notifications
        (SEC-009 / DB-P7: fail visibly, never silently).
        """
        if self._fanning_out:
            return  # nested publish — the outer pass will deliver it
        self._fanning_out = True
        try:
            for _ in range(MAX_CAUSATION_DEPTH):
                advanced = 0
                for subscriber in self._subscribers:  # registration order (§7.7)
                    advanced += self._delivery.deliver(
                        subscriber.name, subscriber.handler
                    )
                if advanced == 0:
                    return
            self._audit.record(
                principal="kernel:bus",
                action="bus.fan_out_depth_exceeded",
                details={"max_passes": MAX_CAUSATION_DEPTH},
            )
            raise FanOutDepthExceeded(
                f"fan-out still producing work after {MAX_CAUSATION_DEPTH} "
                "passes — a handler is publishing in a loop (EB-011.2's cap, "
                "applied to reaction waves)"
            )
        finally:
            self._fanning_out = False
