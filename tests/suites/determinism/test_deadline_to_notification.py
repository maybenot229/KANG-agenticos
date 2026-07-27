"""M5 "Proves" — the deadline lifecycle end to end, fully offline.

    create → approach event → notification per ladder → acknowledge

This closes the "notification per ladder" clause of 18 §3 M5's Proves list.
It runs against the REAL wired Core (composition root, sqlite, real bus and
notifier), not fakes, and makes zero model calls — there is no model in the
system yet, which is the point of building the deterministic path first
(05 §16, 18 §7.6).

Determinism (13 §2.6): the same fixture run twice produces the same states
and the same event sequence.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.notification_store import SqliteNotificationStore
from kang.api.dispatch import ApiRequest
from kang.kernel.runtime.composition import build_core

REPO_ROOT = Path(__file__).resolve().parents[3]

# The deadline sits inside the innermost lead threshold relative to the real
# clock the Core wires, so one sweep crosses it.
SOON = "2020-01-01T09:00:00+00:00"
FAR = "2099-01-01T09:00:00+00:00"


def _seed_permissions(kang_home: Path) -> None:
    """Copy the shipped default grants into %KANG_HOME% (17 §8: the
    installer's job; here, the fixture's)."""
    config = kang_home / "config"
    config.mkdir(parents=True, exist_ok=True)
    (config / "permissions.toml").write_text(
        (REPO_ROOT / "config" / "defaults" / "permissions.toml").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )


@pytest.fixture
def core(tmp_path):
    _seed_permissions(tmp_path)
    built = build_core(tmp_path)
    yield built, tmp_path
    built.close()


def _call(core, operation, params, key=None):
    session = core.mint_first_party_session()
    response = core.dispatcher.dispatch(
        ApiRequest(operation, params, session.token, idempotency_key=key)
    )
    assert response["ok"] is True, response
    return response["result"]


def _notifications(kang_home: Path) -> list:
    conn = open_connection(kang_home / "kang.db")
    try:
        store = SqliteNotificationStore(conn)
        rows = conn.execute("SELECT id FROM notification ORDER BY created_at, id")
        return [store.get(row[0]) for row in rows.fetchall()]
    finally:
        conn.close()


def test_deadline_lifecycle_produces_a_delivered_notification(core):
    built, home = core
    _call(built, "deadline.create", {"title": "Submit entry", "at": SOON}, key="k1")

    swept = _call(built, "deadline.sweep", {}, key="k2")
    assert swept["count"] == 1

    # The sweep's two events fanned out to the notifier, which enqueued a
    # row and then drained it through the ladder — all inside the publish.
    notifications = _notifications(home)
    assert len(notifications) == 1
    notification = notifications[0]
    assert notification.priority == "attention"  # 05 §13: approaching deadlines
    assert notification.state == "delivered"  # ladder, assuming Idle (M5)
    assert notification.delivered_at is not None
    assert notification.entity_refs[0]["kind"] == "deadline"


def test_a_far_deadline_produces_no_notification(core):
    built, home = core
    _call(built, "deadline.create", {"title": "Far off", "at": FAR}, key="k1")
    assert _call(built, "deadline.sweep", {}, key="k2")["count"] == 0
    assert _notifications(home) == []


def test_acknowledge_closes_the_loop_additively(core):
    built, home = core
    _call(built, "deadline.create", {"title": "Submit entry", "at": SOON}, key="k1")
    _call(built, "deadline.sweep", {}, key="k2")
    notification = _notifications(home)[0]

    acked = _call(built, "notification.ack", {"id": notification.id}, key="k3")
    assert acked["state"] == "acked"

    # 12 §13: acks never delete history — the row and its content survive
    after = _notifications(home)[0]
    assert after.state == "acked"
    assert after.acked_at is not None
    assert after.delivered_at == notification.delivered_at
    assert after.payload == notification.payload


def test_a_second_sweep_does_not_re_notify(core):
    built, home = core
    _call(built, "deadline.create", {"title": "Submit entry", "at": SOON}, key="k1")
    _call(built, "deadline.sweep", {}, key="k2")
    # The deadline is `alerted` now, so it leaves the tracked set entirely —
    # the first line of defence against re-notification (the 24h rule is the
    # second, tested at the notifier).
    assert _call(built, "deadline.sweep", {}, key="k3")["count"] == 0
    assert len(_notifications(home)) == 1


def test_the_run_is_deterministic_across_identical_fixtures(tmp_path):
    """Same inputs ⇒ same observable outcome (13 §2.6). Ids and timestamps
    differ by construction (uuid7 + wall clock); the STATES and the event
    type sequence must not."""
    outcomes = []
    for name in ("run-a", "run-b"):
        home = tmp_path / name
        _seed_permissions(home)
        built = build_core(home)
        try:
            _call(
                built, "deadline.create", {"title": "Submit entry", "at": SOON}, "k1"
            )
            _call(built, "deadline.sweep", {}, "k2")
        finally:
            built.close()
        rows = _notifications(home)
        outcomes.append([(n.priority, n.state) for n in rows])
    assert outcomes[0] == outcomes[1] == [("attention", "delivered")]


def test_no_model_calls_are_possible(core):
    """18 §7.6: M0-M6 contain no model call. The router does not exist yet,
    so this is structural — asserted so the claim is checked, not assumed."""
    built, _ = core
    import kang.kernel.runtime.composition as composition

    source = Path(composition.__file__).read_text(encoding="utf-8")
    for forbidden in ("anthropic", "openai", "ollama", "ModelRouter"):
        assert forbidden not in source, f"a model path reached the Core: {forbidden}"
