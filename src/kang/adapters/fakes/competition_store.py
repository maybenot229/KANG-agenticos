"""FakeCompetitionStore — in-memory CompetitionStore, contract-paired
(13 §2.3).

Layer: adapters/fakes.
Constitutional home: 11_CODING §5/§7 (every port has an in-memory fake).
"""

from __future__ import annotations

from kang.domain.ports.competition_store import Competition

__all__ = ["FakeCompetitionStore"]


class FakeCompetitionStore:
    """CompetitionStore over a dict."""

    def __init__(self) -> None:
        self._competitions: dict[str, Competition] = {}

    def create(self, competition: Competition) -> None:
        if competition.id in self._competitions:
            raise ValueError(f"duplicate competition {competition.id}")
        self._competitions[competition.id] = competition

    def list_all(self) -> list[Competition]:
        return sorted(
            self._competitions.values(), key=lambda c: (c.name.casefold(), c.id)
        )
