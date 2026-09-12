"""backup.snapshot / backup.verify / backup.offsite_check handlers
(ADR-031, ADR-032, ADR-034).

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

from typing import Any, Callable

from kang.api.dispatch import Handler, HandlerContext
from kang.api.errors import ApiError
from kang.domain.ports.backup import BackupError, BackupService
from kang.domain.ports.clock import Clock
from kang.domain.ports.eventlog import EventEnvelope
from kang.kernel.bus.bus import EventBus

__all__ = [
    "BACKUPS_PRINCIPAL",
    "make_backup_offsite_check_handler",
    "make_backup_snapshot_handler",
    "make_backup_verify_handler",
]

# The backup domain's own event-publishing principal (ADR-034), matching
# kernel:tasks/kernel:deadlines/etc.'s one-line pattern (EB-010): the
# operation that publishes a domain fact does so under that domain's
# principal, not the requester's (kernel:scheduler, for every job-
# triggered operation in this file).
BACKUPS_PRINCIPAL = "kernel:backups"


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


def make_backup_offsite_check_handler(
    backups: BackupService,
    bus: EventBus,
    clock: Clock,
    new_id: Callable[[], str],
    device_id: str,
) -> Handler:
    """`backup.offsite_check` (ADR-034, 07 Part XII.5): read the
    Kang-configured marker's mtime; announce `backup.offsite_stale` only
    when it is stale.

    Never raises `BackupError` — `external_backup_status` never raises at
    all (an unconfigured marker is a normal, honest result, not a
    refusal the way a failed integrity check is for `backup.snapshot`).
    Publishes nothing when the marker is fresh: no event, no
    notification, matching Part XII.5's own "warns... if no evidence"
    framing — silence is the healthy state. `causation_id=None`: unlike
    `deadline.approaching`, this fact has no accompanying mutation event
    to be caused by; it is a genuine root cause.
    """

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        now = clock.now()
        status = backups.external_backup_status(now.isoformat())
        if status.stale:
            bus.publish(
                EventEnvelope(
                    event_id=new_id(),
                    type="backup.offsite_stale",
                    occurred_at=now.isoformat(),
                    principal=BACKUPS_PRINCIPAL,
                    correlation_id=context.correlation_id,
                    causation_id=None,
                    device_id=device_id,
                    payload={
                        "last_marker_at": status.last_marker_at,
                        "checked_at": now.isoformat(),
                    },
                    recovery_grade=False,
                    entity_refs=({"kind": "backup", "id": "offsite"},),
                ),
                # No state of its own: a pure fact's whole existence IS
                # the event (EB-008 rule 2) — nothing was mutated to
                # commit.
                commit_state=lambda: None,
            )
        return {
            "last_marker_at": status.last_marker_at,
            "stale": status.stale,
        }

    return handler
