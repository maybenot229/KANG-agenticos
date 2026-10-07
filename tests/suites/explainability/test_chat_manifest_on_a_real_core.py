"""A real chat turn carries its context manifest (ADR-058 D5; 05 §3 phase 3;
13 §2.16 "assemblies without manifests are impossible"): through a real
Core and the real dispatcher, `chat.send` writes the manifest onto its own
invocation row — the row `explain.invocation` returns — before the model is
called. The test home ships no `providers.toml`, so the model is unreachable
and the turn degrades: proof that the manifest exists even then.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.invocation_store import SqliteInvocationStore
from kang.api.dispatch import ApiRequest
from kang.kernel.runtime.composition import build_core

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def core(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    for name in ("memory.toml", "permissions.toml"):
        (config / name).write_text(
            (REPO_ROOT / "config" / "defaults" / name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    built = build_core(tmp_path)
    yield built, tmp_path
    built.close()


def _call(core, token, operation, params):
    return core.dispatcher.dispatch(
        ApiRequest(operation, params, token, idempotency_key=core.new_id())
    )


def _save(core, token, content, **extra):
    params = dict(
        type="fact",
        content=content,
        trust_tier=2,
        source_kind="stated",
        source_detail="conversation",
        reason="Kang said so",
    )
    params.update(extra)
    response = _call(core, token, "memory.propose", params)
    assert response["ok"] is True, response
    return response["result"]["id"]


def test_a_degraded_chat_turn_still_records_a_content_free_manifest(core):
    built, home = core
    token = built.mint_first_party_session().token
    rule = _save(built, token, "Never book anything before nine", type="rule")
    fact = _save(built, token, "The robotics team meets on Fridays")
    _save(built, token, "School term ends in June")

    sent = _call(built, token, "chat.send", {"message": "when does robotics meet?"})
    assert sent["ok"] is True, sent
    assert sent["result"]["degraded"] is True  # no provider in this home

    conn = open_connection(home / "kang.db")
    try:
        row = SqliteInvocationStore(conn).by_correlation(sent["correlation_id"])
    finally:
        conn.close()
    manifest = json.loads(row.manifest)
    assert manifest["agent"] == "chat"
    assert manifest["recipe"] == {"id": "chat-general", "version": 1}
    assert manifest["refused"] is None
    assert [e["id"] for e in manifest["standing"]] == [rule]
    assert [e["id"] for e in manifest["relevance"]] == [fact]
    assert manifest["semantic"] == "unavailable"
    assert "Fridays" not in row.manifest and "robotics meet" not in row.manifest
