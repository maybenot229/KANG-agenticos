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
    CognitiveToolLoopNotSupported,
    MechanicalAgentNotSupported,
    ToolNotAllowed,
)
from kang.domain.ports.clock import Clock
from kang.domain.ports.conversation_store import (
    ConversationNotFound,
    ConversationStore,
    Message,
)
from kang.domain.ports.model_provider import (
    ModelResult,
    NoProviderAvailable,
    ProviderUnavailable,
    TaskSpec,
)
from kang.domain.ports.session import Session, SessionStore

__all__ = [
    "AgentRunResult",
    "CHAT_HISTORY_LIMIT",
    "ChatTurnDeps",
    "CognitiveExecutorDeps",
    "Dispatch",
    "ExecutorDeps",
    "RouterRoute",
    "run_chat_turn",
    "run_cognitive_agent",
    "run_mechanical_agent",
]

# ADR-046 D5: a plain count cap, not a token-budget-aware truncation
# (that is Phase-2 Context-Assembler territory, 06_MEMORY's own real
# "Chat (general)" recipe — chat's own recipe stays deferred to it).
# Named as a known simplification, not hidden.
CHAT_HISTORY_LIMIT = 20

# (operation, params, session_token, idempotency_key) -> the dispatcher's
# own response envelope, verbatim.
Dispatch = Callable[[str, dict[str, Any], str, str | None], dict[str, Any]]

# (spec, prompt) -> the Router's own ModelResult, verbatim. A generic,
# port-shaped callable rather than importing kang.kernel.router.Router
# directly — agents/runtime may not import kernel (17 §4.2); the
# composition root supplies the real closure over a real Router (ADR-044).
RouterRoute = Callable[[TaskSpec, str], ModelResult]


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
class CognitiveExecutorDeps:
    """The cognitive executor's own collaborators (ADR-044), mirroring
    `ExecutorDeps`'s own shape. `read_prompt` resolves an agent's own
    `prompt_file` to text — file I/O the composition root performs
    (which knows `AGENT_DEFINITIONS_DIR`), injected here rather than
    done in this module, which stays pure/I/O-free like its sibling."""

    route: RouterRoute
    read_prompt: Callable[[AgentDefinition], str]
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


def _compose_prompt(
    persona: str,
    history: tuple[Message, ...],
    context_chips: list[str],
    message: str,
) -> str:
    """One flat string — `ModelProvider.call()` accepts no separate
    system/user channel (confirmed reading `AnthropicProvider.call()`:
    one `role: "user"` message, always). Chips are labeled, not merged
    into `message`, so they are never mistaken for Kang's own words
    (ADR-044 D4). `history` (ADR-046 D5) is the prior transcript,
    already oldest-first (`ConversationStore.recent_messages`'s own
    contract) — rendered ahead of the current chips/message, which
    describe *this* turn, not the past ones."""
    chips_block = "\n".join(f"- {chip}" for chip in context_chips) or "(none)"
    history_block = "\n".join(f"{m.role}: {m.content}" for m in history) or "(none yet)"
    return (
        f"{persona}\n\n"
        f"## Prior conversation\n{history_block}\n\n"
        f"## Current context (Kang's own chips)\n{chips_block}\n\n"
        f"## Kang's message\n{message}\n"
    )


