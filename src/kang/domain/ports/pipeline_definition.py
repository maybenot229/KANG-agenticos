"""Pipeline definition types — the pipeline registry's own datatypes
(AG-002, ADR-042).

Layer: domain/ports. Ports own their datatypes (17 §7).
Constitutional home: 05_AGENTS AG-002 ("Multi-agent behavior exists only
as pipelines: named, versioned, bounded DAGs of agent steps, defined in
the registry and executed by the Orchestrator"). ADR-042 narrows
"bounded DAG" to an ordered, linear step sequence — every real pipeline
in Appendix A is a simple chain; no real pipeline needs branching, and
this project has repeatedly declined pre-building against a hypothetical
(ADR-036 D1, ADR-038 D4, ADR-039 D4).

This module is pure structure — no I/O, no validation logic beyond what
a `@dataclass(frozen=True)` gives for free. Structural parsing lives in
`adapters/config/pipelines_loader.py` (id/filename/steps shape); the one
genuine cross-registry check (every step's `agent_id` must resolve in
the `AgentRegistry`) lives in `kernel/orchestrator/pipeline_registry.py`
(adapters may not import kernel — 17 §4.3). See ADR-042 for why the
split mirrors ADR-040's own agent-definition split.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["PipelineDefinition", "PipelineDefinitionInvalid", "PipelineStep"]


class PipelineDefinitionInvalid(Exception):
    """A pipeline (or the registry as a whole) fails a structural or
    cross-registry rule. Registry loading fails closed on this (ADR-042
    D3): a single bad pipeline refuses the ENTIRE load, the same posture
    ADR-040 D3 already established for agent definitions."""


@dataclass(frozen=True)
class PipelineStep:
    """One step of a pipeline (ADR-042 D2). `mode` names which facet of
    the agent's own single mandate this step exercises (e.g.
    `strategist(evaluate)` vs. `strategist(revise)`) — structural only,
    never validated against what the named agent actually implements
    (ADR-042 D3's own restraint, mirroring ADR-040 D2's treatment of
    `tools`)."""

    agent_id: str  # MUST exist in the AgentRegistry (cross-validated, D3)
    mode: str | None


@dataclass(frozen=True)
class PipelineDefinition:
    """One registered pipeline (AG-002). Deliberately an ordered, linear
    sequence, not a branching DAG (ADR-042 D2) — every real pipeline in
    Appendix A is a simple chain."""

    id: str
    steps: tuple[PipelineStep, ...]  # non-empty, ORDERED — linear, not a DAG
