"""OllamaProvider (ADR-055 D2) against an injected HTTP call — never a live
network in CI (13 §2.3). The live server was exercised by hand on
2026-10-05; that is a smoke check, not a test."""

from __future__ import annotations

import json

import pytest

from kang.adapters.ollama.provider import OllamaProvider
from kang.domain.ports.model_provider import (
    ProviderRefused,
    ProviderUnavailable,
    TaskSpec,
)

SPEC = TaskSpec("embedding", "normal", 10, "background")


def _post(status: int, body: object, seen: list | None = None):
    def post(url: str, payload: bytes, timeout_s: float):
        if seen is not None:
            seen.append((url, json.loads(payload), timeout_s))
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        return status, raw

    return post


def test_embed_posts_the_texts_and_parses_one_vector_per_text():
    seen: list = []
    body = {"embeddings": [[0.1, 0.2], [0.3, 0.4]], "prompt_eval_count": 7}
    provider = OllamaProvider("http://127.0.0.1:11434", _post(200, body, seen))
    result = provider.embed(SPEC, "nomic-embed-text", ("a", "b"))
    assert result.vectors == ((0.1, 0.2), (0.3, 0.4))
    assert (result.model, result.tokens_in, result.cost_usd) == (
        "nomic-embed-text",
        7,
        0.0,
    )
    ((url, payload, _),) = seen
    assert url == "http://127.0.0.1:11434/api/embed"
    assert payload == {"model": "nomic-embed-text", "input": ["a", "b"]}


@pytest.mark.parametrize("status", [404, 500, 503])
def test_a_missing_model_or_server_error_is_unavailable(status):
    provider = OllamaProvider(post=_post(status, {"error": "nope"}))
    with pytest.raises(ProviderUnavailable):
        provider.embed(SPEC, "m", ("a",))


def test_another_client_error_is_a_refusal():
    provider = OllamaProvider(post=_post(400, {"error": "bad request"}))
    with pytest.raises(ProviderRefused):
        provider.embed(SPEC, "m", ("a",))


def test_an_unreachable_server_is_unavailable():
    def refused(url, payload, timeout_s):
        raise ConnectionRefusedError("no server")

    with pytest.raises(ProviderUnavailable):
        OllamaProvider(post=refused).embed(SPEC, "m", ("a",))


@pytest.mark.parametrize("body", [b"not json", {"nothing": 1}, {"embeddings": [[0.1]]}])
def test_a_malformed_or_short_body_is_unavailable(body):
    provider = OllamaProvider(post=_post(200, body))
    with pytest.raises(ProviderUnavailable):
        provider.embed(SPEC, "m", ("a", "b"))


def test_text_generation_stays_reserved():
    provider = OllamaProvider(post=_post(200, {}))
    with pytest.raises(ProviderRefused):
        provider.call(TaskSpec("private", "private", 10, "background"), "m", "hi")
