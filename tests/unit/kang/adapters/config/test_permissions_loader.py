"""permissions.toml loader (05 §8, 07 F8): parse, pairing-lint, fail closed."""

from __future__ import annotations

from pathlib import Path

import pytest

from kang.adapters.config.permissions_loader import (
    KANG_ONLY_GRANTS,
    GrantLoadError,
    load_grants,
    parse_grants,
)
from kang.kernel.permissions.engine import PermissionEngine, build_checked_engine

REPO_ROOT = Path(__file__).resolve().parents[5]


def test_parses_principal_scope_grants():
    grants = parse_grants(
        '[grants]\n"kang" = ["*"]\n"kernel:bus" = ["events.publish:kang"]\n'
    )
    assert grants["kang"] == ("*",)
    assert grants["kernel:bus"] == ("events.publish:kang",)


def test_malformed_toml_raises():
    with pytest.raises(GrantLoadError, match="valid TOML"):
        parse_grants("[grants\nbroken")


def test_non_list_scopes_raise():
    with pytest.raises(GrantLoadError, match="list of scope"):
        parse_grants('[grants]\n"agent:x" = "events.publish:kang"\n')


def test_parse_does_not_pairing_lint_that_is_kernel_policy():
    # The adapter parses structure only; pairing lint is kernel policy run
    # at engine build (adapters must not import the kernel — 17 §4.3). A
    # forbidden grant set parses here and is refused there (see
    # kernel/permissions test_engine::test_build_checked_engine_lints).
    grants = parse_grants('[grants]\n"agent:x" = ["*"]\n')
    assert grants["agent:x"] == ("*",)


def test_missing_file_raises_for_fallback():
    with pytest.raises(GrantLoadError, match="unreadable"):
        load_grants(Path("does-not-exist.toml"))


def test_kang_only_fallback_denies_non_kang():
    engine = PermissionEngine(KANG_ONLY_GRANTS)
    assert engine.allows("kang", "events.publish:kang")
    assert not engine.allows("kernel:bus", "events.publish:kang")


def test_shipped_default_loads_and_is_usable():
    grants = load_grants(REPO_ROOT / "config" / "defaults" / "permissions.toml")
    engine = build_checked_engine(grants)  # parse (adapter) + lint+build (kernel)
    engine.check("kang", "vault.write:anywhere")  # wildcard
    engine.check("kernel:bus", "events.publish:kang")
    assert not engine.allows("kernel:bus", "events.publish:plugin.x")
