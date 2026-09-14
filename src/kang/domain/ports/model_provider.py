"""ModelProvider port — the Model Router's one call shape into any AI
provider (D010, ADR-038).

Layer: domain/ports. Ports own their datatypes (17 §7).
Constitutional home: 04_ARCHITECTURE D010 ("a kernel-level Model Router
behind a single `ModelProvider` port... callers declare intent, not
models... structured-output discipline: all machine-consumed outputs
are schema-validated; invalid output → bounded retry → typed failure"),
05_AGENTS §9 (`model.*`: "Via Model Router only... direct provider SDK
access is architecturally absent from the runtime" — this port is the
only door), docs/adr/038-model-router-taskspec.md D2/D3 (`TaskSpec`'s
exact four fields, this port's exact call shape, the typed-error set).

`TaskSpec.privacy_tier` reuses `sensitivity`'s exact three-value
vocabulary (06_MEMORY, 07_DATABASE §5.1) rather than inventing a fifth
enum — orthogonal to `task_class`, never inferred from it (ADR-038's
own Context finding: a `routine`-class classification call can still
carry `privacy_tier="private"` content).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel

__all__ = [
    "LATENCY_TOLERANCES",
    "PRIVACY_TIERS",
    "TASK_CLASSES",
    "ModelProvider",
    "ModelResult",
    "NoProviderAvailable",
    "ProviderRefused",
    "ProviderUnavailable",
    "StructuredOutputInvalid",
    "TaskSpec",
]

TASK_CLASSES = ("deep_reasoning", "routine", "classification", "embedding", "private")
PRIVACY_TIERS = ("normal", "sensitive", "private")  # == sensitivity's own vocabulary
LATENCY_TOLERANCES = ("interactive", "background")


@dataclass(frozen=True)
class TaskSpec:
    """A caller's declared intent (D010: "callers declare intent, not
    models") — never a model name. `task_class="private"` is reserved
    for work that has no other honest class; it is NOT how a caller
    marks sensitive content — that is `privacy_tier`, independently
    (ADR-038 D2)."""

    task_class: str  # one of TASK_CLASSES
    privacy_tier: str  # one of PRIVACY_TIERS
    context_size: int  # approximate input tokens; the router's own estimate
    latency_tolerance: str  # one of LATENCY_TOLERANCES


@dataclass(frozen=True)
class ModelResult:
    """One provider call's outcome, shaped to write straight into a
    `model_call` row without reconstruction (07_DATABASE §5.5).
    `cost_usd` is the ADAPTER's own computation (it alone knows its
    provider's per-token pricing) — the Router relays it verbatim,
    never computes or defaults it itself (rule 8.6: a cost the Router
    cannot know is not the Router's to invent, the same discipline
    `api/schemas/invocation.py` already states for the general
    invocation ledger's own cost field)."""

    text: str | None
    structured: BaseModel | None
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int


class ProviderUnavailable(Exception):
    """The provider could not be reached or returned a server error
    (network, 5xx) — fallback-chain-eligible (D010's own "fallback
    chain... never a silent hang")."""


class ProviderRefused(Exception):
    """The provider rejected the request itself (4xx, a malformed call)
    — a caller bug, never retried and never advances the fallback chain
    (retrying a bad request against a different provider would just
    fail differently, hiding the real bug)."""


class StructuredOutputInvalid(Exception):
    """`response_schema` was given and the provider's output never
    validated against it within the adapter's own bounded retry (D010's
    "invalid output → bounded retry → typed failure"). Raised by the
    ADAPTER, never the Router — the retry itself is provider-specific."""


class NoProviderAvailable(Exception):
    """No provider in `providers.toml` can even be TRIED for this
    TaskSpec — either every candidate in its task_class's chain is
    presently circuit-broken, or (routinely, until Phase 5's local-model
    migration lands) `privacy_tier="private"` has no `local_only`
    provider configured at all. Fails closed (ADR-038 D4): never
    silently falls back to a provider that would not honor the tier.
    Distinct from every candidate being genuinely TRIED and failing —
    that propagates the last `ProviderUnavailable` instead, since a
    provider genuinely attempted and refused is a different fact than
    one never reachable to begin with."""


class ModelProvider(Protocol):
    """One provider's own implementation of the port — Anthropic,
    OpenAI, Ollama, or a fake (ADR-038 D1: only the fake ships this
    slice). `Router` (`kernel/router/`) is the only caller; nothing
    else in the codebase may reach a provider directly."""

    def call(
        self,
        spec: TaskSpec,
        prompt: str,
        response_schema: type[BaseModel] | None,
    ) -> ModelResult:
        """Run one call. Raises `ProviderUnavailable` / `ProviderRefused`
        / `StructuredOutputInvalid` — never a bare `Exception` (D010's
        typed-failure discipline applies at this boundary, not just the
        API's)."""
        ...
