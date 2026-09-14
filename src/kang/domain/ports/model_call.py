"""ModelCallStore port — the usage & cost ledger (D010, AG-008,
07_DATABASE §5.5).

Layer: domain/ports. Ports own their datatypes (17 §7).
Constitutional home: 05_AGENTS AG-008 ("every call lands in `model_call`
(cost ledger); the health panel shows spend vs. caps daily"),
07_DATABASE §5.5 (`model_call`'s schema), docs/adr/038-model-router-
taskspec.md D4 ("every call logged, regardless of outcome" — the
ledger half of AG-008 this slice implements; threshold-based
enforcement is named-deferred, its own future slice).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

__all__ = ["MODEL_CALL_OUTCOMES", "ModelCall", "ModelCallStore"]

MODEL_CALL_OUTCOMES = ("ok", "error", "timeout", "fallback")


@dataclass(frozen=True)
class ModelCall:
    """One provider call attempt, permanently recorded. `outcome`
    semantics (ADR-038, since 07_DATABASE's own CHECK constraint names
    the four values but not their meaning): `ok` = this attempt
    succeeded; `fallback` = this attempt failed but the chain had
    another candidate to try next; `error` = this attempt (or the
    route's last attempt) failed with no further candidate; `timeout`
    is reserved, unused until a real provider adapter can distinguish a
    genuine timeout from `ProviderUnavailable`'s broader "could not
    reach it" — named here rather than fabricated early."""

    provider: str
    model: str
    task_class: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int
    outcome: str  # one of MODEL_CALL_OUTCOMES
    at: str


class ModelCallStore(Protocol):
    """Append-only — `model_call` rows are never updated (07_DATABASE
    §5.5: a usage ledger, not a mutable record)."""

    def record(self, call: ModelCall) -> None:
        """Append one row."""
        ...
