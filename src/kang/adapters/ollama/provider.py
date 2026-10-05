"""OllamaProvider — the `ModelProvider` adapter for a local Ollama server,
embedding only (ADR-055 D2; ADR-054 D1/D2/D7).

Layer: adapters/ollama.
Constitutional home: 04_ARCHITECTURE D010 (`class: embedding` →
"Embedding model (local-preferred)"), docs/adr/054-embedding-model-and-
dimension.md D2 (Ollama is the embedding runtime; no ML stack inside KANG,
17 §9: model weights are the runtime's to store, not KANG's), ADR-055 D2.

Text generation (`call`) is NOT implemented and refuses loudly: local
`private`/`routine` generation stays RESERVED behind 03_ROADMAP's
"Local-model migration per task class" trigger (ADR-054 D7), which has not
fired. Only `embed` serves.

The HTTP call is injected (`post`) so the contract is tested without a
network (13 §2.3); the default uses stdlib `urllib` — the Router is
synchronous, and a one-endpoint JSON POST needs no HTTP dependency.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Callable

from kang.domain.ports.model_provider import (
    EmbeddingResult,
    ModelResult,
    ProviderRefused,
    ProviderUnavailable,
    TaskSpec,
)

__all__ = ["DEFAULT_BASE_URL", "OllamaProvider", "Post", "urllib_post"]

# Ollama's own documented default bind. 127.0.0.1, not "localhost": a name
# lookup can resolve elsewhere; the loopback address cannot.
DEFAULT_BASE_URL = "http://127.0.0.1:11434"

# A first call loads the model into memory (seconds); a batch of eight at the
# spike's measured ~1.24 chunks/s is under ten. Generous, never unbounded.
TIMEOUT_S = 60.0

# (url, json body, timeout_s) -> (http status, response body). Raises
# OSError (urllib.error.URLError is one) when the server cannot be reached.
Post = Callable[[str, bytes, float], tuple[int, bytes]]


def urllib_post(url: str, body: bytes, timeout_s: float) -> tuple[int, bytes]:
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


class OllamaProvider:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, post: Post = urllib_post):
        self._base_url = base_url.rstrip("/")
        self._post = post

    def call(
        self,
        spec: TaskSpec,
        model: str,
        prompt: str,
        response_schema: type | None = None,
    ) -> ModelResult:
        raise ProviderRefused(
            "OllamaProvider serves embeddings only — local text generation is "
            "RESERVED (03_ROADMAP §8 'Local-model migration per task class', "
            "ADR-054 D7); check providers.toml"
        )

    def embed(
        self, spec: TaskSpec, model: str, texts: tuple[str, ...]
    ) -> EmbeddingResult:
        body = json.dumps({"model": model, "input": list(texts)}).encode("utf-8")
        started = time.monotonic()
        try:
            status, raw = self._post(f"{self._base_url}/api/embed", body, TIMEOUT_S)
        except OSError as exc:  # refused connection, DNS, timeout
            raise ProviderUnavailable(f"Ollama unreachable: {exc}") from exc
        latency_ms = int((time.monotonic() - started) * 1000)
        if status == 404 or status >= 500:
            # 404 is Ollama's "model not pulled": this provider cannot serve
            # now, which is the chain's business, not a caller bug.
            raise ProviderUnavailable(f"Ollama answered {status}: {raw[:200]!r}")
        if status >= 400:
            raise ProviderRefused(
                f"Ollama refused the request ({status}): {raw[:200]!r}"
            )
        return EmbeddingResult(
            vectors=_vectors(raw, len(texts)),
            model=model,
            tokens_in=_tokens_in(raw),
            cost_usd=0.0,  # local: no per-token price exists to compute
            latency_ms=latency_ms,
        )


def _vectors(raw: bytes, expected: int) -> tuple[tuple[float, ...], ...]:
    try:
        embeddings = json.loads(raw)["embeddings"]
        vectors = tuple(tuple(float(x) for x in vector) for vector in embeddings)
    except (ValueError, KeyError, TypeError) as exc:
        raise ProviderUnavailable(f"Ollama returned a malformed body: {exc}") from exc
    if len(vectors) != expected:
        raise ProviderUnavailable(
            f"Ollama returned {len(vectors)} vectors for {expected} texts"
        )
    return vectors


def _tokens_in(raw: bytes) -> int:
    count = json.loads(raw).get("prompt_eval_count", 0)
    return count if isinstance(count, int) else 0
