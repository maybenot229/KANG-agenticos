"""DeadlineStore port-contract suite — fake and sqlite (13 §2.3).
Subclasses provide ``store``. The same suite runs against both so the fake
cannot drift from the real store (a fake that lies is a red build).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from kang.domain.ports.deadline_store import (
    Deadline,
    DeadlineNotFoundError,
    DeadlineRevisionConflictError,
)

CREATED = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)


def _deadline(
    index: int = 0,
    at: str = "2026-03-01T09:00:00+00:00",
    status: str = "tracked",
    kind: str = "custom",
) -> Deadline:
    return Deadline(
        id=f"dl-{index:04d}",
        kind=kind,
        title=f"deadline {index:04d}",
        at=at,
        status=status,
        lead_days=(14, 7, 3, 1),
        created_at=CREATED,
        updated_at=CREATED,
        device_id="device-test",
        revision=1,
    )


class DeadlineStoreContract:
    def test_create_then_get_roundtrips(self, store):
        deadline = _deadline(0)
        store.create(deadline)
        assert store.get(deadline.id) == deadline

    def test_get_unknown_raises(self, store):
        with pytest.raises(DeadlineNotFoundError):
            store.get("dl-none")

    def test_new_deadline_is_tracked(self, store):
        store.create(_deadline(0))
        assert store.get("dl-0000").status == "tracked"

    def test_lead_days_roundtrip_preserves_order(self, store):
        store.create(_deadline(0))
        assert store.get("dl-0000").lead_days == (14, 7, 3, 1)

    def test_update_bumps_revision_and_returns_snapshot(self, store):
        store.create(_deadline(0))
        loaded = store.get("dl-0000")
        committed = store.update(replace(loaded, status="alerted"))
        assert committed.revision == loaded.revision + 1
        assert committed.status == "alerted"
        assert store.get("dl-0000").revision == loaded.revision + 1

    def test_update_with_stale_revision_conflicts(self, store):
        store.create(_deadline(0))
        loaded = store.get("dl-0000")
        store.update(loaded)  # revision 1 -> 2
        with pytest.raises(DeadlineRevisionConflictError):
            store.update(loaded)  # still holding revision 1

    def test_update_unknown_raises_not_found(self, store):
        with pytest.raises(DeadlineNotFoundError):
            store.update(_deadline(9))

    def test_active_returns_only_tracked(self, store):
        store.create(_deadline(0))
        store.create(_deadline(1, status="met"))
        store.create(_deadline(2, status="cancelled"))
        assert [d.id for d in store.active()] == ["dl-0000"]

    def test_active_orders_by_at_then_id(self, store):
        store.create(_deadline(2, at="2026-05-01T09:00:00+00:00"))
        store.create(_deadline(0, at="2026-04-01T09:00:00+00:00"))
        store.create(_deadline(1, at="2026-04-01T09:00:00+00:00"))
        # soonest first; ties broken by id for a deterministic total order
        assert [d.id for d in store.active()] == ["dl-0000", "dl-0001", "dl-0002"]

    def test_delete_removes_the_row(self, store):
        store.create(_deadline(0))
        store.delete("dl-0000", deleted_by="kang")
        with pytest.raises(DeadlineNotFoundError):
            store.get("dl-0000")

    def test_delete_unknown_raises(self, store):
        with pytest.raises(DeadlineNotFoundError):
            store.delete("dl-none", deleted_by="kang")
