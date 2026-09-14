"""In-memory Model Router ports — provider call + usage ledger (13 §2.3).

Layer: adapters/fakes.
Constitutional home: 11_CODING §5/§7 (every port has an in-memory fake),
docs/adr/038-model-router-taskspec.md D1 (`Router` is proven against
these, never a live network call, this slice — the whole point of the
scope cut). Grouped in one module: both are the Router's own small,
closely-related state ports.
"""

from __future__ import annotations

from typing import Any

from kang.domain.ports.model_call import ModelCall
from kang.domain.ports.model_provider import ModelResult, TaskSpec

__all__ = ["FakeModelCallStore", "FakeModelProvider"]


class FakeModelProvider:
    """Returns queued results/raises queued exceptions, in call order;
    falls back to a fixed `result`/`error` (constructor args) once the
    queue is empty, or a bland default `ModelResult` if neither was
    given. Records every call's `(spec, prompt, response_schema)` for
    assertion — `Router` tests check this rather than a real network
    call ever happening."""

    def __init__(
        self,
        *,
        result: ModelResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self._default_result = result
        self._default_error = error
        self._queue: list[ModelResult | Exception] = []
        self.calls: list[tuple[TaskSpec, str, Any]] = []

    def queue(self, outcome: ModelResult | Exception) -> None:
        """Schedule the next call's outcome — consumed in FIFO order."""
        self._queue.append(outcome)

    def call(
        self, spec: TaskSpec, prompt: str, response_schema: Any = None
    ) -> ModelResult:
        self.calls.append((spec, prompt, response_schema))
        if self._queue:
            outcome: ModelResult | Exception = self._queue.pop(0)
        elif self._default_error is not None:
            outcome = self._default_error
        elif self._default_result is not None:
            outcome = self._default_result
        else:
            outcome = ModelResult(
                text="ok",
                structured=None,
                tokens_in=1,
                tokens_out=1,
                cost_usd=0.0,
                latency_ms=1,
            )
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeModelCallStore:
    def __init__(self) -> None:
        self.calls: list[ModelCall] = []

    def record(self, call: ModelCall) -> None:
        self.calls.append(call)
