"""Registry skeleton: empty, deterministic, JSON-servable (12 §16)."""

from __future__ import annotations

import json

from kang.api.registry import registry_json, registry_snapshot


def test_registries_are_empty_at_m0():
    snapshot = registry_snapshot()
    assert snapshot["operations"] == []
    assert snapshot["event_types"] == []
    assert snapshot["error_codes"] == []
    assert snapshot["contract_version"] == 1


def test_registry_serves_as_json():
    parsed = json.loads(registry_json())
    assert parsed == registry_snapshot()


def test_registry_json_is_byte_stable():
    assert registry_json() == registry_json()
