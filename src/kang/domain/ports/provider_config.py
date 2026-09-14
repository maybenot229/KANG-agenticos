"""Router configuration types — `providers.toml`, parsed (D010, ADR-038 D5).

Layer: domain/ports. Ports own their datatypes (17 §7): this is the
shape both the adapter that parses `providers.toml`
(`adapters/config/providers_loader.py`) and the kernel that consumes it
(`kernel/router/`) agree on, without either importing the other's
concrete module (17 §4.3 — adapters and kernel meet only at the
composition root).
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["ProviderEntry", "ProvidersConfig"]


@dataclass(frozen=True)
class ProviderEntry:
    """One provider's entry in one task class's fallback chain."""

    name: str  # matches a ModelProvider wired by name at the composition root
    model: str  # the concrete model id that provider's call should use
    local_only: bool = False  # ADR-038 D4: a candidate for privacy_tier="private"


@dataclass(frozen=True)
class ProvidersConfig:
    """The fully parsed `providers.toml` — or the fail-closed empty
    default (ADR-038 D5: an absent/invalid file yields this, not a
    default-open "try everything"). One ordered provider chain per
    task class; a task class with no entry has an empty chain, same as
    a missing file.

    `monthly_cap_usd`/`per_task_class_cap_usd_by_class` are AG-008's
    already-accepted budget hierarchy's own config fields (05_AGENTS
    §12) — parsed and carried here so the shape is right from the
    start, but NOT read or acted on by `Router` yet (ADR-038 D4: the
    ledger half of AG-008 is this slice's job, threshold enforcement is
    its own named, deferred slice)."""

    chains: dict[str, tuple[ProviderEntry, ...]] = field(default_factory=dict)
    circuit_breaker_failure_threshold: int = 3
    circuit_breaker_cooldown_s: float = 60.0
    monthly_cap_usd: float | None = None
    per_task_class_cap_usd_by_class: dict[str, float] = field(default_factory=dict)

    def chain_for(self, task_class: str) -> tuple[ProviderEntry, ...]:
        return self.chains.get(task_class, ())
