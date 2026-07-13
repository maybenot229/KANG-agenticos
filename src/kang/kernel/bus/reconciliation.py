"""Ghost-event reconciliation — THE caged module (15_EVENT_BUS §4).

Layer: kernel/bus.
Constitutional home: 15_EVENT_BUS EB-004 (the startup reconciliation pass:
re-apply recovery-grade pending events idempotently and confirm; for
non-recovery-grade pending events, confirm if the referenced state exists,
else orphan — never deliver, never delete; report the window).

THE CONTAINMENT RULE (§4 trade-offs), enforced by this module's shape:
reconciliation logic lives in THIS ONE module, is exercised by the
crash-replay CI class (13 §2.5), and MUST NOT grow features. It re-applies
and reports; it never decides. Adding a branch that *decides* anything
(merges, resolves conflicts, mutates beyond re-application) belongs
elsewhere and fails review here.
"""

from __future__ import annotations

from dataclasses import dataclass

from kang.domain.ports.clock import Clock
from kang.domain.ports.eventlog import EventLog, StoredEvent
from kang.domain.ports.recovery import RecoveryApplier
from kang.kernel.audit.service import AuditService

__all__ = ["Reconciliation", "ReconciliationReport"]


@dataclass(frozen=True)
class ReconciliationReport:
    """The window, reported to the startup health summary and audit (§4.5)
    so the crash is explained (SEC-009, 07 F2/F3)."""

    window: int
    reapplied: int
    confirmed: int
    orphaned: int


class Reconciliation:
    """Runs the §4 pass over the pending window on startup."""

    def __init__(
        self,
        event_log: EventLog,
        applier: RecoveryApplier,
        audit: AuditService,
        clock: Clock,
    ) -> None:
        self._event_log = event_log
        self._applier = applier
        self._audit = audit
        self._clock = clock

    def run(self) -> ReconciliationReport:
        """Read pending oldest-first; re-apply/confirm/orphan; report."""
        pending = self._event_log.pending()
        reapplied = confirmed = orphaned = 0
        for stored in pending:  # oldest first, by seq (§4.1)
            if stored.envelope.recovery_grade:
                self._applier.reapply(stored.envelope)  # idempotent (EB-003)
                self._event_log.confirm(stored.seq)
                reapplied += 1
            elif self._state_present(stored):
                self._event_log.confirm(stored.seq)
                confirmed += 1
            else:
                self._event_log.mark_orphaned(stored.seq)  # §4.3
                orphaned += 1
        report = ReconciliationReport(
            window=len(pending),
            reapplied=reapplied,
            confirmed=confirmed,
            orphaned=orphaned,
        )
        self._report(report)
        return report

    def _state_present(self, stored: StoredEvent) -> bool:
        """A non-recovery-grade event is consistent iff its referenced
        entities exist (§4.3). No refs ⇒ nothing to contradict ⇒ present."""
        return all(
            self._applier.entity_exists(ref["kind"], ref["id"])
            for ref in stored.envelope.entity_refs
        )

    def _report(self, report: ReconciliationReport) -> None:
        self._audit.record(
            principal="kernel:bus",
            action="reconciliation.completed",
            details={
                "window": report.window,
                "reapplied": report.reapplied,
                "confirmed": report.confirmed,
                "orphaned": report.orphaned,
            },
        )
