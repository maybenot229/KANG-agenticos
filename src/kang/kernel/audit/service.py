"""AuditService — the ONLY writer of audit truth.

Layer: kernel/audit (authority; the log port is injected, I/O lives in
adapters).
Constitutional home: 10_SECURITY SEC-013 (append-only, hash-chained),
SEC-006 (anonymous action is architecturally impossible: this writer
refuses entries without a principal), 01_PRINCIPLES S5. Log ≠ audit
(11 §6): diagnostics go to structured logging; THIS is the record.
"""

from __future__ import annotations

from typing import Any

from kang.domain.ports.audit import AuditEntry, AuditLog, AuditRecord
from kang.domain.ports.clock import Clock
from kang.kernel.runtime.correlation import get_correlation_id

__all__ = ["AuditService", "AuditWriteError"]


class AuditWriteError(Exception):
    """The entry violates the attribution contract (SEC-006)."""


class AuditService:
    """Every audited action flows through here; nothing else holds the
    AuditLog port. Components state their own actions (15 §8: the acting
    component writes its audit entry — never derived from events)."""

    def __init__(self, log: AuditLog, clock: Clock) -> None:
        self._log = log
        self._clock = clock

    def record(
        self,
        principal: str,
        action: str,
        details: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> AuditRecord:
        """Append one attributable fact. The correlation id defaults to the
        ambient invocation context (12 §5 — one id, end to end)."""
        if not principal.strip():
            raise AuditWriteError(
                "audit entry without a principal — anonymous action is "
                "architecturally impossible (SEC-006)"
            )
        if not action.strip():
            raise AuditWriteError("audit entry without an action (SEC-006)")
        entry = AuditEntry(
            at=self._clock.now().isoformat(),
            principal=principal,
            action=action,
            correlation_id=correlation_id or get_correlation_id(),
            details=details,
        )
        return self._log.append(entry)
