"""The Model Router (D010, ADR-038): fallback chains, the circuit
breaker, privacy-tier fail-closed, and the model_call ledger — all
against fakes, zero network (13 §1: "no network")."""

from __future__ import annotations

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.fakes.model_provider import FakeModelCallStore, FakeModelProvider
from kang.domain.ports.model_provider import (
    ModelResult,
    NoProviderAvailable,
    ProviderRefused,
    ProviderUnavailable,
    TaskSpec,
)
from kang.domain.ports.provider_config import ProviderEntry, ProvidersConfig
from kang.kernel.router.router import Router

SPEC = TaskSpec(
    task_class="routine",
    privacy_tier="normal",
    context_size=100,
    latency_tolerance="background",
)
PRIVATE_SPEC = TaskSpec(
    task_class="routine",
    privacy_tier="private",
    context_size=100,
    latency_tolerance="background",
)


def _config(**chains: list[ProviderEntry]) -> ProvidersConfig:
    return ProvidersConfig(chains={k: tuple(v) for k, v in chains.items()})


def test_routes_to_the_single_configured_provider():
    provider = FakeModelProvider(
        result=ModelResult(
            text="hi", structured=None, tokens_in=5, tokens_out=2,
            cost_usd=0.01, latency_ms=42,
        )
    )
    config = _config(routine=[ProviderEntry(name="anthropic", model="claude-haiku-4")])
    calls = FakeModelCallStore()
    router = Router(config, {"anthropic": provider}, calls, FakeClock())

    result = router.route(SPEC, "hello")

    assert result.text == "hi"
    assert provider.calls == [(SPEC, "claude-haiku-4", "hello", None)]
    assert len(calls.calls) == 1
    assert calls.calls[0].outcome == "ok"
    assert calls.calls[0].provider == "anthropic"
    assert calls.calls[0].tokens_in == 5
    assert calls.calls[0].cost_usd == 0.01


def test_falls_over_to_the_next_provider_on_provider_unavailable():
    first = FakeModelProvider(error=ProviderUnavailable("down"))
    second = FakeModelProvider(
        result=ModelResult(
            text="ok", structured=None, tokens_in=1, tokens_out=1,
            cost_usd=0.0, latency_ms=1,
        )
    )
    config = _config(
        routine=[
            ProviderEntry(name="a", model="m1"),
            ProviderEntry(name="b", model="m2"),
        ]
    )
    calls = FakeModelCallStore()
    router = Router(config, {"a": first, "b": second}, calls, FakeClock())

    result = router.route(SPEC, "hello")

    assert result.text == "ok"
    assert first.calls and second.calls  # both were genuinely tried
    assert [c.outcome for c in calls.calls] == ["fallback", "ok"]
    assert [c.provider for c in calls.calls] == ["a", "b"]


def test_provider_refused_propagates_immediately_never_advances_the_chain():
    first = FakeModelProvider(error=ProviderRefused("bad request"))
    second = FakeModelProvider()
    config = _config(
        routine=[
            ProviderEntry(name="a", model="m1"),
            ProviderEntry(name="b", model="m2"),
        ]
    )
    calls = FakeModelCallStore()
    router = Router(config, {"a": first, "b": second}, calls, FakeClock())

    with pytest.raises(ProviderRefused):
        router.route(SPEC, "hello")

    assert second.calls == []  # never tried — a caller bug, not a fallback case
    assert [c.outcome for c in calls.calls] == ["error"]


def test_every_candidate_failing_propagates_the_last_provider_unavailable():
    a = FakeModelProvider(error=ProviderUnavailable("down-a"))
    b = FakeModelProvider(error=ProviderUnavailable("down-b"))
    config = _config(
        routine=[
            ProviderEntry(name="a", model="m1"),
            ProviderEntry(name="b", model="m2"),
        ]
    )
    calls = FakeModelCallStore()
    router = Router(config, {"a": a, "b": b}, calls, FakeClock())

    with pytest.raises(ProviderUnavailable, match="down-b"):
        router.route(SPEC, "hello")

    assert [c.outcome for c in calls.calls] == ["fallback", "error"]


def test_no_chain_configured_raises_no_provider_available_without_logging():
    calls = FakeModelCallStore()
    router = Router(ProvidersConfig(), {}, calls, FakeClock())

    with pytest.raises(NoProviderAvailable):
        router.route(SPEC, "hello")

    assert calls.calls == []  # never even tried anything, nothing to log


def test_private_tier_fails_closed_when_no_local_only_provider_is_configured():
    # A chain exists for the task_class, but nothing in it is local_only
    # — ADR-038 D4's own fail-closed behavior, the router MUST NOT use
    # the cloud entry for private-tier content.
    provider = FakeModelProvider()
    config = _config(routine=[ProviderEntry(name="anthropic", model="claude-haiku-4")])
    calls = FakeModelCallStore()
    router = Router(config, {"anthropic": provider}, calls, FakeClock())

    with pytest.raises(NoProviderAvailable):
        router.route(PRIVATE_SPEC, "sensitive content")

    assert provider.calls == []  # the cloud provider was never even called


