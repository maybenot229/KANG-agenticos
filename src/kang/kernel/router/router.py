"""The Model Router (D010, ADR-038) — `TaskSpec` in, `ModelResult` out,
never a model name from the caller.

Layer: kernel.
Constitutional home: 04_ARCHITECTURE D010 (fallback chains + circuit
breakers; structured-output discipline is delegated to the adapter —
the Router doesn't know or care whether a call asked for structured
output, only whether it succeeded or raised), 05_AGENTS §9 (`model.*`:
"Via Model Router only... direct provider SDK access is architecturally
absent from the runtime" — this class is the only door), AG-008 (every
call logged to `model_call` — the ledger half; threshold enforcement is
ADR-038 D4's own named, deferred gap, not implemented here), ADR-038 D4
(privacy-tier fail-closed, the circuit breaker's exact shape).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from pydantic import BaseModel

from kang.domain.ports.clock import Clock
from kang.domain.ports.model_call import ModelCall, ModelCallStore
from kang.domain.ports.model_provider import (
    ModelProvider,
    ModelResult,
    NoProviderAvailable,
    ProviderRefused,
    ProviderUnavailable,
    TaskSpec,
)
from kang.domain.ports.provider_config import ProviderEntry, ProvidersConfig

__all__ = ["Router"]


class Router:
    """Routes a `TaskSpec` to a provider via `providers.toml`'s chain for
    its `task_class`, honoring `privacy_tier` (fails closed) and a
    per-provider circuit breaker. Every attempt, success or failure, is
    logged to `model_call` (AG-008's ledger half)."""

    def __init__(
        self,
        config: ProvidersConfig,
        providers: dict[str, ModelProvider],
        calls: ModelCallStore,
        clock: Clock,
    ) -> None:
        self._config = config
        self._providers = providers
        self._calls = calls
        self._clock = clock
        self._consecutive_failures: dict[str, int] = {}
        self._breaker_open_until: dict[str, datetime] = {}

    def route(
        self,
        spec: TaskSpec,
        prompt: str,
        response_schema: type[BaseModel] | None = None,
    ) -> ModelResult:
        """Try each candidate in `spec.task_class`'s chain, in order,
        skipping any presently circuit-broken. Raises `NoProviderAvailable`
        if no candidate can even be tried (D4: an empty/filtered chain,
        or every candidate circuit-broken) — a candidate genuinely tried
        and refused propagates its own `ProviderUnavailable`/
        `ProviderRefused` instead, since "tried and failed" and "never
        reachable to begin with" are different facts."""
        candidates = self._candidates(spec)
        triable = [c for c in candidates if not self._breaker_is_open(c.name)]
        if not triable:
            raise NoProviderAvailable(
                f"no provider available for task_class={spec.task_class!r} "
                f"privacy_tier={spec.privacy_tier!r}"
            )

        last_error: ProviderUnavailable | None = None
        for index, entry in enumerate(triable):
            provider = self._providers.get(entry.name)
            if provider is None:
                continue  # configured in providers.toml, not wired at boot
            has_next = any(
                self._providers.get(e.name) is not None for e in triable[index + 1 :]
            )
            try:
                result = provider.call(spec, entry.model, prompt, response_schema)
            except ProviderUnavailable as exc:
                last_error = exc
                self._record_failure(entry.name)
                outcome = "fallback" if has_next else "error"
                self._log_failure(entry, spec, outcome=outcome)
                continue
            except ProviderRefused:
                self._log_failure(entry, spec, outcome="error")
                raise
            self._record_success(entry.name)
            self._log_success(entry, spec, result)
            return result

        if last_error is not None:
            raise last_error
        raise NoProviderAvailable(
            f"no wired provider for task_class={spec.task_class!r} "
            f"privacy_tier={spec.privacy_tier!r}"
        )

    def _candidates(self, spec: TaskSpec) -> tuple[ProviderEntry, ...]:
        chain = self._config.chain_for(spec.task_class)
        if spec.privacy_tier == "private":
            # D4: fails closed — never a cloud provider for private
            # content, even if the chain has one configured.
            return tuple(entry for entry in chain if entry.local_only)
        return chain

    def _breaker_is_open(self, name: str) -> bool:
        open_until = self._breaker_open_until.get(name)
        if open_until is None:
            return False
        if self._clock.now() >= open_until:
            del self._breaker_open_until[name]
            self._consecutive_failures[name] = 0
            return False
        return True

    def _record_failure(self, name: str) -> None:
        count = self._consecutive_failures.get(name, 0) + 1
        self._consecutive_failures[name] = count
        if count >= self._config.circuit_breaker_failure_threshold:
            self._breaker_open_until[name] = self._clock.now() + timedelta(
                seconds=self._config.circuit_breaker_cooldown_s
            )

    def _record_success(self, name: str) -> None:
        self._consecutive_failures[name] = 0

    def _log_success(
        self, entry: ProviderEntry, spec: TaskSpec, result: ModelResult
    ) -> None:
        self._calls.record(
            ModelCall(
                provider=entry.name,
                model=entry.model,
                task_class=spec.task_class,
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
                cost_usd=result.cost_usd,
                latency_ms=result.latency_ms,
                outcome="ok",
                at=self._clock.now().isoformat(),
            )
        )

    def _log_failure(self, entry: ProviderEntry, spec: TaskSpec, outcome: str) -> None:
        self._calls.record(
            ModelCall(
                provider=entry.name,
                model=entry.model,
                task_class=spec.task_class,
                tokens_in=0,
                tokens_out=0,
                cost_usd=0.0,
                latency_ms=0,
                outcome=outcome,
                at=self._clock.now().isoformat(),
            )
        )
