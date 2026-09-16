"""PipelineRegistry — the checked, indexed pipeline definition set
(AG-002, ADR-042).

Layer: kernel/orchestrator.
Constitutional home: 05_AGENTS AG-002 ("Multi-agent behavior exists only
as pipelines... defined in the registry and executed by the
Orchestrator").

Composes the adapter's structural parse (`adapters/config/
pipelines_loader.py`) with the one genuine cross-registry check ADR-042
D3 adds: every step's `agent_id` must resolve in the already-built
`AgentRegistry` (ADR-040) — the same parse-in-adapters/cross-check-in-
kernel split `registry.py::build_checked_registry` already established
for agent definitions, because adapters may not import kernel (17 §4.3).

Also carries `check_pipeline_membership_reciprocity` — ADR-042 D3's own
named follow-up ("a real, useful check... but the first real pipeline
data this ADR ships is what would prove whether that check is even
worth its own complexity"), built once that real data existed (same
day) to prove it against — and immediately caught a real gap in
ADR-040's own shipped data (`notifier`/`memory_steward`'s wrong
`pipelines` claims, corrected there).
"""

from __future__ import annotations

from collections.abc import Iterator

from kang.domain.ports.pipeline_definition import (
    PipelineDefinition,
    PipelineDefinitionInvalid,
)
from kang.kernel.orchestrator.registry import AgentRegistry

__all__ = [
    "PipelineRegistry",
    "build_checked_pipeline_registry",
    "check_pipeline_membership_reciprocity",
]


class PipelineRegistry:
    """The validated, indexed set of registered pipelines (AG-002)."""

    def __init__(self, definitions: dict[str, PipelineDefinition]) -> None:
        self._by_id = definitions

    def get(self, pipeline_id: str) -> PipelineDefinition | None:
        return self._by_id.get(pipeline_id)

    def __iter__(self) -> Iterator[PipelineDefinition]:
        return iter(self._by_id.values())

    def __len__(self) -> int:
        return len(self._by_id)


def build_checked_pipeline_registry(
    definitions: list[PipelineDefinition], agent_registry: AgentRegistry
) -> PipelineRegistry:
    """Cross-validate every pipeline step's `agent_id` against the real,
    already-built `AgentRegistry` (ADR-042 D3's one genuine cross-
    check), then index by id. Raises `PipelineDefinitionInvalid` on the
    first unresolvable agent id — fails closed, the whole registry
    refused, matching ADR-040 D3's own posture. Takes an already-built
    `AgentRegistry`, not a bare directory path, so this check is always
    against the real, validated agent set actually loaded — never a
    second, possibly-stale re-scan of the definitions directory."""
    for definition in definitions:
        for step in definition.steps:
            if agent_registry.get(step.agent_id) is None:
                raise PipelineDefinitionInvalid(
                    f"pipeline {definition.id!r} step names agent_id "
                    f"{step.agent_id!r}, which is not in the AgentRegistry"
                )
    return PipelineRegistry({d.id: d for d in definitions})


def check_pipeline_membership_reciprocity(
    agent_registry: AgentRegistry, pipeline_registry: PipelineRegistry
) -> None:
    """Every agent's own declared `pipelines` (ADR-040 D2) must exactly
    match the set of pipelines that actually list it as a step — no
    false claim, no missing one. Raises `PipelineDefinitionInvalid` on
    the first mismatch — fails closed, same posture as every other
    registry check in this codebase. A separate check from
    `build_checked_pipeline_registry`'s own (ADR-042 D3 named this one
    a candidate follow-up, not part of that check's original scope) —
    call it once both registries are built."""
    for agent in agent_registry:
        actual_membership = frozenset(
            pipeline.id
            for pipeline in pipeline_registry
            if any(step.agent_id == agent.id for step in pipeline.steps)
        )
        claimed_membership = frozenset(agent.pipelines)
        if claimed_membership != actual_membership:
            raise PipelineDefinitionInvalid(
                f"agent {agent.id!r} declares pipelines "
                f"{sorted(claimed_membership)!r}, but is actually a step "
                f"in {sorted(actual_membership)!r}"
            )
