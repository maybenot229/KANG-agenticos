"""permission.list / audit.list / system.health / invocation.list handlers
— the System-domain operations (09_UI §12/§7).

Layer: api.
Constitutional home: 09_UI §7 (permission screen), §12 (Audit & History
Views).
"""

from __future__ import annotations

from typing import Any

from kang.api.dispatch import Handler, HandlerContext
from kang.api.schemas.invocation import DEFAULT_LIMIT, MAX_LIMIT
from kang.domain.ports.clock import Clock
from kang.domain.ports.invocation import InvocationStore
from kang.domain.ports.scheduler import JobStore, KillSwitch
from kang.kernel.audit.service import AuditService
from kang.kernel.permissions.engine import PermissionEngine

__all__ = [
    "make_audit_list_handler",
    "make_invocation_list_handler",
    "make_permission_list_handler",
    "make_system_health_handler",
]

# 08_PLUGIN Appendix B style: one honest sentence per scope family,
# describing what holding it lets a principal do — not the plugin-install
# screen's per-plugin instance (this is the System-domain permission
# screen, 09_UI §7), but the same "plain-language consequence" contract.
# Keyed by family only (Scope.family, ignoring the qualifier) since every
# grant in `config/defaults/permissions.toml` today is either the bare `*`
# wildcard or a single-qualifier family — a scope whose family isn't
# listed here falls back to an honest "no description written yet" rather
# than a fabricated one (09_UI §4's "never pad" rule, applied to this
# screen too).
_SCOPE_CONSEQUENCES: dict[str, str] = {
    "*": (
        "Full authority over everything KANG can do — reserved for "
        "Kang's own first-party session."
    ),
    "events.publish": (
        "Can publish facts to the event bus under the named namespace — "
        "the kernel's own truth-recording mechanism, not visible data "
        "access."
    ),
    "tasks.write": (
        "Can create or modify tasks and stamp plan dates, within "
        "whatever operations it triggers allow."
    ),
    "task.write": "Can create tasks.",
    "task.read": "Can read tasks by id.",
    "deadlines.set": "Can create tracked deadlines.",
    "deadlines.read": "Can read the list of currently tracked deadlines.",
    "deadlines.mark_alerted": (
        "Can flip a deadline from tracked to alerted — the lead-time sweep's one write."
    ),
    "projects.write": "Can create projects.",
    "projects.read": "Can read the list of tracked projects.",
    "competitions.write": "Can create competitions.",
    "competitions.read": "Can read the list of tracked competitions.",
    "milestones.write": "Can create milestones on a project.",
    "milestones.read": "Can read a project's list of tracked milestones.",
}


def _scope_consequence(scope: str) -> str:
    if scope == "*":
        return _SCOPE_CONSEQUENCES["*"]
    family = scope.split(":", 1)[0]
    return _SCOPE_CONSEQUENCES.get(
        family, f"No plain-language description written yet for {family!r}."
    )


def make_permission_list_handler(engine: PermissionEngine) -> Handler:
    """`permission.list` (09_UI §7: "every grant per principal, in the same
    scope language as permissions.toml, with plain-language consequence
    lines"). Read-only reflection of `PermissionEngine.snapshot()` — the
    same loaded grant snapshot every permission check in this Core runs
    against, not a fresh re-read of the file (which could diverge from
    what's actually enforced if the file changed since boot)."""

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "grants": [
                {
                    "principal": principal,
                    "scopes": [
                        {"scope": scope, "consequence": _scope_consequence(scope)}
                        for scope in scopes
                    ],
                }
                for principal, scopes in engine.snapshot().items()
            ]
        }

    return handler


def make_audit_list_handler(audit: AuditService, clock: Clock) -> Handler:
    """`audit.list` (added 2026-08-05, System-domain Activity view, 09_UI
    §12): every audit record of one month, oldest first —
    `AuditService.records()`'s existing pass-through over the `AuditLog`
    port, exposed through the API for the first time. `month` defaults to
    the injected clock's current month, mirroring `plan.generate`'s own
    default-to-today convention."""

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        month = params.get("month") or clock.now().strftime("%Y-%m")
        return {
            "month": month,
            "records": [
                {
                    "at": record.entry.at,
                    "principal": record.entry.principal,
                    "action": record.entry.action,
                    "correlation_id": record.entry.correlation_id,
                    "details": record.entry.details,
                }
                for record in audit.records(month)
            ],
        }

    return handler


def make_system_health_handler(job_store: JobStore, kill_switch: KillSwitch) -> Handler:
    """`system.health` (added 2026-08-05, System-domain Health view, 09_UI
    §12): job statuses + the automation kill-switch state.
    `JobStore.list_jobs()`/`.consecutive_failures()` and `KillSwitch.
    is_engaged()` already existed — pure API-layer exposure, no new
    domain logic. Backup age, restore-verification, index parity, and the
    integrity-incident counter are NOT covered (see this operation's
    schema docstring for why) — a real, named gap, not silently folded
    into "Health built."""

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "jobs": [
                {
                    "id": job.id,
                    "name": job.name,
                    "schedule": job.schedule,
                    "catch_up": job.catch_up,
                    "enabled": job.enabled,
                    "quarantined": job.quarantined,
                    "consecutive_failures": job_store.consecutive_failures(job.id),
                }
                for job in job_store.list_jobs()
            ],
            "automation_engaged": kill_switch.is_engaged(),
        }

    return handler


def make_invocation_list_handler(invocations: InvocationStore) -> Handler:
    """`invocation.list` (added 2026-08-05, System-domain Invocations view,
    09_UI §12): the `limit` most recent invocations, newest-`started`-first
    — `InvocationStore.recent()`, new port surface (unlike `deadline.list`/
    `held_action.list`/`audit.list`, `InvocationStore` had no list method
    at all before this). `limit` defaults to `DEFAULT_LIMIT` and clamps to
    `MAX_LIMIT` (12_API §15's standing "default page 50, max 500") rather
    than raising `invalid_request` on an over-large value — a clamp is the
    same shape `plan.generate`'s date-default and `audit.list`'s month-
    default already use for "no value supplied," and an over-large `limit`
    is a client asking for more than the standing cap allows, not a
    malformed request."""

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        requested = params.get("limit")
        # max(1, ...): SQLite's LIMIT -1 (or 0) means "unlimited" — clamping
        # only the top end would let a non-positive `limit` defeat the
        # entire point of a bounded page.
        limit = (
            DEFAULT_LIMIT if requested is None else max(1, min(requested, MAX_LIMIT))
        )
        return {
            "invocations": [
                {
                    "id": inv.id,
                    "correlation_id": inv.correlation_id,
                    "kind": inv.kind,
                    "operation": inv.operation,
                    "principal": inv.principal,
                    "trigger": inv.trigger,
                    "started": inv.started,
                    "finished": inv.finished,
                    "outcome": inv.outcome,
                }
                for inv in invocations.recent(limit)
            ]
        }

    return handler
