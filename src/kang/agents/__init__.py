"""Agent definitions (data) + the one shared runtime. Agents are data (AR5).

Layer: agents.
Constitutional home: 05_AGENTS AG-002; 17_PROJECT_STRUCTURE §2/§6.1.
`definitions/` carries three real agents as of ADR-040 (`deadline_sweep`,
`critic`, `planner`) — loaded and pairing-linted by `adapters/config/
agent_definitions_loader.py` + `kernel/orchestrator/registry.py`, not
yet run by anything (`runtime/` is still a stub; a separate M7 item).
"""

__all__: list[str] = []
