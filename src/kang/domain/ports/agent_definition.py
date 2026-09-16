"""Agent definition types — the registry's own datatypes (AG-004, ADR-040).

Layer: domain/ports. Ports own their datatypes (17 §7).
Constitutional home: 05_AGENTS AG-004 ("Agents exist only as registered
definitions: versioned declarative documents... listing mandate, kind,
triggers, recipe, tool allowlist, scopes, timeouts, retry, degradation,
and pipeline memberships"), §1.2 (cognitive vs. mechanical, and a
mechanical agent's optional cognitive-escalation capability), AG-005
(the tool allowlist), §8 (capability scopes).

This module is pure structure — no I/O, no validation logic beyond what
a `@dataclass(frozen=True)` gives for free. Parsing lives in
`adapters/config/agent_definitions_loader.py` (structural checks);
pairing-lint validation lives in `kernel/orchestrator/registry.py`
(reuses `kernel/permissions/pairing.py`, unavailable to adapters — 17
§4.3). See ADR-040 for why the split.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "AGENT_KINDS",
    "AgentDefinition",
    "AgentDefinitionInvalid",
    "CognitiveAgentNotSupported",
    "EscalationCapability",
    "ToolNotAllowed",
]

AGENT_KINDS = ("cognitive", "mechanical")  # §1.2's own two kinds, exactly


class AgentDefinitionInvalid(Exception):
    """A definition (or the registry as a whole) fails a structural or
    pairing rule. Registry loading fails closed on this (ADR-040 D3): a
    single bad definition refuses the ENTIRE load, never a partial
    registry silently smaller than the one on disk."""


class ToolNotAllowed(Exception):
    """An agent attempted to call an operation outside its own declared
    `tools` allowlist (AG-005, ADR-028 C4). Raised BEFORE any dispatch
    is attempted — independent of, and prior to, whatever scope check
    the dispatch pipeline itself performs (ADR-041 D1)."""


class CognitiveAgentNotSupported(Exception):
    """The mechanical-agent executor (ADR-041) refuses to run a
    `kind="cognitive"` definition — 03_ROADMAP's own Phase 1 scope:
    "Intentionally postponed: all cognitive agents beyond basic chat."
    Not a load-time validity problem (the definition itself is fine,
    ADR-040 already proved that) — a runtime scope boundary."""


@dataclass(frozen=True)
class EscalationCapability:
    """§1.2: "A mechanical agent MAY escalate to a cognitive step... the
    escalation is a declared capability in its definition, never an
    improvisation." Only valid on a `kind="mechanical"` definition —
    Appendix A's own `M→C` agents (`competition_scout`, `web_monitor`,
    `memory_steward`)."""

    task_class: str  # one of ModelProvider's TASK_CLASSES (ADR-038 D2) — reused
    prompt_file: str  # relative to the definition's own folder; must exist


@dataclass(frozen=True)
class AgentDefinition:
    """One registered agent (AG-004). Structurally validated by the
    loader; pairing-linted by the kernel. See this module's own
    docstring for why the split."""

    id: str
    kind: str  # one of AGENT_KINDS
    mandate: str  # AGP-1: one sentence, the single responsibility
    triggers: tuple[str, ...]
    tools: tuple[str, ...]  # AG-005's allowlist — structural only (ADR-040 D2)
    scopes: tuple[str, ...]  # §8's capability scopes — parsed + pairing-linted
    timeout_s: int
    retry: int
    degradation: str  # AGP-8: never empty — "nothing, silently" is never valid
    recipe: str | None  # Phase-2 concept (06_MEMORY Part XI) — captured, not resolved
    pipelines: tuple[str, ...]
    prompt_file: str | None  # required iff cognitive; forbidden iff mechanical
    escalation: EscalationCapability | None  # only valid iff kind == "mechanical"
