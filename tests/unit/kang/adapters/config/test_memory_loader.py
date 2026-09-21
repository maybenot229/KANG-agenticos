"""memory.toml loads fail-closed (ADR-051 D8): a malformed or absent file
refuses, and nothing falls back to a built-in expiry window."""

from __future__ import annotations

from pathlib import Path

import pytest

from kang.adapters.config.memory_loader import (
    MemoryConfigError,
    load_memory_config,
    parse_memory_config,
)

REPO_ROOT = Path(__file__).resolve().parents[5]


def test_the_shipped_default_loads_with_its_one_real_key():
    config = load_memory_config(REPO_ROOT / "config" / "defaults" / "memory.toml")
    assert config.candidate_expiry_days == 14  # 06 Appendix A


def test_the_shipped_default_holds_only_the_gate_table_and_key():
    import tomllib

    data = tomllib.loads(
        (REPO_ROOT / "config" / "defaults" / "memory.toml").read_text(encoding="utf-8")
    )
    assert data == {"gate": {"candidate_expiry_days": 14}}


def test_an_absent_file_refuses(tmp_path):
    with pytest.raises(MemoryConfigError):
        load_memory_config(tmp_path / "memory.toml")


@pytest.mark.parametrize(
    "text",
    [
        "this is = not [valid toml",
        "",
        "[other]\nx = 1\n",
        "[gate]\n",
        "[gate]\ncandidate_expiry_days = 0\n",
        "[gate]\ncandidate_expiry_days = -3\n",
        '[gate]\ncandidate_expiry_days = "14"\n',
        "[gate]\ncandidate_expiry_days = 14.5\n",
        "[gate]\ncandidate_expiry_days = true\n",
        "gate = 14\n",
    ],
)
def test_a_malformed_file_refuses_rather_than_defaulting(text):
    with pytest.raises(MemoryConfigError):
        parse_memory_config(text)


def test_extra_keys_are_tolerated_but_the_real_key_is_required():
    parsed = parse_memory_config(
        "[gate]\ncandidate_expiry_days = 7\nfuture_key = 1\n[scoring]\nx = 1\n"
    )
    assert parsed.candidate_expiry_days == 7
