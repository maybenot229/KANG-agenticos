"""providers.toml loader (D010, ADR-038 D5): parse, fail closed."""

from __future__ import annotations

from pathlib import Path

import pytest

from kang.adapters.config.providers_loader import (
    ProvidersLoadError,
    load_providers,
    parse_providers,
)
from kang.domain.ports.provider_config import ProvidersConfig

REPO_ROOT = Path(__file__).resolve().parents[5]


def test_parses_a_chain_per_task_class():
    config = parse_providers(
        "[task_class.routine]\n"
        'chain = [{ name = "anthropic", model = "claude-haiku-4" }]\n'
    )
    chain = config.chain_for("routine")
    assert len(chain) == 1
    assert chain[0].name == "anthropic"
    assert chain[0].model == "claude-haiku-4"
    assert chain[0].local_only is False


def test_local_only_flag_parses_true():
    config = parse_providers(
        "[task_class.private]\n"
        'chain = [{ name = "ollama", model = "llama3", local_only = true }]\n'
    )
    assert config.chain_for("private")[0].local_only is True


def test_unlisted_task_class_has_an_empty_chain():
    config = parse_providers("[task_class.routine]\nchain = []\n")
    assert config.chain_for("deep_reasoning") == ()


def test_malformed_toml_raises():
    with pytest.raises(ProvidersLoadError, match="valid TOML"):
        parse_providers("[task_class\nbroken")


def test_chain_entry_missing_model_raises():
    with pytest.raises(ProvidersLoadError, match="'name' and 'model'"):
        parse_providers('[task_class.routine]\nchain = [{ name = "anthropic" }]\n')


def test_missing_file_raises_for_fallback():
    with pytest.raises(ProvidersLoadError, match="unreadable"):
        load_providers(Path("does-not-exist.toml"))


def test_absent_file_fallback_is_an_empty_config_every_task_class_fails_closed():
    # ADR-038 D5: the caller's own fallback (mirroring composition.py's
    # _load_grants) is an empty ProvidersConfig — every task class routes
    # to nothing until a valid file exists.
    empty = ProvidersConfig()
    assert empty.chain_for("routine") == ()
    assert empty.chain_for("deep_reasoning") == ()


def test_circuit_breaker_settings_parse_with_defaults():
    config = parse_providers("")
    assert config.circuit_breaker_failure_threshold == 3
    assert config.circuit_breaker_cooldown_s == 60.0

    configured = parse_providers(
        "[circuit_breaker]\nfailure_threshold = 5\ncooldown_s = 30.0\n"
    )
    assert configured.circuit_breaker_failure_threshold == 5
    assert configured.circuit_breaker_cooldown_s == 30.0


def test_budget_fields_parse_but_are_advisory_only():
    # ADR-038 D4: parsed and carried, not enforced by anything yet — this
    # test only proves the round-trip, not any enforcement behavior.
    config = parse_providers(
        "[budget]\nmonthly_cap_usd = 50.0\n"
        "[budget.per_task_class_cap_usd]\nroutine = 15.0\n"
    )
    assert config.monthly_cap_usd == 50.0
    assert config.per_task_class_cap_usd_by_class == {"routine": 15.0}


def test_budget_section_is_optional():
    config = parse_providers("[task_class.routine]\nchain = []\n")
    assert config.monthly_cap_usd is None
    assert config.per_task_class_cap_usd_by_class == {}


def test_shipped_default_loads_and_fails_closed_for_private():
    config = load_providers(REPO_ROOT / "config" / "defaults" / "providers.toml")
    assert config.chain_for("routine")[0].name == "anthropic"
    # No local_only provider ships yet (Ollama is Phase 5, RESERVED) —
    # the private chain is empty by construction (ADR-038 D4).
    assert config.chain_for("private") == ()
    assert config.monthly_cap_usd == 50.0
