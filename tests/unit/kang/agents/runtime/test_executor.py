"""The mechanical-agent executor (05_AGENTS §3, ADR-041): the allowlist
gate, session minting, and dispatch — against a fake `Dispatch`
callable and the real `FakeSessionStore` (13 §2.3). No real Dispatcher/
ApiRequest anywhere here — proving `executor.py` never needed to import
`kang.api` at all (ADR-041's own layering point).
"""

from __future__ import annotations

import itertools

import pytest

from kang.adapters.fakes.api_stores import FakeSessionStore
from kang.adapters.fakes.clock import FakeClock
from kang.agents.runtime.executor import (
    AgentRunResult,
    CognitiveExecutorDeps,
    ExecutorDeps,
    run_cognitive_agent,
    run_mechanical_agent,
)
from kang.domain.ports.agent_definition import (
    AgentDefinition,
    CognitiveAgentNotSupported,
    CognitiveToolLoopNotSupported,
    MechanicalAgentNotSupported,
    ToolNotAllowed,
)
from kang.domain.ports.model_provider import (
    ModelResult,
    NoProviderAvailable,
    ProviderRefused,
    ProviderUnavailable,
)

MECHANICAL_AGENT = AgentDefinition(
    id="deadline_sweep",
    kind="mechanical",
    mandate="Lead-time alerts; missed-deadline detection (FR-031)",
    triggers=("sched:hourly",),
    tools=("deadline.sweep",),
    scopes=(),
    timeout_s=120,
    retry=2,
    degradation="No degradation path needed.",
    recipe=None,
    pipelines=(),
    prompt_file=None,
    escalation=None,
)

COGNITIVE_AGENT = AgentDefinition(
    id="critic",
    kind="cognitive",
    mandate="Adversarial review.",
    triggers=("chained",),
    tools=("notify:digest",),
    scopes=("memory.read:critic-view",),
    timeout_s=600,
    retry=0,
    degradation="Unavailable.",
    recipe="critic-view",
    pipelines=(),
    prompt_file="prompts/system.md",
    escalation=None,
)

CHAT_AGENT = AgentDefinition(
    id="chat",
    kind="cognitive",
    mandate="Converse with Kang using client-supplied context chips.",
    triggers=("kang",),
    tools=(),
    scopes=(),
    timeout_s=60,
    retry=0,
    degradation="Chat is unavailable right now.",
    recipe=None,
    pipelines=(),
    prompt_file="prompts/system.md",
    escalation=None,
)


class _RecordingDispatch:
    """Stands in for a real `Dispatcher.dispatch()` closure, shaped
    exactly like `agents.runtime.executor.Dispatch` — the executor
    never sees, and never needs, the real `ApiRequest`/`Dispatcher`."""

    def __init__(self, response: dict | None = None) -> None:
        self._response = response or {"ok": True, "result": {}}
        self.calls: list[tuple[str, dict, str, str | None]] = []

    def __call__(self, operation, params, session_token, idempotency_key):
        self.calls.append((operation, params, session_token, idempotency_key))
        return self._response


def _new_id_factory():
    ids = itertools.count(1)
    return lambda: f"id-{next(ids)}"


def _deps(dispatch=None, sessions=None, new_id=None, clock=None) -> ExecutorDeps:
    return ExecutorDeps(
        dispatch=dispatch or _RecordingDispatch(),
        sessions=sessions if sessions is not None else FakeSessionStore(),
        new_id=new_id or _new_id_factory(),
        clock=clock or FakeClock(),
    )


def test_refuses_a_cognitive_agent_before_any_dispatch():
    dispatch = _RecordingDispatch()
    sessions = FakeSessionStore()

    with pytest.raises(CognitiveAgentNotSupported):
        run_mechanical_agent(
            COGNITIVE_AGENT, "some.op", {}, _deps(dispatch=dispatch, sessions=sessions)
        )

    assert dispatch.calls == []
    assert sessions._by_token == {}  # nothing minted either — refused first


def test_refuses_an_operation_outside_the_tools_allowlist():
    dispatch = _RecordingDispatch()

    with pytest.raises(ToolNotAllowed, match="not-a-real-tool"):
        run_mechanical_agent(
            MECHANICAL_AGENT, "not-a-real-tool", {}, _deps(dispatch=dispatch)
        )

    assert dispatch.calls == []


def test_dispatches_the_allowed_operation_with_a_freshly_minted_agent_session():
    dispatch = _RecordingDispatch(response={"ok": True, "result": {"swept": 3}})
    sessions = FakeSessionStore()
    clock = FakeClock()

    result = run_mechanical_agent(
        MECHANICAL_AGENT,
        "deadline.sweep",
        {"some": "param"},
        _deps(dispatch=dispatch, sessions=sessions, clock=clock),
        idempotency_key="agent:deadline_sweep:2026-09-16T00:00:00",
    )

    assert isinstance(result, AgentRunResult)
    assert result.agent_id == "deadline_sweep"
    assert result.operation == "deadline.sweep"
    assert result.response == {"ok": True, "result": {"swept": 3}}

    assert len(dispatch.calls) == 1
    operation, params, session_token, idempotency_key = dispatch.calls[0]
    assert operation == "deadline.sweep"
    assert params == {"some": "param"}
    assert idempotency_key == "agent:deadline_sweep:2026-09-16T00:00:00"

    # The session dispatch used is a REAL one the executor minted, not a
    # placeholder — resolvable through the same SessionStore a real
    # Dispatcher's own _authenticate would use.
    session = sessions.resolve(session_token)
    assert session.principal == "agent:deadline_sweep"
    assert session.first_party is False  # SEC-003 by construction
    assert session.created_at == clock.now().isoformat()


