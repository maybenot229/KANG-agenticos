"""In-memory API stores — invocation, idempotency, session (13 §2.3).

Layer: adapters/fakes.
Constitutional home: 11_CODING §5/§7 (every port has an in-memory fake).
Grouped in one module: they are the small API-layer state ports, exercised
together by the API dispatch tests.
"""

from __future__ import annotations

from dataclasses import replace

from kang.domain.ports.invocation import Invocation, InvocationNotFound
from kang.domain.ports.session import Session, SessionInvalid

__all__ = ["FakeIdempotencyStore", "FakeInvocationStore", "FakeSessionStore"]


class FakeInvocationStore:
    def __init__(self) -> None:
        self._by_id: dict[str, Invocation] = {}

    def start(self, invocation: Invocation) -> None:
        self._by_id[invocation.id] = invocation

    def finish(self, invocation_id: str, outcome: str, finished: str) -> None:
        self._by_id[invocation_id] = replace(
            self._by_id[invocation_id], outcome=outcome, finished=finished
        )

    def by_correlation(self, correlation_id: str) -> Invocation:
        for invocation in self._by_id.values():
            if invocation.correlation_id == correlation_id:
                return invocation
        raise InvocationNotFound(correlation_id)

    def recent(self, limit: int) -> list[Invocation]:
        ordered = sorted(
            self._by_id.values(), key=lambda inv: (inv.started, inv.id), reverse=True
        )
        return ordered[:limit]


class FakeIdempotencyStore:
    def __init__(self) -> None:
        self._by_key: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._by_key.get(key)

    def put(self, key: str, outcome_json: str, at: str) -> None:
        self._by_key.setdefault(key, outcome_json)  # first write wins

    def purge_before(self, cutoff: str) -> int:
        return 0  # the fake keeps everything; retention is the sqlite store's job


class FakeSessionStore:
    def __init__(self) -> None:
        self._by_token: dict[str, Session] = {}

    def create(self, session: Session) -> None:
        self._by_token[session.token] = session

    def resolve(self, token: str) -> Session:
        try:
            return self._by_token[token]
        except KeyError:
            raise SessionInvalid("no live session for the presented token") from None
