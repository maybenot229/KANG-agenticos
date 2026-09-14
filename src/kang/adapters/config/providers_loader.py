"""providers.toml loader — routing truth from the file (D010, ADR-038 D5).

Layer: adapters/config (the config adapter; TOML parsing is I/O at the
boundary — mirrors `permissions_loader.py`'s own shape exactly, same
class of surface).
Constitutional home: 04_ARCHITECTURE D010 (`providers.toml` as the
routing config's home), docs/adr/038-model-router-taskspec.md D5
(fail-closed like `permissions.toml`, not open like `kang.toml`): an
absent or invalid file is a `ProvidersLoadError`; the caller (the
composition root) falls back to an empty `ProvidersConfig` — every
task class routes to nothing until a valid file exists, never a
default-open "try any configured provider."
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from kang.domain.ports.provider_config import ProviderEntry, ProvidersConfig

__all__ = ["ProvidersLoadError", "load_providers", "parse_providers"]


class ProvidersLoadError(Exception):
    """providers.toml is missing, unreadable, or malformed. The caller
    falls back to an empty `ProvidersConfig` (ADR-038 D5)."""


def _parse_chain(task_class: str, spec: Any) -> tuple[ProviderEntry, ...]:
    if not isinstance(spec, dict) or not isinstance(spec.get("chain"), list):
        raise ProvidersLoadError(
            f"[task_class.{task_class}] must have a 'chain' list"
        )
    entries: list[ProviderEntry] = []
    for entry in spec["chain"]:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("name"), str)
            or not isinstance(entry.get("model"), str)
        ):
            raise ProvidersLoadError(
                f"[task_class.{task_class}] chain entries need string "
                "'name' and 'model'"
            )
        entries.append(
            ProviderEntry(
                name=entry["name"],
                model=entry["model"],
                local_only=bool(entry.get("local_only", False)),
            )
        )
    return tuple(entries)


def parse_providers(toml_text: str) -> ProvidersConfig:
    """Parse routing config text. Raises ProvidersLoadError on malformed
    structure."""
    try:
        data = tomllib.loads(toml_text)
    except tomllib.TOMLDecodeError as exc:
        raise ProvidersLoadError(f"providers.toml is not valid TOML: {exc}") from exc

    raw_classes = data.get("task_class", {})
    if not isinstance(raw_classes, dict):
        raise ProvidersLoadError("providers.toml [task_class] must be a table")
    chains = {
        task_class: _parse_chain(task_class, spec)
        for task_class, spec in raw_classes.items()
    }

    breaker = data.get("circuit_breaker", {})
    if not isinstance(breaker, dict):
        raise ProvidersLoadError("providers.toml [circuit_breaker] must be a table")
    try:
        failure_threshold = int(breaker.get("failure_threshold", 3))
        cooldown_s = float(breaker.get("cooldown_s", 60.0))
    except (TypeError, ValueError) as exc:
        raise ProvidersLoadError(
            "providers.toml [circuit_breaker] fields must be numeric"
        ) from exc

    monthly_cap_usd, per_class_caps = _parse_budget(data.get("budget", {}))

    return ProvidersConfig(
        chains=chains,
        circuit_breaker_failure_threshold=failure_threshold,
        circuit_breaker_cooldown_s=cooldown_s,
        monthly_cap_usd=monthly_cap_usd,
        per_task_class_cap_usd_by_class=per_class_caps,
    )


def _parse_budget(budget: Any) -> tuple[float | None, dict[str, float]]:
    """AG-008's config shape, parsed but not yet enforced (ADR-038 D4).
    Absent `[budget]` is valid (no caps declared, matching this ADR's
    own "not read or acted on yet" — a missing section is not itself a
    fail-closed trigger the way a missing chain is)."""
    if not isinstance(budget, dict):
        raise ProvidersLoadError("providers.toml [budget] must be a table")
    monthly_raw = budget.get("monthly_cap_usd")
    per_class_raw = budget.get("per_task_class_cap_usd", {})
    if not isinstance(per_class_raw, dict):
        raise ProvidersLoadError(
            "providers.toml [budget.per_task_class_cap_usd] must be a table"
        )
    try:
        monthly_cap_usd = float(monthly_raw) if monthly_raw is not None else None
        per_class_caps = {k: float(v) for k, v in per_class_raw.items()}
    except (TypeError, ValueError) as exc:
        raise ProvidersLoadError(
            "providers.toml [budget] fields must be numeric"
        ) from exc
    return monthly_cap_usd, per_class_caps


def load_providers(path: Path) -> ProvidersConfig:
    """Load routing truth from `path`. Raises ProvidersLoadError if the
    file is absent or invalid — the caller decides the fail-closed
    fallback (ADR-038 D5)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProvidersLoadError(f"providers.toml unreadable at {path}: {exc}") from exc
    return parse_providers(text)