def test_private_tier_routes_to_a_local_only_provider_when_one_exists():
    local = FakeModelProvider(
        result=ModelResult(
            text="local", structured=None, tokens_in=1, tokens_out=1,
            cost_usd=0.0, latency_ms=5,
        )
    )
    config = _config(
        routine=[
            ProviderEntry(name="cloud", model="claude-haiku-4"),
            ProviderEntry(name="local", model="llama3", local_only=True),
        ]
    )
    calls = FakeModelCallStore()
    providers = {"cloud": FakeModelProvider(), "local": local}
    router = Router(config, providers, calls, FakeClock())

    result = router.route(PRIVATE_SPEC, "sensitive content")

    assert result.text == "local"
    assert [c.provider for c in calls.calls] == ["local"]


def test_configured_but_unwired_provider_is_skipped_silently():
    # providers.toml names a provider that isn't wired at the
    # composition root yet (no real adapter this slice) — the router
    # must not crash, just skip to the next real candidate.
    wired = FakeModelProvider()
    config = _config(
        routine=[
            ProviderEntry(name="not-wired", model="m1"),
            ProviderEntry(name="wired", model="m2"),
        ]
    )
    calls = FakeModelCallStore()
    router = Router(config, {"wired": wired}, calls, FakeClock())

    router.route(SPEC, "hello")

    assert wired.calls  # reached, despite the unwired entry ahead of it
    assert [c.provider for c in calls.calls] == ["wired"]


def test_circuit_breaker_opens_after_the_configured_failure_threshold():
    provider = FakeModelProvider(error=ProviderUnavailable("down"))
    backup = FakeModelProvider(
        result=ModelResult(
            text="ok", structured=None, tokens_in=1, tokens_out=1,
            cost_usd=0.0, latency_ms=1,
        )
    )
    config = ProvidersConfig(
        chains={
            "routine": (
                ProviderEntry(name="flaky", model="m1"),
                ProviderEntry(name="backup", model="m2"),
            )
        },
        circuit_breaker_failure_threshold=2,
        circuit_breaker_cooldown_s=30.0,
    )
    calls = FakeModelCallStore()
    clock = FakeClock()
    router = Router(config, {"flaky": provider, "backup": backup}, calls, clock)

    router.route(SPEC, "hello")  # failure 1, falls back to backup
    router.route(SPEC, "hello")  # failure 2 — trips the breaker
    assert len(provider.calls) == 2

    # Breaker is now open: a third call must not even try "flaky".
    router.route(SPEC, "hello")
    assert len(provider.calls) == 2  # unchanged — skipped, not tried


def test_circuit_breaker_closes_again_after_the_cooldown_elapses():
    provider = FakeModelProvider(error=ProviderUnavailable("down"))
    backup = FakeModelProvider(
        result=ModelResult(
            text="ok", structured=None, tokens_in=1, tokens_out=1,
            cost_usd=0.0, latency_ms=1,
        )
    )
    config = ProvidersConfig(
        chains={
            "routine": (
                ProviderEntry(name="flaky", model="m1"),
                ProviderEntry(name="backup", model="m2"),
            )
        },
        circuit_breaker_failure_threshold=1,
        circuit_breaker_cooldown_s=30.0,
    )
    calls = FakeModelCallStore()
    clock = FakeClock()
    router = Router(config, {"flaky": provider, "backup": backup}, calls, clock)

    router.route(SPEC, "hello")  # trips the breaker immediately (threshold=1)
    assert len(provider.calls) == 1

    clock.advance(10)  # still within the 30s cooldown
    router.route(SPEC, "hello")
    assert len(provider.calls) == 1  # still skipped

    clock.advance(21)  # now past the cooldown (31s elapsed total)
    router.route(SPEC, "hello")
    assert len(provider.calls) == 2  # tried again


def test_a_success_resets_the_consecutive_failure_count():
    provider = FakeModelProvider()
    backup = FakeModelProvider(
        result=ModelResult(
            text="backup-ok", structured=None, tokens_in=1, tokens_out=1,
            cost_usd=0.0, latency_ms=1,
        )
    )
    config = ProvidersConfig(
        chains={
            "routine": (
                ProviderEntry(name="flaky", model="m1"),
                ProviderEntry(name="backup", model="m2"),
            )
        },
        circuit_breaker_failure_threshold=2,
        circuit_breaker_cooldown_s=30.0,
    )
    calls = FakeModelCallStore()
    router = Router(config, {"flaky": provider, "backup": backup}, calls, FakeClock())

    provider.queue(ProviderUnavailable("blip"))
    router.route(SPEC, "hello")  # failure #1 of 2 needed to trip

    provider.queue(
        ModelResult(
            text="ok", structured=None, tokens_in=1, tokens_out=1,
            cost_usd=0.0, latency_ms=1,
        )
    )
    router.route(SPEC, "hello")  # success — resets the count to 0

    provider.queue(ProviderUnavailable("blip again"))
    router.route(SPEC, "hello")  # failure #1 again (not #2) — breaker still closed

    provider.queue(
        ModelResult(
            text="still reachable", structured=None, tokens_in=1, tokens_out=1,
            cost_usd=0.0, latency_ms=1,
        )
    )
    result = router.route(SPEC, "hello")
    assert result.text == "still reachable"  # "flaky" tried again, not skipped
