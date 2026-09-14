"""Agent admission, pipelines, budgets.

Layer: kernel.
Constitutional home: 05_AGENTS AG-001, docs/adr/040-agent-registry.md.
`registry.py` carries AG-001 phase 1's own "registry lookup" — the
checked, indexed `AgentRegistry` (ADR-040). Admission proper (idempotency
check, concurrency check, budget precheck) is still unbuilt — a separate
M7 item, the executor's own future slice.
"""

__all__: list[str] = []
