"""The mechanical-agent executor (05_AGENTS §3, ADR-041) — a tool call
is an operation dispatch.

Layer: agents/runtime.
Constitutional home: 05_AGENTS §3 (the nine-phase lifecycle — this
module covers the mechanical shape: admission's allowlist half,
execution, completion; phases 3/4/6/7 are structurally real, no-ops
for this agent shape, not skipped — see ADR-041 D2), AG-005 (the tool
allowlist, enforced here before any dispatch), ADR-028 C4 (the
allowlist check is independent of, and prior to, the dispatcher's own
scope check).

Deliberately does NOT import `kang.api.dispatch` — `agents/runtime` may
not import `kang.api` at all (17 §4.2's own contract; not merely
"pre-M7", unconditional). `Dispatch` below is a plain, generic callable
shape instead, mirroring `api/http_binding.py`'s own "stays ignorant of
HOW a request reaches the Core" pattern: the composition root (or, this
slice, a test/live-check) supplies the real closure over a real
`Dispatcher`; this module only needs something shaped like "run one
operation, session-scoped."
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from kang.domain.ports.agent_definition import (
    AgentDefinition,
    CognitiveAgentNotSupported,
    ToolNotAllowed,
)
from kang.domain.ports.clock import Clock
from kang.domain.ports.session import Session, SessionStore

__all__ = ["AgentRunResult", "Dispatch", "ExecutorDeps", "run_mechanical_agent"]

# (operation, params, session_token, idempotency_key) -> the dispatcher's
# own response envelope, verbatim.
Dispatch = Callable[[str, dict[str, Any], str, str | None], dict[str, Any]]


@dataclass(frozen=True)
class ExecutorDeps:
    """The executor's own collaborators (11 §4: beyond a few params, a
    dataclass) — everything except the subject of one run (which agent,
    which operation, which params, which idempotency key)."""

    dispatch: Dispatch
    sessions: SessionStore
    new_id: Callable[[], str]
    clock: Clock


@dataclass(frozen=True)
class AgentRunResult:
    """One mechanical-agent run's outcome — the dispatch response plus
    which agent/operation produced it. Not a new persistence concept
    (ADR-041 D3: no outer `kind="agent"` invocation row this slice) —
    just enough for a caller to log or assert against."""

    agent_id: str
    operation: str
    response: dict[str, Any]


def run_mechanical_agent(
    agent: AgentDefinition,
    operation: str,
    params: dict[str, Any],
    deps: ExecutorDeps,
    *,
    idempotency_key: str | None = None,
) -> AgentRunResult:
    """Run one mechanical agent's single tool call (ADR-041 D1).

    Refuses BEFORE `deps.dispatch` is ever called if `agent.kind` is not
    `"mechanical"` (03_ROADMAP Phase 1: cognitive agents beyond basic
    chat are out of scope) or if `operation` is not in `agent.tools`
    (AG-005/ADR-028 C4 — a gate independent of, and prior to, whatever
    scope check `dispatch` itself performs).

    Mints a session for principal `agent:{id}`, `first_party=False` —
    mirrors `kernel/runtime/scheduler_wiring.py::_make_job_runner`
    exactly: "a job is not Kang's hand" applies verbatim to an agent
    (SEC-003 by construction — no agent principal can ever hold a
    first-party session, so none can ever approve a held action)."""
    if agent.kind != "mechanical":
        raise CognitiveAgentNotSupported(
            f"agent {agent.id!r} is kind={agent.kind!r}; the mechanical-agent "
            "executor (ADR-041) does not run cognitive agents"
        )
    if operation not in agent.tools:
        raise ToolNotAllowed(
            f"agent {agent.id!r} is not allowed to call {operation!r} "
            f"(its own tools: {agent.tools})"
        )

    session = Session(
        token=deps.new_id(),
        principal=f"agent:{agent.id}",
        first_party=False,
        created_at=deps.clock.now().isoformat(),
    )
    deps.sessions.create(session)

    response = deps.dispatch(operation, params, session.token, idempotency_key)
    return AgentRunResult(agent_id=agent.id, operation=operation, response=response)
