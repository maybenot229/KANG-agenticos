"""AnthropicProvider (D010, ADR-039) — request-building, credential
handling, and error-mapping, against a mocked SDK client. No live
network call anywhere (13 §1) — the `anthropic.Anthropic` class itself
is monkeypatched to a fake; every response/exception object constructed
is a REAL SDK type (`anthropic.types.Message` et al., real exception
classes), never a loose mock, so a field-name typo here would fail the
same way it would against the real SDK.
"""

from __future__ import annotations

import httpx2
import pytest
from anthropic import (
    AnthropicError,
    APIConnectionError,
    AuthenticationError,
    BadRequestError,
)
from anthropic.types import Message, TextBlock, Usage

import kang.adapters.anthropic.provider as provider_module
from kang.adapters.anthropic.provider import CREDENTIAL_NAME, AnthropicProvider
from kang.adapters.fakes.credentials import FakeCredentialStore
from kang.domain.ports.model_provider import (
    ProviderRefused,
    ProviderUnavailable,
    TaskSpec,
)

SPEC = TaskSpec(
    task_class="routine",
    privacy_tier="normal",
    context_size=10,
    latency_tolerance="interactive",
)
_REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def _message(text: str, tokens_in: int, tokens_out: int) -> Message:
    return Message(
        id="msg_1",
        content=[TextBlock(text=text, type="text")],
        model="claude-haiku-4",
        role="assistant",
        stop_reason="end_turn",
        stop_sequence=None,
        type="message",
        usage=Usage(input_tokens=tokens_in, output_tokens=tokens_out),
    )


class _FakeMessages:
    def __init__(self, outcome) -> None:
        self._outcome = outcome
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


class _FakeClient:
    """Stands in for `anthropic.Anthropic` — captures the api_key it was
    constructed with, exposes a controllable `.messages.create`."""

    instances: list["_FakeClient"] = []

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.messages = _FakeMessages(_FakeClient.next_outcome)
        _FakeClient.instances.append(self)


def _install(monkeypatch, outcome) -> None:
    _FakeClient.instances = []
    _FakeClient.next_outcome = outcome
    monkeypatch.setattr(provider_module.anthropic, "Anthropic", _FakeClient)


def test_successful_call_returns_a_model_result_with_usage_and_cost(monkeypatch):
    _install(monkeypatch, _message("hi there", tokens_in=1000, tokens_out=500))
    credentials = FakeCredentialStore({CREDENTIAL_NAME: "sk-real-looking-key"})
    provider = AnthropicProvider(credentials)

    result = provider.call(SPEC, "claude-haiku-4", "hello")

    assert result.text == "hi there"
    assert result.tokens_in == 1000
    assert result.tokens_out == 500
    # $0.8/M in, $4.0/M out (the adapter's own pricing snapshot)
    assert result.cost_usd == pytest.approx(1000 * 0.8 / 1e6 + 500 * 4.0 / 1e6)
    assert result.latency_ms >= 0


def test_fetches_the_credential_by_the_declared_name_fresh_every_call(monkeypatch):
    _install(monkeypatch, _message("ok", 1, 1))
    credentials = FakeCredentialStore({CREDENTIAL_NAME: "sk-abc"})
    provider = AnthropicProvider(credentials)

    provider.call(SPEC, "claude-haiku-4", "one")
    provider.call(SPEC, "claude-haiku-4", "two")

    # Two calls -> two genuinely separate client constructions, never a
    # client held on the instance across calls (SEC-011: in-memory only
    # for the duration of the call).
    assert len(_FakeClient.instances) == 2
    assert all(c.api_key == "sk-abc" for c in _FakeClient.instances)


def test_a_missing_credential_becomes_provider_unavailable(monkeypatch):
    _install(monkeypatch, _message("unreachable", 1, 1))
    provider = AnthropicProvider(FakeCredentialStore())  # nothing seeded

    with pytest.raises(ProviderUnavailable):
        provider.call(SPEC, "claude-haiku-4", "hello")

    assert _FakeClient.instances == []  # never even got as far as a client


def test_bad_request_error_becomes_provider_refused(monkeypatch):
    error = BadRequestError(
        "bad prompt", response=httpx2.Response(400, request=_REQUEST), body=None
    )
    _install(monkeypatch, error)
    credentials = FakeCredentialStore({CREDENTIAL_NAME: "sk-abc"})
    provider = AnthropicProvider(credentials)

    with pytest.raises(ProviderRefused):
        provider.call(SPEC, "claude-haiku-4", "hello")


def test_authentication_error_becomes_provider_refused_not_unavailable(monkeypatch):
    # A bad/expired key is never fallback-chain-eligible in the sense of
    # "retry this same provider" — ADR-039 D3's own reasoning.
    error = AuthenticationError(
        "invalid api key", response=httpx2.Response(401, request=_REQUEST), body=None
    )
    _install(monkeypatch, error)
    credentials = FakeCredentialStore({CREDENTIAL_NAME: "sk-wrong"})
    provider = AnthropicProvider(credentials)

    with pytest.raises(ProviderRefused):
        provider.call(SPEC, "claude-haiku-4", "hello")


def test_connection_error_becomes_provider_unavailable(monkeypatch):
    error = APIConnectionError(request=_REQUEST)
    _install(monkeypatch, error)
    credentials = FakeCredentialStore({CREDENTIAL_NAME: "sk-abc"})
    provider = AnthropicProvider(credentials)

    with pytest.raises(ProviderUnavailable):
        provider.call(SPEC, "claude-haiku-4", "hello")


def test_an_unrecognized_anthropic_error_defaults_to_provider_unavailable(monkeypatch):
    # A subtype this adapter doesn't explicitly name in _REFUSAL_ERRORS
    # must still map somewhere safe, not leak as a bare Exception.
    class _SomeFutureAnthropicError(AnthropicError):
        pass

    _install(monkeypatch, _SomeFutureAnthropicError("unexpected"))
    credentials = FakeCredentialStore({CREDENTIAL_NAME: "sk-abc"})
    provider = AnthropicProvider(credentials)

    with pytest.raises(ProviderUnavailable):
        provider.call(SPEC, "claude-haiku-4", "hello")


def test_an_unrecognized_model_has_zero_cost_not_a_guessed_number(monkeypatch):
    _install(monkeypatch, _message("ok", 1000, 1000))
    credentials = FakeCredentialStore({CREDENTIAL_NAME: "sk-abc"})
    provider = AnthropicProvider(credentials)

    result = provider.call(SPEC, "some-future-model-not-in-the-table", "hello")

    assert result.cost_usd == 0.0


def test_response_schema_raises_not_implemented(monkeypatch):
    _install(monkeypatch, _message("ok", 1, 1))
    credentials = FakeCredentialStore({CREDENTIAL_NAME: "sk-abc"})
    provider = AnthropicProvider(credentials)

    with pytest.raises(NotImplementedError):
        provider.call(SPEC, "claude-haiku-4", "hello", response_schema=object)
