"""memory.toml loader — the memory system's tunable, fail-closed (ADR-051 D8).

Layer: adapters/config (TOML parsing is I/O at the boundary — mirrors
`providers_loader.py`/`permissions_loader.py`).
Constitutional home: 06_MEMORY Appendix A (`[gate]`), ADR-051 D8: an absent or
malformed file is a `MemoryConfigError`; the caller (the composition root)
refuses to serve the gate — it never falls back to a built-in default,
because a silently defaulted expiry window makes 06 §4.3's "silence is a
veto" contract unverifiable.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from kang.domain.ports.memory_config import MemoryConfig

__all__ = ["MemoryConfigError", "load_memory_config", "parse_memory_config"]


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