def run_cognitive_agent(
    agent: AgentDefinition,
    message: str,
    context_chips: list[str],
    history: tuple[Message, ...],
    deps: CognitiveExecutorDeps,
) -> AgentRunResult:
    """Run one cognitive agent's single conversational turn (ADR-044 D2)
    — the mirror of `run_mechanical_agent`, for a model call instead of
    a tool call. `history` (ADR-046) is prior turns to compose into the
    prompt — this function itself does no persistence; that is
    `run_chat_turn`'s own job, below.

    Refuses BEFORE `deps.route` is ever called if `agent.kind` is not
    `"cognitive"`, or if `agent.tools` is non-empty (no tool-calling
    loop exists yet — AG-005's allowlist has nothing to enforce against
    without one; refused loudly, never a silent ignore of a declared
    capability).

    Mints a session for principal `agent:{id}`, `first_party=False` —
    the same bounded-authority shape every other agent gets, deliberately
    not a special case for "it's Kang's own conversation" (ADR-044 D2's
    own argued rejection of that framing: a consequential proposal inside
    chat breaks out into Kang's own real first-party confirmation later,
    it does not need chat's own session to already hold his authority).

    On `ProviderUnavailable`/`NoProviderAvailable`: returns the agent's
    own `degradation` text with `response["degraded"] = True` — never an
    invented reply (AGP-8). `ProviderRefused` is NOT caught here — a
    malformed request or bad credential is a real bug/config problem,
    not a degradable runtime condition; it propagates to the dispatcher's
    own top-level catch (API-006), which returns an honest `internal`
    error envelope rather than a fabricated conversational reply."""
    if agent.kind != "cognitive":
        raise MechanicalAgentNotSupported(
            f"agent {agent.id!r} is kind={agent.kind!r}; the cognitive-agent "
            "executor (ADR-044) does not run mechanical agents"
        )
    if agent.tools:
        raise CognitiveToolLoopNotSupported(
            f"agent {agent.id!r} declares tools {agent.tools!r}, but no "
            "tool-calling loop exists yet (ADR-044)"
        )

    session = Session(
        token=deps.new_id(),
        principal=f"agent:{agent.id}",
        first_party=False,
        created_at=deps.clock.now().isoformat(),
    )
    deps.sessions.create(session)

    persona = deps.read_prompt(agent)
    prompt = _compose_prompt(persona, history, context_chips, message)
    spec = TaskSpec(
        task_class="deep_reasoning",
        privacy_tier="normal",
        context_size=len(prompt) // 4,
        latency_tolerance="interactive",
    )
    try:
        result = deps.route(spec, prompt)
    except (ProviderUnavailable, NoProviderAvailable):
        return AgentRunResult(
            agent_id=agent.id,
            operation="model.call",
            response={"reply": agent.degradation, "degraded": True},
        )
    return AgentRunResult(
        agent_id=agent.id,
        operation="model.call",
        response={"reply": result.text, "degraded": False},
    )


@dataclass(frozen=True)
class ChatTurnDeps:
    """`run_chat_turn`'s own collaborators (ADR-046) — wraps
    `CognitiveExecutorDeps` rather than duplicating `new_id`/`clock`,
    plus the one new dependency this turn-level orchestration needs."""

    cognitive: CognitiveExecutorDeps
    conversations: ConversationStore


def run_chat_turn(
    agent: AgentDefinition,
    message: str,
    context_chips: list[str],
    conversation_id: str | None,
    deps: ChatTurnDeps,
) -> dict:
    """One real, persisted multi-turn exchange (ADR-046) — the
    conversation-lifecycle orchestration `run_cognitive_agent` itself
    deliberately does not own. `conversation_id=None` starts a new
    conversation (the server mints the id, matching every other entity
    in this codebase — ADR-046 D4); a real id continues an existing one
    (`ConversationNotFound` propagates for an unknown one, never a
    silent create-under-that-id).

    Persistence order: Kang's own message is appended BEFORE the model
    call (a crash mid-call still records what Kang actually said); the
    reply is appended AFTER, as `role="agent"` on success or
    `role="kang_system"` when degraded (ADR-046 D3 — a real system
    notice, never the agent "speaking" a reply it didn't generate).

    Returns a plain dict matching `ChatSendResponse`'s own shape
    exactly (`reply`, `degraded`, `conversation_id`) — `chat_ops.py`'s
    handler returns this verbatim, no reshaping needed."""
    clock = deps.cognitive.clock
    new_id = deps.cognitive.new_id

    if conversation_id is None:
        conversation_id = new_id()
        deps.conversations.start(conversation_id, clock.now().isoformat())
    elif deps.conversations.get(conversation_id) is None:
        raise ConversationNotFound(f"no conversation {conversation_id!r}")

    history = deps.conversations.recent_messages(conversation_id, CHAT_HISTORY_LIMIT)
    deps.conversations.append_message(
        conversation_id, new_id(), "kang", message, clock.now().isoformat()
    )

    result = run_cognitive_agent(agent, message, context_chips, history, deps.cognitive)
    reply = result.response["reply"]
    degraded = result.response["degraded"]

    deps.conversations.append_message(
        conversation_id,
        new_id(),
        "kang_system" if degraded else "agent",
        reply,
        clock.now().isoformat(),
    )

    return {"reply": reply, "degraded": degraded, "conversation_id": conversation_id}
