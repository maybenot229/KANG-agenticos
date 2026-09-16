"""Agent definitions (data) + the one shared runtime. Agents are data (AR5).

Layer: agents.
Constitutional home: 05_AGENTS AG-002; 17_PROJECT_STRUCTURE §2/§6.1.
`definitions/` carries the full 15-agent catalog (ADR-040 D4);
`pipelines/` carries the four real pipelines (ADR-042) — both loaded
and cross-validated by `adapters/config/` + `kernel/orchestrator/`.
`runtime/` (`run_mechanical_agent`, ADR-041) is wired into the real,
running Core as of ADR-043 (2026-09-16) — `deadline_sweep`'s real
scheduled trigger runs through it; every other agent's own definition
is still loaded-but-inert, no executor call yet.
"""

__all__: list[str] = []
