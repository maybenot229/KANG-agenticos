"""The ONE executor: lifecycle phases 1-9.

Layer: agents.
Constitutional home: 05_AGENTS §3, docs/adr/041-mechanical-agent-
executor.md. `executor.py` carries the mechanical-agent shape
(`run_mechanical_agent`) — cognitive-agent execution stays out
(03_ROADMAP Phase 1: "all cognitive agents beyond basic chat" is
postponed past M7). Wired into the real Core as of ADR-043
(2026-09-16, docs/adr/043-deadline-sweep-agent-envelope-routing.md):
`kernel/runtime/scheduler_wiring.py` calls this for every job named in
`AGENT_ROUTED_JOBS` (`deadline_sweep`, today).
"""

__all__: list[str] = []
