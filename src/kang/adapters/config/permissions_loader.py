"""permissions.toml loader — grant truth from the file (D003).

Layer: adapters/config (the config adapter; TOML parsing is I/O at the
boundary).
Constitutional home: 05_AGENTS §8 (permissions.toml is truth; grants are
`(principal, scope)`; loaded snapshot), 07_DATABASE Part XV F8
(corrupt/missing ⇒ fail closed: Kang-only mode).

This adapter parses grant TRUTH from the file — structural validation only.
The pairing lint (10 §2.6) is kernel policy over the scope vocabulary and
lives in kernel/permissions; it runs when the engine is built
(`kernel.permissions.engine.build_checked_engine`), because adapters must
not import the kernel (17 §4.3). The full load flow — parse here, lint +
build there — is composed at the composition root (M4); a pairing violation
there fails closed to KANG_ONLY_GRANTS with a banner (07 F8).
"""

from __future__ import annotations

import tomllib
from pathlib import Path

__all__ = ["KANG_ONLY_GRANTS", "GrantLoadError", "load_grants", "parse_grants"]

# The fail-closed grant set (07 F8): every non-Kang principal denied.
KANG_ONLY_GRANTS: dict[str, tuple[str, ...]] = {"kang": ("*",)}


class GrantLoadError(Exception):
    """permissions.toml is missing, unparseable, or fails pairing lints.
    The caller falls back to KANG_ONLY_GRANTS with a banner (07 F8)."""


def parse_grants(toml_text: str) -> dict[str, tuple[str, ...]]:
    """Parse and pairing-lint grant text. Raises GrantLoadError on malformed
    structure or a pairing violation."""
    try:
        data = tomllib.loads(toml_text)
    except tomllib.TOMLDecodeError as exc:
        raise GrantLoadError(f"permissions.toml is not valid TOML: {exc}") from exc
    raw = data.get("grants", {})
    if not isinstance(raw, dict):
        raise GrantLoadError("permissions.toml [grants] must be a table")
    grants: dict[str, tuple[str, ...]] = {}
    for principal, scopes in raw.items():
        if not isinstance(scopes, list) or not all(isinstance(s, str) for s in scopes):
            raise GrantLoadError(
                f"grants for {principal!r} must be a list of scope strings"
            )
        grants[principal] = tuple(scopes)
    return grants


def load_grants(path: Path) -> dict[str, tuple[str, ...]]:
    """Load grant truth from `path`. Raises GrantLoadError if the file is
    absent or invalid — the caller decides the fail-closed fallback (07 F8)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise GrantLoadError(f"permissions.toml unreadable at {path}: {exc}") from exc
    return parse_grants(text)
