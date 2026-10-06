"""06 §5.2's scorer (ADR-056 D2). 13 §2.2 requires property-based tests for
scoring math: these sweep a deterministic grid of generated candidates
(SHA-256-derived, no RNG — 11 §14) and assert the properties the formula
promises, plus exact values for each term."""

from __future__ import annotations

import hashlib
import math
from datetime import datetime, timedelta, timezone

import pytest

from kang.domain.memory.retrieval import RetrievalCandidate, score_candidates
from kang.domain.ports.memory_config import ScoringConfig, ScoringWeights
from kang.domain.ports.memory_store import MEMORY_TYPES

NOW = datetime(2026, 10, 6, tzinfo=timezone.utc)
WEIGHTS = ScoringWeights(0.40, 0.20, 0.15, 0.15, 0.10)
HALF_LIVES = {t: 0.0 for t in MEMORY_TYPES} | {"fact": 180.0, "observation": 30.0}
CONFIG = ScoringConfig(WEIGHTS, HALF_LIVES, match_min_similarity=0.5)


def cand(record_id="m", **overrides) -> RetrievalCandidate:
    base = dict(
        record_id=record_id,
        type="fact",
        updated_at=NOW,
        importance=0.5,
        pinned=False,
        distance=None,
        bm25=None,
    )
    base.update(overrides)
    return RetrievalCandidate(**base)


def _unit(seed: str) -> float:
    return int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def generated(n: int = 200) -> list[RetrievalCandidate]:
    out = []
    for i in range(n):
        u = [_unit(f"{i}:{k}") for k in range(6)]
        out.append(
            cand(
                record_id=f"r{i:03d}",
                type=MEMORY_TYPES[int(u[0] * len(MEMORY_TYPES)) % len(MEMORY_TYPES)],
                updated_at=NOW - timedelta(days=u[1] * 1000),
                importance=u[2],
                pinned=u[3] > 0.9,
                distance=None if u[4] < 0.2 else u[4] * 2,
                bm25=None if u[5] < 0.3 else -u[5] * 20,
            )
        )
    return out


def test_every_score_lies_within_zero_and_the_weight_sum():
    for s in score_candidates(generated(), NOW, CONFIG):
        assert 0.0 <= s.score <= sum(vars(WEIGHTS).values()) + 1e-12
        for term in vars(s.terms).values():
            assert 0.0 <= term <= 1.0


def test_the_score_is_exactly_the_weighted_sum_of_its_terms():
    for s in score_candidates(generated(), NOW, CONFIG):
        t = s.terms
        expected = (
            WEIGHTS.semantic * t.semantic
            + WEIGHTS.lexical * t.lexical
            + WEIGHTS.recency * t.recency
            + WEIGHTS.importance * t.importance
            + WEIGHTS.context * t.context
        )
        assert s.score == pytest.approx(expected)


def test_ranking_is_deterministic_and_ties_break_by_id():
    first = score_candidates(generated(), NOW, CONFIG)
    again = score_candidates(list(reversed(generated())), NOW, CONFIG)
    assert first == again
    tied = score_candidates([cand("b"), cand("a"), cand("c")], NOW, CONFIG)
    assert [s.record_id for s in tied] == ["a", "b", "c"]


def test_closer_vectors_never_score_lower_all_else_equal():
    for distance in (0.0, 0.2, 0.5, 0.9, 1.4, 2.0):
        near = cand("near", distance=distance)
        far = cand("far", distance=min(2.0, distance + 0.1))
        scores = {
            s.record_id: s.score for s in score_candidates([near, far], NOW, CONFIG)
        }
        assert scores["near"] >= scores["far"]


def test_pinning_sets_importance_to_one():
    (s,) = score_candidates([cand(pinned=True, importance=0.1)], NOW, CONFIG)
    assert s.terms.importance == 1.0


def test_a_zero_half_life_never_decays_and_a_half_life_halves():
    old = NOW - timedelta(days=180)
    (lesson,) = score_candidates([cand(type="lesson", updated_at=old)], NOW, CONFIG)
    (fact,) = score_candidates([cand(type="fact", updated_at=old)], NOW, CONFIG)
    assert lesson.terms.recency == 1.0
    assert fact.terms.recency == pytest.approx(0.5)


def test_bm25_is_min_max_normalized_with_the_best_at_one():
    scored = score_candidates(
        [cand("best", bm25=-9.0), cand("mid", bm25=-5.0), cand("worst", bm25=-1.0)],
        NOW,
        CONFIG,
    )
    lexical = {s.record_id: s.terms.lexical for s in scored}
    assert lexical == {"best": 1.0, "mid": pytest.approx(0.5), "worst": 0.0}
    (only,) = score_candidates([cand(bm25=-3.0)], NOW, CONFIG)
    assert only.terms.lexical == 1.0


def test_similarity_is_one_minus_cosine_distance_clamped():
    sims = {
        d: score_candidates([cand(distance=d)], NOW, CONFIG)[0].terms.semantic
        for d in (0.0, 0.25, 1.0, 1.7)
    }
    assert sims == {0.0: 1.0, 0.25: 0.75, 1.0: 0.0, 1.7: 0.0}


def test_a_match_needs_a_lexical_hit_or_enough_similarity():
    scored = {
        s.record_id: s.is_match
        for s in score_candidates(
            [
                cand("lexical", bm25=-1.0, distance=1.9),
                cand("close", distance=0.4),
                cand("vague", distance=0.6),
                cand("nothing"),
            ],
            NOW,
            CONFIG,
        )
    }
    assert scored == {"lexical": True, "close": True, "vague": False, "nothing": False}


def test_without_semantics_only_lexical_hits_match_and_similarity_weighs_nothing():
    scored = {
        s.record_id: s
        for s in score_candidates(
            [cand("close", distance=0.0), cand("hit", bm25=-1.0)],
            NOW,
            CONFIG,
            use_semantic=False,
        )
    }
    assert not scored["close"].is_match and scored["hit"].is_match
    assert scored["close"].terms.semantic == 1.0  # reported, not weighted
    assert scored["close"].score == pytest.approx(
        WEIGHTS.recency * 1.0 + WEIGHTS.importance * 0.5
    )


def test_recency_matches_the_formula_exactly():
    days = 45.0
    (s,) = score_candidates(
        [cand(type="observation", updated_at=NOW - timedelta(days=days))], NOW, CONFIG
    )
    assert s.terms.recency == pytest.approx(math.exp(-math.log(2) * days / 30.0))