def test_idempotency_key_is_optional_and_passed_through_as_none():
    dispatch = _RecordingDispatch()
    deps = _deps(dispatch=dispatch)
    run_mechanical_agent(MECHANICAL_AGENT, "deadline.sweep", {}, deps)
    assert dispatch.calls[0][3] is None


def test_each_run_mints_its_own_session_token():
    dispatch = _RecordingDispatch()
    deps = _deps(dispatch=dispatch)

    run_mechanical_agent(MECHANICAL_AGENT, "deadline.sweep", {}, deps)
    run_mechanical_agent(MECHANICAL_AGENT, "deadline.sweep", {}, deps)

    tokens = {call[2] for call in dispatch.calls}
    assert len(tokens) == 2  # never reused across invocations


# ---- run_cognitive_agent (ADR-044) ----------------------------------------


class _RecordingRoute:
    """Stands in for `Router.route`, shaped exactly like
    `agents.runtime.executor.RouterRoute` — the executor never sees, and
    never needs, the real `Router`."""

    def __init__(
        self, result: ModelResult | None = None, raises: Exception | None = None
    ):
        self._result = result
        self._raises = raises
        self.calls: list[tuple] = []

    def __call__(self, spec, prompt):
        self.calls.append((spec, prompt))
        if self._raises is not None:
            raise self._raises
        return self._result


def _cognitive_deps(
    route=None, sessions=None, new_id=None, clock=None
) -> CognitiveExecutorDeps:
    return CognitiveExecutorDeps(
        route=route or _RecordingRoute(ModelResult(
            text="a reply", structured=None, tokens_in=10, tokens_out=5,
            cost_usd=0.0, latency_ms=100,
        )),
        read_prompt=lambda agent: f"persona-for-{agent.id}",
        sessions=sessions if sessions is not None else FakeSessionStore(),
        new_id=new_id or _new_id_factory(),
        clock=clock or FakeClock(),
    )


def test_run_cognitive_agent_refuses_a_mechanical_agent_before_any_route_call():
    route = _RecordingRoute()
    with pytest.raises(MechanicalAgentNotSupported):
        run_cognitive_agent(MECHANICAL_AGENT, "hi", [], _cognitive_deps(route=route))
    assert route.calls == []


def test_run_cognitive_agent_refuses_a_non_empty_tools_allowlist():
    route = _RecordingRoute()
    with pytest.raises(CognitiveToolLoopNotSupported, match="notify:digest"):
        run_cognitive_agent(COGNITIVE_AGENT, "hi", [], _cognitive_deps(route=route))
    assert route.calls == []


def test_run_cognitive_agent_composes_persona_plus_chips_plus_message():
    route = _RecordingRoute(ModelResult(
        text="ok", structured=None, tokens_in=1, tokens_out=1, cost_usd=0.0,
        latency_ms=1,
    ))
    run_cognitive_agent(
        CHAT_AGENT, "what's today?", ["chip one", "chip two"],
        _cognitive_deps(route=route),
    )
    assert len(route.calls) == 1
    spec, prompt = route.calls[0]
    assert spec.task_class == "deep_reasoning"
    assert spec.privacy_tier == "normal"
    assert spec.latency_tolerance == "interactive"
    assert "persona-for-chat" in prompt
    assert "chip one" in prompt
    assert "chip two" in prompt
    assert "what's today?" in prompt


def test_run_cognitive_agent_returns_the_real_reply_on_success():
    result = run_cognitive_agent(CHAT_AGENT, "hi", [], _cognitive_deps())
    assert isinstance(result, AgentRunResult)
    assert result.agent_id == "chat"
    assert result.operation == "model.call"
    assert result.response == {"reply": "a reply", "degraded": False}


@pytest.mark.parametrize(
    "exc", [ProviderUnavailable("down"), NoProviderAvailable("none")]
)
def test_run_cognitive_agent_degrades_never_inventing_a_reply(exc):
    route = _RecordingRoute(raises=exc)
    result = run_cognitive_agent(CHAT_AGENT, "hi", [], _cognitive_deps(route=route))
    assert result.response == {"reply": CHAT_AGENT.degradation, "degraded": True}


def test_run_cognitive_agent_propagates_provider_refused():
    route = _RecordingRoute(raises=ProviderRefused("bad request"))
    with pytest.raises(ProviderRefused):
        run_cognitive_agent(CHAT_AGENT, "hi", [], _cognitive_deps(route=route))


def test_run_cognitive_agent_mints_a_non_first_party_agent_session():
    sessions = FakeSessionStore()
    clock = FakeClock()
    deps = _cognitive_deps(sessions=sessions, clock=clock)
    run_cognitive_agent(CHAT_AGENT, "hi", [], deps)
    [session] = sessions._by_token.values()
    assert session.principal == "agent:chat"
    assert session.first_party is False  # SEC-003 by construction, no special case
    assert session.created_at == clock.now().isoformat()
