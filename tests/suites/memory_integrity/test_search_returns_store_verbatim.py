"""`memory.search` through a real Core (ADR-056): 13 §2.8's no-fabrication
claim — "retrieval returns store-verbatim content + ids" — and the channel
rule that memory content is shown to Kang alone (first-party only).

The test home ships no `providers.toml`, so the semantic half has no
provider: every search here is the declared lexical degradation (A9), which
is also what proves that a missing embedding runtime never breaks search.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kang.adapters.sqlite.connection import open_connection
from kang.api.dispatch import ApiRequest
from kang.domain.ports.session import Session
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


def _save(core, token, content):
    response = _call(
        core,
        token,
        "memory.propose",
        dict(
            type="fact",
            content=content,
            trust_tier=2,
            source_kind="stated",
            source_detail="conversation",
            reason="Kang said so",
        ),
    )
    assert response["ok"] is True, response
    return response["result"]["id"]


def test_every_result_is_the_stored_row_verbatim(core):
    built, home = core
    token = built.mint_first_party_session().token
    saved = {
        _save(built, token, "Dr Lee mentors the robotics team"),
        _save(built, token, "The robotics submission is due in March"),
        _save(built, token, "School term ends in June"),
    }
    response = _call(built, token, "memory.search", {"query": "robotics"})
    assert response["ok"] is True, response
    result = response["result"]
    assert result["degraded"] == "semantic_unavailable"
    assert len(result["results"]) == 2 and result["nearest_misses"] == []

    conn = open_connection(home / "kang.db")
    try:
        for hit in result["results"]:
            assert hit["id"] in saved
            stored = conn.execute(
                "SELECT content, type, trust_tier, source_kind, source_detail, "
                "created_at, updated_at FROM memory_record WHERE id = ?",
                (hit["id"],),
            ).fetchone()
            assert stored == (
                hit["content"],
                hit["type"],
                hit["trust_tier"],
                hit["source_kind"],
                hit["source_detail"],
                hit["created_at"],
                hit["updated_at"],
            )
    finally:
        conn.close()


def test_a_search_with_no_match_says_so_and_is_never_padded(core):
    built, _ = core
    token = built.mint_first_party_session().token
    _save(built, token, "School term ends in June")
    result = _call(built, token, "memory.search", {"query": "zebra"})["result"]
    assert result["results"] == []


@pytest.mark.parametrize("principal", ["agent:memory_steward", "kernel:scheduler"])
def test_no_non_first_party_session_can_search(core, principal):
    built, _ = core
    token = built.new_id()
    built.sessions.create(Session(token, principal, False, ""))
    response = _call(built, token, "memory.search", {"query": "anything"})
    assert response["ok"] is False
    assert response["error"]["code"] in ("first_party_required", "permission_denied")
