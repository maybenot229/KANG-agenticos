"""memory.toml loads fail-closed (ADR-051 D8): a malformed or absent file
refuses, and nothing falls back to a built-in expiry window."""

from __future__ import annotations

from pathlib import Path

import pytest

from kang.adapters.config.memory_loader import (
    MemoryConfigError,
    load_memory_config,
    load_scoring_config,
    parse_memory_config,
    parse_scoring_config,
)

REPO_ROOT = Path(__file__).resolve().parents[5]


def test_the_shipped_default_loads_with_its_one_real_key():
    config = load_memory_config(REPO_ROOT / "config" / "defaults" / "memory.toml")
    assert config.candidate_expiry_days == 14  # 06 Appendix A


def test_the_shipped_default_holds_only_keys_something_reads():
    # ADR-051's rule — no key ships without a reader — extended by ADR-056:
    # [scoring]/[search] are read by memory.search. Nothing else ships
    # (duplicate_cosine and [retention] still have no reader).
    import tomllib

    data = tomllib.loads(
        (REPO_ROOT / "config" / "defaults" / "memory.toml").read_text(encoding="utf-8")
    )
    # ADR-058: [assembly] is read by the Context Assembler.
    assert set(data) == {"gate", "scoring", "search", "assembly"}
    assert data["gate"] == {"candidate_expiry_days": 14}
    assert set(data["scoring"]) == {"weights", "half_life_days"}
    assert set(data["search"]) == {"match_min_similarity", "stopwords"}


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


# ---- [scoring]/[search] (ADR-056 D3) ----------------------------------------

SCORING_OK = """
[scoring.weights]
semantic = 0.4
lexical = 0.2
recency = 0.15
importance = 0.15
context = 0.1
[scoring.half_life_days]
fact = 180
observation = 30
preference = 0
relationship = 0
lesson = 0
rule = 0
profile = 0
reflection = 0
[search]
match_min_similarity = 0.5
stopwords = ["The", "of"]
"""


def test_the_shipped_scoring_matches_06_appendix_a():
    config = load_scoring_config(REPO_ROOT / "config" / "defaults" / "memory.toml")
    w = config.weights
    assert (w.semantic, w.lexical, w.recency, w.importance, w.context) == (
        0.40,
        0.20,
        0.15,
        0.15,
        0.10,
    )
    assert config.half_life_days["fact"] == 180  # 06 §5.2
    assert config.half_life_days["lesson"] == 0  # "principles don't age"


def test_a_gate_only_file_refuses_search_but_still_serves_the_gate():
    gate_only = "[gate]\ncandidate_expiry_days = 14\n"
    assert parse_memory_config(gate_only).candidate_expiry_days == 14
    with pytest.raises(MemoryConfigError):
        parse_scoring_config(gate_only)


@pytest.mark.parametrize(
    "broken",
    [
        SCORING_OK.replace("context = 0.1\n", ""),  # a weight missing
        SCORING_OK.replace("reflection = 0\n", ""),  # a type missing
        SCORING_OK.replace("semantic = 0.4", "semantic = -0.4"),
        SCORING_OK.replace("semantic = 0.4", "semantic = true"),
        SCORING_OK.replace("0.5", "1.5"),
        SCORING_OK.replace("[search]", "[elsewhere]"),
        SCORING_OK.replace('stopwords = ["The", "of"]', 'stopwords = "the"'),
        SCORING_OK.replace('stopwords = ["The", "of"]\n', ""),
    ],
)
def test_a_malformed_scoring_table_refuses_rather_than_defaulting(broken):
    assert broken != SCORING_OK  # every case really breaks something
    with pytest.raises(MemoryConfigError):
        parse_scoring_config(broken)


def test_stopwords_are_case_folded():
    assert parse_scoring_config(SCORING_OK).stopwords == frozenset({"the", "of"})


# ---- [assembly] (ADR-058 D3) ------------------------------------------------


def test_the_shipped_budget_shares_are_06_appendix_a():
    from kang.adapters.config.memory_loader import load_assembly_config

    config = load_assembly_config(REPO_ROOT / "config" / "defaults" / "memory.toml")
    assert config.budget_shares == {
        "p0": 0.30,
        "p1": 0.15,
        "p2": 0.30,
        "p3": 0.15,
        "p4": 0.10,
    }


@pytest.mark.parametrize(
    "shares",
    [
        "{ p0 = 0.3, p1 = 0.15, p2 = 0.3, p3 = 0.15 }",  # a class missing
        "{ p0 = 0.5, p1 = 0.15, p2 = 0.3, p3 = 0.15, p4 = 0.1 }",  # sums past 1
        "{ p0 = -0.1, p1 = 0.35, p2 = 0.3, p3 = 0.35, p4 = 0.1 }",  # negative
    ],
)
def test_malformed_budget_shares_refuse(shares):
    from kang.adapters.config.memory_loader import parse_assembly_config

    with pytest.raises(MemoryConfigError):
        parse_assembly_config(f"[assembly]\nbudget_shares = {shares}\n")
