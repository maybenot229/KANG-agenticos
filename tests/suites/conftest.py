"""Session-scoped synthetic corpora for the suites that consume them
(ADR-049 D1): `suites/migration/` and `suites/performance/`.

Lives here rather than in `tests/fixtures/corpus/` because pytest discovers a
conftest only along the path of the tests that use it — `tests/suites/` is the
common ancestor of both consumers. Every database is generated under pytest's
`tmp_path_factory`, never inside the repository (PS-002); a corpus is built
only when a test requests it, so the commit tier never pays for `year10`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.fixtures.corpus import YEAR1, YEAR10, CorpusReport, Profile, generate

CORPUS_SEED = 1


@dataclass(frozen=True)
class Corpus:
    path: Path
    report: CorpusReport


def _build(factory: pytest.TempPathFactory, profile: Profile) -> Corpus:
    path = factory.mktemp(profile.name) / "kang.db"
    return Corpus(path, generate(profile, path, seed=CORPUS_SEED))


@pytest.fixture(scope="session")
def corpus_year1(tmp_path_factory: pytest.TempPathFactory) -> Corpus:
    return _build(tmp_path_factory, YEAR1)


@pytest.fixture(scope="session")
def corpus_year10(tmp_path_factory: pytest.TempPathFactory) -> Corpus:
    return _build(tmp_path_factory, YEAR10)
