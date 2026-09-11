"""backup.snapshot / backup.verify handlers (ADR-031, ADR-032).

Layer: api.
Constitutional home: 07_DATABASE Part XII, 05_AGENTS Appendix E
(`backup.snapshot`/`.verify`, daily/monthly), 12_API §16.

Thin by construction (12 §2): the policy — integrity gate, both
`VACUUM INTO`s, the audit copy, the manifest line, retention, the
restore-test — is the `BackupService` port's. Each handler resolves the
clock, calls the port once, and maps its typed failure to an API-006
code. No filesystem or SQL reaches this layer.
"""

from __future__ import annotations

from typing import Any

from kang.api.dispatch import Handler, HandlerContext
from kang.api.errors import ApiError
from kang.domain.ports.backup import BackupError, BackupService
from kang.domain.ports.clock import Clock

__all__ = ["make_backup_snapshot_handler", "make_backup_verify_handler"]


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


def make_backup_verify_handler(backups: BackupService, clock: Clock) -> Handler:
    """`backup.verify` (ADR-032): restore-test the latest daily snapshot.

    A `BackupError` here means "nothing to verify" (no daily snapshot
    exists at all) — a distinct condition from a failed check. A failed
    check (bad integrity, a broken read shape) is NOT an error: it is
    the normal, successful response of this operation, carrying
    `integrity_ok=False`/populated `read_shape_errors`. Collapsing that
    into an `ApiError` would hide the one result this job exists to
    surface — 05_AGENTS Appendix A: "alert on any failure — no silent
    skip, ever" means the finding must reach the caller, not be turned
    into a thrown exception nobody without try/except sees.
    """

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        try:
            record = backups.verify_latest(clock.now().isoformat())
        except BackupError as exc:
            raise ApiError("internal", f"verify refused: {exc}") from exc
        return {
            "snapshot": record.snapshot,
            "integrity_ok": record.integrity_ok,
            "read_shapes_checked": list(record.read_shapes_checked),
            "read_shapes_not_built": list(record.read_shapes_not_built),
            "read_shape_errors": list(record.read_shape_errors),
            "live_row_counts": record.live_row_counts,
            "snapshot_row_counts": record.snapshot_row_counts,
            "schema_version": record.schema_version,
        }

    return handler
