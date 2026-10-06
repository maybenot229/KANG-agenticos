"""memory.toml loader — the memory system's tunable, fail-closed (ADR-051 D8).

Layer: adapters/config (TOML parsing is I/O at the boundary — mirrors
`providers_loader.py`/`permissions_loader.py`).
Constitutional home: 06_MEMORY Appendix A (`[gate]`), ADR-051 D8: an absent or
malformed file is a `MemoryConfigError`; the caller (the composition root)
refuses to serve the gate — it never falls back to a built-in default,
because a silently defaulted expiry window makes 06 §4.3's "silence is a
veto" contract unverifiable.

ADR-056 D3 adds `[scoring]`/`[search]` (06 §5.2 / Appendix A), parsed by
`parse_scoring_config` — separately, so each part fails closed only for its
own reader: a missing `[scoring]` refuses `memory.search`, never the gate.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from kang.domain.ports.memory_config import MemoryConfig, ScoringConfig, ScoringWeights
from kang.domain.ports.memory_store import MEMORY_TYPES

__all__ = [
    "MemoryConfigError",
    "load_memory_config",
    "load_scoring_config",
    "parse_memory_config",
    "parse_scoring_config",
]

_WEIGHTS = ("semantic", "lexical", "recency", "importance", "context")


class MemoryConfigError(Exception):
    """memory.toml is missing, unreadable, or malformed. The gate refuses to
    build (ADR-051 D8) — there is no fallback value."""


def parse_memory_config(toml_text: str) -> MemoryConfig:
    try:
        data = tomllib.loads(toml_text)
    except tomllib.TOMLDecodeError as exc:
        raise MemoryConfigError(f"memory.toml is not valid TOML: {exc}") from exc
    gate = data.get("gate")
    if not isinstance(gate, dict):
        raise MemoryConfigError("memory.toml needs a [gate] table")
    days = gate.get("candidate_expiry_days")
    # bool is an int subclass: `true` must not read as 1 day.
    if not isinstance(days, int) or isinstance(days, bool) or days < 1:
        raise MemoryConfigError(
            "memory.toml [gate] candidate_expiry_days must be a positive integer"
        )
    return MemoryConfig(candidate_expiry_days=days)


def load_memory_config(path: Path) -> MemoryConfig:
    """Load from `path`. Raises MemoryConfigError if absent or invalid."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise MemoryConfigError(f"memory.toml unreadable at {path}: {exc}") from exc
    return parse_memory_config(text)


def _number(value: object) -> bool:
    # bool is an int subclass: `true` must not read as 1.
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def parse_scoring_config(toml_text: str) -> ScoringConfig:
    """`[scoring]` (five non-negative weights; a non-negative half-life for
    every type in the closed taxonomy, 0 = no decay) and `[search]`
    (`match_min_similarity` in [0, 1]; `stopwords`, a list of words dropped
    from the lexical half). Raises MemoryConfigError — never a
    default."""
    try:
        data = tomllib.loads(toml_text)
    except tomllib.TOMLDecodeError as exc:
        raise MemoryConfigError(f"memory.toml is not valid TOML: {exc}") from exc
    scoring, search = data.get("scoring"), data.get("search")
    if not isinstance(scoring, dict) or not isinstance(search, dict):
        raise MemoryConfigError(
            "memory.toml needs [scoring] and [search] tables for memory.search "
            "(copy them from config/defaults/memory.toml — ADR-056 D3)"
        )
    weights = scoring.get("weights")
    if not isinstance(weights, dict) or set(weights) != set(_WEIGHTS):
        raise MemoryConfigError(f"[scoring] weights must name exactly {_WEIGHTS}")
    half_lives = scoring.get("half_life_days")
    if not isinstance(half_lives, dict) or set(half_lives) != set(MEMORY_TYPES):
        raise MemoryConfigError(
            f"[scoring] half_life_days must name every memory type {MEMORY_TYPES}"
        )
    values = [*weights.values(), *half_lives.values()]
    if not all(_number(v) and v >= 0 for v in values):
        raise MemoryConfigError("[scoring] values must be non-negative numbers")
    floor = search.get("match_min_similarity")
    if not _number(floor) or not 0 <= floor <= 1:
        raise MemoryConfigError("[search] match_min_similarity must be in [0, 1]")
    stopwords = search.get("stopwords")
    if not isinstance(stopwords, list) or not all(
        isinstance(w, str) for w in stopwords
    ):
        raise MemoryConfigError("[search] stopwords must be a list of words")
    return ScoringConfig(
        weights=ScoringWeights(*(float(weights[k]) for k in _WEIGHTS)),
        half_life_days={t: float(half_lives[t]) for t in MEMORY_TYPES},
        match_min_similarity=float(floor),
        stopwords=frozenset(w.casefold() for w in stopwords),
    )


def load_scoring_config(path: Path) -> ScoringConfig:
    """Load `[scoring]`/`[search]` from `path`. Raises MemoryConfigError."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise MemoryConfigError(f"memory.toml unreadable at {path}: {exc}") from exc
    return parse_scoring_config(text)
