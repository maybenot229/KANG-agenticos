"""invocation.list — the System-domain Invocations view (09_UI §12), added
2026-08-05.

The claim: the handler defaults/clamps `limit` per 12_API §15's standing
page limits (default 50, max 500), never lets a non-positive `limit`
defeat the bound (SQLite's `LIMIT -1`/`0` semantics would otherwise turn
"list fewer" into "list everything"), and returns rows in
`InvocationStore.recent()`'s newest-first contract without a `manifest`
field (that stays behind `explain.invocation`).
"""

from __future__ import annotations

from dataclasses import replace

from kang.adapters.fakes.api_stores import FakeInvocationStore
from kang.api.dispatch import HandlerContext
from kang.api.operations import make_invocation_list_handler
from kang.domain.ports.invocation import Invocation

CONTEXT = HandlerContext(
    principal="kang", correlation_id="corr-1", trigger="cli", first_party=True
)


def _invocation(n: int) -> Invocation:
    return Invocation(
        id=f"inv-{n}",
        correlation_id=f"corr-{n}",
        kind="command",
        operation="task.create",
        principal="kang",
        trigger="cli",
        started=f"2026-01-0{n}T00:00:00+00:00",
        finished=None,
        outcome=None,
    )


class TestInvocationList:
    def test_empty_store_lists_nothing(self):
        handler = make_invocation_list_handler(FakeInvocationStore())
        assert handler(CONTEXT, {}) == {"invocations": []}

    def test_default_limit_and_newest_first_ordering(self):
        store = FakeInvocationStore()
        for n in (1, 2, 3):
            store.start(_invocation(n))
        handler = make_invocation_list_handler(store)
        result = handler(CONTEXT, {})
        assert [inv["id"] for inv in result["invocations"]] == [
            "inv-3",
            "inv-2",
            "inv-1",
        ]

    def test_explicit_limit_is_respected(self):
        store = FakeInvocationStore()
        for n in (1, 2, 3):
            store.start(_invocation(n))
        handler = make_invocation_list_handler(store)
        result = handler(CONTEXT, {"limit": 1})
        assert [inv["id"] for inv in result["invocations"]] == ["inv-3"]

    def test_over_max_limit_clamps_rather_than_erroring(self):
        store = FakeInvocationStore()
        store.start(_invocation(1))
        handler = make_invocation_list_handler(store)
        result = handler(CONTEXT, {"limit": 10_000})
        assert [inv["id"] for inv in result["invocations"]] == ["inv-1"]

    def test_non_positive_limit_does_not_defeat_the_bound(self):
        # SQLite's LIMIT -1 (and, differently, LIMIT 0) are special — a
        # naive pass-through of a non-positive value must not turn into
        # "unlimited". The store's own recent() is called with a limit
        # clamped to at least 1, not the raw params value.
        store = FakeInvocationStore()
        for n in (1, 2, 3):
            store.start(_invocation(n))
        handler = make_invocation_list_handler(store)
        result = handler(CONTEXT, {"limit": -1})
        assert len(result["invocations"]) == 1

    def test_no_manifest_field_in_list_rows(self):
        store = FakeInvocationStore()
        store.start(replace(_invocation(1), manifest='{"ids": ["m-1"]}'))
        handler = make_invocation_list_handler(store)
        (row,) = handler(CONTEXT, {})["invocations"]
        assert "manifest" not in row
