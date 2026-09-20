"""Synthetic text for the corpus generator (ADR-049 D1).

Every word here is written into this file: generic English words, a short
domain list of generic nouns, and pseudo-words assembled from fixed
syllables so the vocabulary has a realistic long tail (rare terms exist,
so an FTS query for one matches few rows). Nothing is read from any file,
and nothing is drawn from Kang's vault (14 §14.5) — the text is obviously
synthetic by construction.

Constitutional home: 07_DATABASE Part XVI (synthetic corpus), ADR-049 D1.
"""

from __future__ import annotations

from random import Random

__all__ = ["Vocabulary", "chunk_text", "estimate_tokens"]

_COMMON = (
    "the of and to in is that it for as with was on be by this at from or "
    "an are not but have had has they you we she he which their there when "
    "what will would could should about after before because between during "
    "under over again further then once here where why how all any both each "
    "few more most other some such only own same so than too very can just "
    "into through above below up down out off while until against among "
    "small large early late first last next new old good better best long "
    "short high low quick slow simple hard clear plain careful steady quiet "
    "bright open closed near far whole part half full empty first second "
    "third often rarely always never sometimes usually mostly nearly barely "
    "make take give find keep leave bring begin finish start stop change "
    "move turn read write check plan review choose decide learn teach build "
    "test fix send receive record note list count measure compare order "
    "day week month year hour minute morning evening night today tomorrow "
    "yesterday season term summer winter spring autumn monday friday sunday "
    "person team group friend mentor teacher student parent leader member "
    "place room desk table window door road bridge garden library station "
    "thing idea point reason result problem answer question detail example "
    "story letter message page paper sheet number figure chart diagram "
    "water light stone metal wood glass paper cloth thread rope wheel "
    "engine circuit sensor signal battery motor switch wire panel screen "
    "energy budget cost price value rate level range limit margin target"
).split()

_DOMAIN = (
    "competition deadline olympiad report lecture repository sermon tuition "
    "project milestone submission registration syllabus exam quiz revision "
    "essay proposal prototype workshop seminar internship scholarship "
    "checklist schedule agenda timetable assignment coursework rubric "
    "portfolio challenge tournament league bracket round entry judge "
    "mentor coach reading passage chapter lesson tutorial notebook journal "
    "reflection summary retrospective decision priority habit routine"
).split()

_SYL_A = (
    "ba be bi bo bu ka ke ki ko ku la le li lo lu ma me mi mo mu na ne ni no nu".split()
)
_SYL_B = (
    "ra re ri ro ru sa se si so su ta te ti to tu va ve vi vo vu za ze zi zo zu".split()
)
_SYL_C = "n l r s m k th x d p".split()


def estimate_tokens(text: str) -> int:
    """A plain len//4 estimate (roughly four characters per token). It is an
    estimate, not a tokenizer — it only has to land in 06 §5.3's 200-400
    band for chunk-sized text."""
    return len(text) // 4


class Vocabulary:
    """A seeded sentence pool. Built once per generation from the run's own
    `Random`, so the pool (and everything sampled from it) is a pure function
    of the seed."""

    def __init__(self, rng: Random, sentences: int = 6000) -> None:
        self._tail = self._build_tail()
        self._pool = [self._sentence(rng) for _ in range(sentences)]

    @staticmethod
    def _build_tail() -> list[str]:
        return [a + b + c for a in _SYL_A for b in _SYL_B for c in _SYL_C]

    def _word(self, rng: Random) -> str:
        roll = rng.random()
        if roll < 0.62:
            # Skewed toward the head of the list: a few very common words.
            skew = rng.random()
            return _COMMON[int(len(_COMMON) * skew * skew)]
        if roll < 0.88:
            return _DOMAIN[rng.randrange(len(_DOMAIN))]
        return self._tail[rng.randrange(len(self._tail))]

    def _sentence(self, rng: Random) -> str:
        words = [self._word(rng) for _ in range(rng.randint(7, 15))]
        return words[0].capitalize() + " " + " ".join(words[1:]) + "."

    def sentence(self, rng: Random) -> str:
        return self._pool[rng.randrange(len(self._pool))]

    def sentences(self, rng: Random, count: int) -> str:
        pool = self._pool
        size = len(pool)
        return " ".join(pool[rng.randrange(size)] for _ in range(count))

    def title(self, rng: Random) -> str:
        words = [self._word(rng) for _ in range(rng.randint(2, 5))]
        return " ".join(words).capitalize()

    @property
    def domain_words(self) -> tuple[str, ...]:
        return tuple(_DOMAIN)


def chunk_text(vocab: Vocabulary, rng: Random) -> str:
    """One vault chunk: 15-19 sentences of ~70 characters, i.e. a token_est
    of ~200-400 (06 §5.3; the generator's own test asserts the band)."""
    return vocab.sentences(rng, rng.randint(15, 19))
