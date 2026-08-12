"""FakeHeldActionStore — in-memory HeldActionStore, contract-paired (13 §2.3).

Layer: adapters/fakes.
Constitutional home: 11_CODING §5/§7 (every port has an in-memory fake).
"""

from __future__ import annotations

from dataclasses import replace

from kang.domain.ports.held_action import (
    HeldAction,
    HeldActionExpired,
    HeldActionNotFound,
)

__all__ = ["FakeHeldActionStore"]


class FakeHeldActionStore:
    """HeldActionStore over a dict, mirroring the transition guards."""

    def __init__(self) -> None:
        self._actions: dict[str, HeldAction] = {}

    def create(self, held_action: HeldAction) -> None:
        if held_action.id in self._actions:
            raise ValueError(f"duplicate held action {held_action.id}")
        self._actions[held_action.id] = held_action

    def get(self, held_action_id: str) -> HeldAction:
        try:
            return self._actions[held_action_id]
        except KeyError:
            raise HeldActionNotFound(held_action_id) from None

    def approve(self, held_action_id: str, now: str) -> HeldAction:
        return self.approve_in_txn(held_action_id, now)

    def approve_in_txn(self, held_action_id: str, now: str) -> HeldAction:
        # No real transaction concept for an in-memory dict — approve() and
        # approve_in_txn() are identical here; the distinction only matters
        # for the real adapter's shared-connection transaction (ADR-021).
        current = self.get(held_action_id)
        if current.status != "pending":
            raise HeldActionNotFound(f"{held_action_id} is {current.status}")
        if now >= current.expires_at:
            raise HeldActionExpired(held_action_id)
        return self._set_status(held_action_id, "approved")

    def cancel(self, held_action_id: str) -> HeldAction:
        current = self.get(held_action_id)
        if current.status != "pending":
            raise HeldActionNotFound(f"{held_action_id} is {current.status}")
        return self._set_status(held_action_id, "cancelled")

    def mark_executed(self, held_action_id: str) -> HeldAction:
        return self.mark_executed_in_txn(held_action_id)

    def mark_executed_in_txn(self, held_action_id: str) -> HeldAction:
        current = self.get(held_action_id)
        if current.status != "approved":
            raise HeldActionNotFound(f"{held_action_id} is {current.status}")
        return self._set_status(held_action_id, "executed")

    def approved_not_executed(self) -> list[HeldAction]:
        return sorted(
            (a for a in self._actions.values() if a.status == "approved"),
            key=lambda a: (a.created_at, a.id),
        )

    def expire_due(self, now: str) -> int:
        expired = 0
        for held_action_id, action in list(self._actions.items()):
            if action.status == "pending" and now > action.expires_at:
                self._actions[held_action_id] = replace(action, status="cancelled")
                expired += 1
        return expired

    def pending(self) -> list[HeldAction]:
        return sorted(
            (a for a in self._actions.values() if a.status == "pending"),
            key=lambda a: (a.created_at, a.id),
        )

    def _set_status(self, held_action_id: str, status: str) -> HeldAction:
        updated = replace(self._actions[held_action_id], status=status)
        self._actions[held_action_id] = updated
        return updated
