"""AnthropicProvider — the real `ModelProvider` adapter (D010, ADR-039).

Layer: adapters/anthropic.
Constitutional home: 04_ARCHITECTURE D010 (the `ModelProvider` port this
implements), 05_AGENTS §9 ("Via Model Router only... direct provider
SDK access is architecturally absent from the runtime" — `Router` is
the only caller of this class), 10_SECURITY SEC-011 (the API key comes
from `CredentialStore`, requested by name, held only for this call's
own duration — never cached on the instance, never logged).

Structured output (`response_schema`) is NOT implemented this slice —
ADR-039 D3: D010's own "invalid output → bounded retry → typed failure"
discipline needs its own design (a tool schema built from the Pydantic
model, forced `tool_choice`, parsing the tool-use block, the retry loop
itself), and nothing calls this adapter with one yet (the Router isn't
wired into `Core` at all — ADR-038 D1). Passing one raises
`NotImplementedError` loudly, never a silent ignore of the request.
"""

from __future__ import annotations

import time

import anthropic

from kang.domain.ports.credentials import CredentialNotFound, CredentialStore
from kang.domain.ports.model_provider import (
    ModelResult,
    ProviderRefused,
    ProviderUnavailable,
    TaskSpec,
)

__all__ = ["AnthropicProvider"]

CREDENTIAL_NAME = "kang.model_provider.anthropic"

MAX_TOKENS = 4096

# SDK exceptions that mean "this specific request or credential is the
# problem" — never retried, never advances the Router's fallback chain
# (ADR-039 D3: trying a different provider doesn't fix a malformed
# request or a bad key on THIS one). Everything else — including any
# anthropic.AnthropicError subtype not named here — falls to
# ProviderUnavailable, the safer default when this adapter genuinely
# doesn't recognize what went wrong.
_REFUSAL_ERRORS = (
    anthropic.BadRequestError,
    anthropic.AuthenticationError,
    anthropic.PermissionDeniedError,
    anthropic.NotFoundError,
    anthropic.ConflictError,
    anthropic.UnprocessableEntityError,
    anthropic.RequestTooLargeError,
)

# $ per million tokens — an adapter-owned SNAPSHOT, not authoritative
# (ADR-039 D3: Anthropic's own pricing changes over time, D010's own
# "providers will change pricing... routing must be config, not
# surgery" already names this class of drift). Verify against
# Anthropic's current pricing page before relying on this for a real
# budget decision. An unrecognized model yields cost_usd=0.0 — a
# flagged unpriced case, never a guessed number (see _cost_usd).
_PRICE_PER_MILLION_TOKENS_USD = {
    "claude-opus-4": {"in": 15.0, "out": 75.0},
    "claude-haiku-4": {"in": 0.8, "out": 4.0},
}


def _cost_usd(model: str, tokens_in: int, tokens_out: int) -> float:
    prices = _PRICE_PER_MILLION_TOKENS_USD.get(model)
    if prices is None:
        return 0.0  # unpriced, not free — see module docstring
    return (tokens_in * prices["in"] + tokens_out * prices["out"]) / 1_000_000


class AnthropicProvider:
    """`ModelProvider` over the official `anthropic` SDK. The API key is
    fetched fresh from `CredentialStore` on every call (SEC-011: never
    cached) — a genuinely new client per call, not a persistent one
    holding the key in memory between calls."""

    def __init__(self, credentials: CredentialStore) -> None:
        self._credentials = credentials

    def call(
        self,
        spec: TaskSpec,
        model: str,
        prompt: str,
        response_schema: type | None = None,
    ) -> ModelResult:
        if response_schema is not None:
            raise NotImplementedError(
                "AnthropicProvider does not implement response_schema "
                "(structured output) yet — text-only this slice, ADR-039 D3"
            )
        try:
            api_key = self._credentials.get(CREDENTIAL_NAME)
        except CredentialNotFound as exc:
            # Not one of the port's three declared errors, and
            # deliberately not left to propagate as its own type: a
            # missing/misconfigured credential means THIS provider
            # can't serve the request right now, same shape as a
            # provider being unreachable — ProviderUnavailable lets the
            # Router's fallback chain do its job (D010: "provider down
            # -> next in chain") instead of the whole route() call
            # crashing on an exception type it doesn't expect.
            raise ProviderUnavailable(str(exc)) from exc
        client = anthropic.Anthropic(api_key=api_key)
        started = time.monotonic()
        try:
            response = client.messages.create(
                model=model,
                max_tokens=MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
            )
        except _REFUSAL_ERRORS as exc:
            raise ProviderRefused(str(exc)) from exc
        except anthropic.AnthropicError as exc:
            raise ProviderUnavailable(str(exc)) from exc
        latency_ms = int((time.monotonic() - started) * 1000)
        text = "".join(block.text for block in response.content if block.type == "text")
        tokens_in = response.usage.input_tokens
        tokens_out = response.usage.output_tokens
        return ModelResult(
            text=text,
            structured=None,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=_cost_usd(model, tokens_in, tokens_out),
            latency_ms=latency_ms,
        )
