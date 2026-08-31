"""backup.snapshot handler — the daily snapshot's operation (ADR-031).

Layer: api.
Constitutional home: 07_DATABASE Part XII, 05_AGENTS Appendix E
(`backup.snapshot`, daily), 12_API §16.

Thin by construction (12 §2): the policy — integrity gate, both
`VACUUM INTO`s, the audit copy, the manifest line, retention — is the
`BackupService` port's. This handler resolves the clock, calls it once,
and maps its typed failure to an API-006 code. No filesystem or SQL
reaches this layer.
"""

from __future__ import annotations

from typing import Any

from kang.api.dispatch import Handler, HandlerContext
from kang.api.errors import ApiError
from kang.domain.ports.backup import BackupError, BackupService
from kang.domain.ports.clock import Clock

__all__ = ["make_backup_snapshot_handler"]


def make_backup_snapshot_handler(backups: BackupService, clock: Clock) -> Handler:
    """`backup.snapshot` (ADR-031): take the daily snapshot.

    A `BackupError` becomes `internal`, not `conflict`: the only ways it
    is raised are a failed integrity check (the database is suspect —
    07 Part XV F1) or a snapshot target that already exists (the job ran
    twice in one day, which `run_once_latest` should prevent). Both are
    conditions the caller cannot fix by retrying differently, and both
    MUST be loud — 05_AGENTS Appendix A's backup row is explicit: "alert
    on any failure — no silent skip, ever."
    """

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        try:
            record = backups.take_snapshot(clock.now().isoformat())
        except BackupError as exc:
            raise ApiError("internal", f"snapshot refused: {exc}") from exc
        return {
            "database": record.database,
            "eventlog": record.eventlog,
            "audit": record.audit,
            "bytes_total": record.bytes_total,
            "integrity_ok": record.integrity_ok,
            "schema_version": record.schema_version,
            "promoted_monthly": record.promoted_monthly,
            "pruned": list(record.pruned),
        }

    return handler
