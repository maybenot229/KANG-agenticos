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
    ExecutorDeps,
    run_mechanical_agent,
)
from kang.domain.ports.agent_definition import (
    AgentDefinition,
    CognitiveAgentNotSupported,
    ToolNotAllowed,
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
