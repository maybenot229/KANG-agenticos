"""explain.invocation / explain.plan_item / .notification / .suggestion /
.memory handlers.

Layer: api.
Constitutional home: 12_API §12 (explainability).
"""

from __future__ import annotations

from typing import Any

from kang.api.dispatch import Handler, HandlerContext
from kang.api.errors import ApiError
from kang.domain.ports.invocation import InvocationNotFound, InvocationStore
from kang.kernel.audit.service import AuditService

__all__ = ["make_explain_invocation_handler", "make_explain_stub_handler"]


def make_explain_invocation_handler(
    invocations: InvocationStore, audit: AuditService
) -> Handler:
    """explain.invocation (12 §12): reconstruct from PERMANENT storage —
    the invocation row + the audit chain — by correlation_id. Never the
    event log (its 90-day retention would break the ≥180-day guarantee)."""

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        target = params.get("correlation_id")
        if not isinstance(target, str) or not target:
            raise ApiError(
                "invalid_request", "explain.invocation requires a 'correlation_id'"
            )
        try:
            invocation = invocations.by_correlation(target)
        except InvocationNotFound as exc:
            raise ApiError(
                "not_found", f"no invocation for correlation_id {target}"
            ) from exc
        chain = [
            {
                "action": record.entry.action,
                "principal": record.entry.principal,
                "at": record.entry.at,
                "details": record.entry.details,
            }
            for record in audit.records_for_correlation(target)
        ]
        return {
            "correlation_id": target,
            "trigger": invocation.trigger,
            "operation": invocation.operation,
            "principal": invocation.principal,
            "kind": invocation.kind,
            "manifest": invocation.manifest,  # None for non-agent operations
            "started": invocation.started,
            "finished": invocation.finished,
            "outcome": invocation.outcome,
            "chain": chain,
            "reconstructed_from": "invocation + audit (permanent storage)",
        }

    return handler


def make_explain_stub_handler(kind: str) -> Handler:
    """explain.plan_item/notification/suggestion/memory (12 §12): registered
    now; their subjects (plans, notifications, memory) arrive at M5/Phase 2.
    Until then they honestly return not_found — never a synthesized narrative
    (A4)."""

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        raise ApiError(
            "not_found",
            f"no {kind} to explain yet — its subject arrives in a later milestone",
        )

    return handler
