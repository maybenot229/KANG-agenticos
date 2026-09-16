"""PipelineRegistry (AG-002, ADR-042): the one genuine cross-registry
check — every step's `agent_id` must resolve in a real, already-built
`AgentRegistry` — composed with the adapter's structural parse.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kang.adapters.config.agent_definitions_loader import discover_agent_definitions
from kang.adapters.config.pipelines_loader import discover_pipeline_definitions
from kang.domain.ports.agent_definition import AgentDefinition
from kang.domain.ports.pipeline_definition import (
    PipelineDefinition,
    PipelineDefinitionInvalid,
    PipelineStep,
)
from kang.kernel.orchestrator.pipeline_registry import (
    build_checked_pipeline_registry,
    check_pipeline_membership_reciprocity,
)
from kang.kernel.orchestrator.registry import build_checked_registry

REPO_ROOT = Path(__file__).resolve().parents[5]
SHIPPED_DEFINITIONS_DIR = REPO_ROOT / "src" / "kang" / "agents" / "definitions"
SHIPPED_PIPELINES_DIR = REPO_ROOT / "src" / "kang" / "agents" / "pipelines"


def _agent(**overrides) -> AgentDefinition:
    base = dict(
        id="scout",
        kind="mechanical",
        mandate="Scout things.",
        triggers=("sched:daily",),
        tools=("web.fetch:sources",),
        scopes=(),
        timeout_s=60,
        retry=1,
        degradation="skip cycle",
        recipe=None,
        pipelines=(),
        prompt_file=None,
        escalation=None,
    )
    base.update(overrides)
    return AgentDefinition(**base)


def test_a_pipeline_over_known_agents_builds_a_registry_indexed_by_id():
    registry = build_checked_registry([_agent(id="scout"), _agent(id="notifier")])
    pipeline = PipelineDefinition(
        id="p1",
        steps=(PipelineStep(agent_id="scout", mode=None),
               PipelineStep(agent_id="notifier", mode="digest")),
    )
    pipelines = build_checked_pipeline_registry([pipeline], registry)
    assert len(pipelines) == 1
    assert pipelines.get("p1").id == "p1"
    assert pipelines.get("unknown") is None
    assert {p.id for p in pipelines} == {"p1"}


def test_a_step_naming_an_unregistered_agent_id_refuses_the_whole_load():
    registry = build_checked_registry([_agent(id="scout")])
    bad = PipelineDefinition(
        id="p1", steps=(PipelineStep(agent_id="nonexistent_agent", mode=None),),
    )
    with pytest.raises(PipelineDefinitionInvalid, match="nonexistent_agent"):
        build_checked_pipeline_registry([bad], registry)


def test_one_bad_pipeline_refuses_the_whole_registry_not_just_that_pipeline():
    registry = build_checked_registry([_agent(id="scout")])
    good = PipelineDefinition(
        id="good", steps=(PipelineStep(agent_id="scout", mode=None),),
    )
    bad = PipelineDefinition(
        id="bad", steps=(PipelineStep(agent_id="ghost", mode=None),),
    )
    with pytest.raises(PipelineDefinitionInvalid):
        build_checked_pipeline_registry([good, bad], registry)


def test_the_real_shipped_pipelines_cross_validate_against_the_real_agent_registry():
    agent_definitions = discover_agent_definitions(SHIPPED_DEFINITIONS_DIR)
    agent_registry = build_checked_registry(agent_definitions)
    assert len(agent_registry) == 15  # Appendix A's own 15 (ADR-040 D4)

    pipeline_definitions = discover_pipeline_definitions(SHIPPED_PIPELINES_DIR)
    pipelines = build_checked_pipeline_registry(pipeline_definitions, agent_registry)
    assert len(pipelines) == 4  # Appendix A's own 4 (ADR-042 D4)
    assert {p.id for p in pipelines} == {
        "competition_intake", "competition_prep", "deep_research", "weekly_close",
    }


def test_matching_claims_reciprocate_cleanly():
    agent = _agent(id="scout", pipelines=("p1",))
    registry = build_checked_registry([agent])
    pipeline = PipelineDefinition(
        id="p1", steps=(PipelineStep(agent_id="scout", mode=None),),
    )
    pipelines = build_checked_pipeline_registry([pipeline], registry)
    check_pipeline_membership_reciprocity(registry, pipelines)  # no raise


def test_a_false_membership_claim_raises():
    # scout claims p1 but is not actually a step of it.
    agent = _agent(id="scout", pipelines=("p1",))
    registry = build_checked_registry([agent])
    pipeline = PipelineDefinition(
        id="p1", steps=(PipelineStep(agent_id="notifier", mode=None),),
    )
    other_agent = _agent(id="notifier")
    registry = build_checked_registry([agent, other_agent])
    pipelines = build_checked_pipeline_registry([pipeline], registry)
    with pytest.raises(PipelineDefinitionInvalid, match="scout"):
        check_pipeline_membership_reciprocity(registry, pipelines)


def test_a_missing_membership_claim_raises():
    # scout is actually a step of p1 but never declared it.
    agent = _agent(id="scout", pipelines=())
    registry = build_checked_registry([agent])
    pipeline = PipelineDefinition(
        id="p1", steps=(PipelineStep(agent_id="scout", mode=None),),
    )
    pipelines = build_checked_pipeline_registry([pipeline], registry)
    with pytest.raises(PipelineDefinitionInvalid, match="scout"):
        check_pipeline_membership_reciprocity(registry, pipelines)


def test_the_real_shipped_catalog_and_pipelines_reciprocate_cleanly():
    agent_definitions = discover_agent_definitions(SHIPPED_DEFINITIONS_DIR)
    agent_registry = build_checked_registry(agent_definitions)
    pipeline_definitions = discover_pipeline_definitions(SHIPPED_PIPELINES_DIR)
    pipelines = build_checked_pipeline_registry(pipeline_definitions, agent_registry)
    check_pipeline_membership_reciprocity(agent_registry, pipelines)  # no raise
