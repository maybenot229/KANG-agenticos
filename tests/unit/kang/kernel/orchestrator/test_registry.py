"""AgentRegistry (AG-004, ADR-040): the pairing lint reused against an
agent's own declared scopes, composed with the adapter's structural
parse — proving the reuse is real, not cosmetic (the same
`kernel/permissions/pairing.py` that already guards `permissions.toml`).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kang.adapters.config.agent_definitions_loader import discover_agent_definitions
from kang.domain.ports.agent_definition import AgentDefinition, AgentDefinitionInvalid
from kang.kernel.orchestrator.registry import build_checked_registry

REPO_ROOT = Path(__file__).resolve().parents[5]
SHIPPED_DEFINITIONS_DIR = REPO_ROOT / "src" / "kang" / "agents" / "definitions"


def _definition(**overrides) -> AgentDefinition:
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


def test_a_clean_definition_builds_a_registry_indexed_by_id():
    registry = build_checked_registry([_definition(id="a"), _definition(id="b")])
    assert len(registry) == 2
    assert registry.get("a").id == "a"
    assert registry.get("unknown") is None
    assert {d.id for d in registry} == {"a", "b"}


def test_web_fetch_paired_with_sensitive_memory_read_is_refused():
    bad = _definition(scopes=("web.fetch:sources", "memory.read:sensitive"))
    with pytest.raises(AgentDefinitionInvalid, match="pairing lint"):
        build_checked_registry([bad])


def test_web_fetch_paired_with_vault_write_is_refused():
    bad = _definition(scopes=("web.fetch:sources", "vault.write:inbox"))
    with pytest.raises(AgentDefinitionInvalid, match="pairing lint"):
        build_checked_registry([bad])


def test_memory_propose_rule_is_ungrantable_to_any_agent():
    bad = _definition(scopes=("memory.propose:rule",))
    with pytest.raises(AgentDefinitionInvalid, match="pairing lint"):
        build_checked_registry([bad])


def test_memory_propose_profile_is_ungrantable_to_any_agent():
    bad = _definition(scopes=("memory.propose:profile",))
    with pytest.raises(AgentDefinitionInvalid, match="pairing lint"):
        build_checked_registry([bad])


def test_a_wildcard_scope_is_refused_for_any_agent_principal():
    # §8: wildcards are reserved for principal 'kang' — no agent, no
    # matter how trusted its mandate, gets one.
    bad = _definition(scopes=("*",))
    with pytest.raises(AgentDefinitionInvalid, match="pairing lint"):
        build_checked_registry([bad])


def test_a_single_violation_refuses_the_whole_registry_not_just_that_agent():
    good = _definition(id="good", scopes=("memory.read:normal",))
    bad = _definition(id="bad", scopes=("memory.propose:rule",))
    with pytest.raises(AgentDefinitionInvalid):
        build_checked_registry([good, bad])


def test_the_real_shipped_catalog_passes_the_pairing_lint():
    definitions = discover_agent_definitions(SHIPPED_DEFINITIONS_DIR)
    registry = build_checked_registry(definitions)
    assert len(registry) == 16  # Appendix A's own 15 (ADR-040 D4) + chat (ADR-044)
    assert registry.get("planner").kind == "cognitive"
    assert registry.get("researcher").scopes == (
        "memory.read:research-view",
        "memory.propose:fact",
        "memory.propose:observation",
    )  # never memory.read:sensitive — Appendix A's own forbidden entry, honored
