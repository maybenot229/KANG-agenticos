"""job.disable / job.enable handlers — the first real consequential
operation (ADR-021).

Layer: api.
Constitutional home: 12_API.md:182 ("`job.enable/disable` (consequential
for core jobs)" — already named there, not a new decision), 05_AGENTS
Appendix D (the closed consequential list).

Neither handler ever performs the effect itself, on any call — each
always creates a held action and raises `confirmation_required` via the
shared `require_confirmation` gate (`consequential.py`). The effect only
ever happens once approved, driven by `TRANSACTIONAL_EFFECTS`
(composition.py) from `held_action.approve`'s own handler — a
deliberately separate code path (ADR-021's own ruling: re-dispatching
through this handler again would open a second transaction).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from kang.api.dispatch import Handler, HandlerContext
from kang.api.errors import ApiError
from kang.api.operations.consequential import (
    ConfirmationDeps,
    ConfirmationRequest,
    require_confirmation,
)
from kang.domain.ports.scheduler import JobStore

__all__ = ["make_job_disable_handler", "make_job_enable_handler"]


@dataclass(frozen=True)
class _GateSpec:
    """The one thing that differs between `job.disable` and `job.enable`
    (11 §4: beyond a few parameters, a dataclass)."""

    operation: str
    verb: str
    reversibility: str


def _validated_job_id(job_store: JobStore, params: dict[str, Any]) -> str:
    job_id = params.get("job_id")
    if not isinstance(job_id, str) or not job_id:
        raise ApiError("invalid_request", "requires a 'job_id'")
    reason = params.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ApiError("invalid_request", "requires a non-empty 'reason'")
    if not any(job.id == job_id for job in job_store.list_jobs()):
        raise ApiError("not_found", f"no job {job_id!r}")
    return job_id


def _make_gate_handler(
    job_store: JobStore, confirmation: ConfirmationDeps, spec: _GateSpec
) -> Handler:
    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        job_id = _validated_job_id(job_store, params)
        require_confirmation(
            confirmation,
            context,
            ConfirmationRequest(
                operation=spec.operation,
                action=f"{spec.verb.capitalize()} job {job_id!r}",
                reason=params["reason"],
                reversibility=spec.reversibility,
                params={"job_id": job_id},
            ),
        )

    return handler


def make_job_disable_handler(
    job_store: JobStore, confirmation: ConfirmationDeps
) -> Handler:
    """`job.disable` — always gates, never disables directly (see module
    docstring)."""
    return _make_gate_handler(
        job_store,
        confirmation,
        _GateSpec(
            operation="job.disable",
            verb="disable",
            reversibility="reversible — re-enable via job.enable",
        ),
    )


def make_job_enable_handler(
    job_store: JobStore, confirmation: ConfirmationDeps
) -> Handler:
    """`job.enable` — always gates, never enables directly (see module
    docstring)."""
    return _make_gate_handler(
        job_store,
        confirmation,
        _GateSpec(
            operation="job.enable",
            verb="enable",
            reversibility="reversible — disable via job.disable",
        ),
    )
