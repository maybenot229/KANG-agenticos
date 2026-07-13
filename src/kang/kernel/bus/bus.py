"""EventBus — the publish path (EB-004) and startup recovery entry point.

Layer: kernel/bus. The one place the fixed write order is enforced.
Constitutional home: 15_EVENT_BUS EB-004 (the five-step write order:
validate → append pending → commit state → confirm → fan out — event-first,
so a lost state commit becomes a recoverable ghost event, never a silently
missed fact), EB-006 §6.3 (validate registration at publish), EB-011.2
(causation-depth guard before publishing), §4.4 (startup: reconcile, then
resume per-subscriber delivery from cursors).

Publish authority (`events.publish:{namespace}`, §10) is a permission-engine
check that arrives with the engine at M3; noted, not silently skipped. The
depth guard here refuses to extend a runaway chain; the "append + alert +
suppress would-be triggers" variant activates when event-triggered jobs
exist (M3).
"""

from __future__ import annotations

from typing import Callable

from kang.domain.ports.eventlog import EventEnvelope, EventLog
from kang.kernel.bus.cycle_defense import guard_causation_depth
from kang.kernel.bus.delivery import Delivery, Handler
from kang.kernel.bus.event_registry import validate_registration
from kang.kernel.bus.reconciliation import Reconciliation, ReconciliationReport

__all__ = ["EventBus", "Subscriber"]


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
        subscribers: list[Subscriber] | None = None,
    ) -> None:
        self._event_log = event_log
        self._delivery = delivery
        self._reconciliation = reconciliation
        self._subscribers = list(subscribers or [])

    def publish(self, envelope: EventEnvelope, commit_state: Callable[[], None]) -> int:
        """The five-step write order (EB-004). `commit_state` is the caller's
        kang.db transaction — the truth the event is about. Returns seq."""
        # 1. validate (registry: registered, schema, recovery_grade contract)
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
        for subscriber in self._subscribers:  # registration order (§7.7)
            self._delivery.deliver(subscriber.name, subscriber.handler)
