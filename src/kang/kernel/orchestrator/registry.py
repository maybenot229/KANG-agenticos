"""AgentRegistry — the checked, indexed agent definition set (AG-004, ADR-040).

Layer: kernel/orchestrator (AG-001 §3 phase 1, "Admission: registry
lookup..." — this module is that registry).
Constitutional home: 05_AGENTS AG-004, §8 (the pairing lint applies to
an agent's own declared scopes, not only to `permissions.toml` grants).

Composes the adapter's structural parse (`adapters/config/
agent_definitions_loader.py`) with `kernel/permissions/pairing.py`'s
existing lint, reused verbatim against each definition's own `scopes` —
the same split `kernel/permissions/engine.py::build_checked_engine`
already established for grant loading (parse in adapters, lint+build in
kernel, because adapters may not import kernel — 17 §4.3).
"""

from __future__ import annotations

from collections.abc import Iterator

from kang.domain.ports.agent_definition import AgentDefinition, AgentDefinitionInvalid
from kang.kernel.permissions.pairing import PairingViolation, lint_grants

__all__ = ["AgentRegistry", "build_checked_registry"]


class AgentRegistry:
    """The validated, indexed set of registered agents (AG-004: "what
    can KANG do?" answerable by reading this)."""

    def __init__(self, definitions: dict[str, AgentDefinition]) -> None:
        self._by_id = definitions

    def get(self, agent_id: str) -> AgentDefinition | None:
        return self._by_id.get(agent_id)

    def __iter__(self) -> Iterator[AgentDefinition]:
        return iter(self._by_id.values())

    def __len__(self) -> int:
        return len(self._by_id)


def build_checked_registry(definitions: list[AgentDefinition]) -> AgentRegistry:
    """Pairing-lint every definition's own `scopes` (as if it were a
    `permissions.toml` grant for principal `agent:{id}` — §8's own
    principal shape, reused rather than a bare id), then index by id.
    Raises `AgentDefinitionInvalid` (wrapping the pairing lint's own
    `PairingViolation`) on the first violation — fails closed, the
    whole registry refused, matching ADR-040 D3's own posture."""
    for definition in definitions:
        principal = f"agent:{definition.id}"
        try:
            lint_grants({principal: definition.scopes})
        except PairingViolation as exc:
            raise AgentDefinitionInvalid(
                f"agent {definition.id!r}'s own declared scopes violate "
                f"the pairing lint: {exc}"
            ) from exc
    return AgentRegistry({d.id: d for d in definitions})
