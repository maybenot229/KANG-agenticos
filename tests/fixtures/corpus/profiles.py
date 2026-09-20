"""Corpus profiles: per-table target counts and distribution weights
(ADR-049 D3).

Headline counts are the midpoints of 06_MEMORY §13.1's bands (1 / 5 / 10
years). Every other count is a fixed ratio of the headline counts, each with
its one-line reason below. Weights are starting hypotheses in the sense
06 Appendix A uses the phrase: structure is the commitment, constants are
tunable — and tuning them changes the pinned year1 golden, deliberately.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

__all__ = ["PROFILES", "YEAR1", "YEAR5", "YEAR10", "Profile"]


@dataclass(frozen=True)
class Profile:
    name: str
    years: int
    memory_records: int  # 06 §13.1 midpoint for this horizon
    episodes: int  # 06 §13.1 midpoint
    vault_chunks: int  # 06 §13.1 midpoint
    links: int  # 06 §13.1 midpoint

    # ---- derived counts (fixed ratios; the reason is the comment) ----

    @property
    def projects(self) -> int:  # ~one project per 300 durable memories
        return max(3, round(self.memory_records / 300))

    @property
    def goals(self) -> int:  # 07 §5.2 goals are few; ~one per four projects
        return max(3, self.projects // 4)

    @property
    def competitions(self) -> int:  # Kang enters fewer competitions than projects
        return max(2, round(self.projects * 0.6))

    @property
    def milestones(self) -> int:  # ~four milestones per project
        return self.projects * 4

    @property
    def tasks(self) -> int:  # ~one task per eight memories
        return max(20, self.memory_records // 8)

    @property
    def deadlines(self) -> int:  # ~one deadline per five tasks
        return max(10, self.tasks // 5)

    @property
    def notes(self) -> int:  # ~ten 200-400-token chunks per note
        return max(1, self.vault_chunks // 10)

    @property
    def revisions(self) -> int:  # edits are rare (06 §8.2): ~15% of records
        return self.memory_records * 15 // 100

    @property
    def queue_rows(self) -> int:  # ~one proposal per ten records, mostly pending
        return self.memory_records // 10

    @property
    def conversations(self) -> int:  # ~one chat per twenty memories
        return max(2, self.memory_records // 20)

    @property
    def messages(self) -> int:  # six turns per chat
        return self.conversations * 6

    @property
    def tombstones(self) -> int:  # ~2% of records were deleted at some point
        return self.memory_records // 50

    @property
    def span_days(self) -> int:
        return self.years * 365

    def scaled(self, fraction: float) -> "Profile":
        """Scale every headline count; derived counts follow. The
        determinism contract holds per (profile, seed, fraction)."""
        if not 0 < fraction <= 1:
            raise ValueError("fraction must be in (0, 1]")
        if fraction == 1:
            return self
        return replace(
            self,
            memory_records=max(1, round(self.memory_records * fraction)),
            episodes=max(1, round(self.episodes * fraction)),
            vault_chunks=max(1, round(self.vault_chunks * fraction)),
            links=max(1, round(self.links * fraction)),
        )


YEAR1 = Profile("year1", 1, 3_500, 4_500, 35_000, 20_000)
YEAR5 = Profile("year5", 5, 22_000, 22_000, 175_000, 140_000)
YEAR10 = Profile("year10", 10, 45_000, 45_000, 350_000, 275_000)
PROFILES = {p.name: p for p in (YEAR1, YEAR5, YEAR10)}

# ---- distribution weights (value, weight) ----

# 06 §2.1A: fact/observation dominate; rule/profile are rare (only Kang writes them).
MEMORY_TYPES = (
    ("fact", 28),
    ("observation", 22),
    ("preference", 10),
    ("lesson", 10),
    ("relationship", 9),
    ("reflection", 9),
    ("rule", 6),
    ("profile", 6),
)
# Trust tier by type (06 §2.1A): rule/profile are tier 2 only.
TRUST_BY_TYPE = {
    "fact": ((2, 60), (1, 30), (0, 10)),
    "observation": ((1, 85), (0, 15)),
    "preference": ((2, 70), (1, 30)),
    "lesson": ((1, 50), (2, 50)),
    "relationship": ((2, 100),),
    "reflection": ((2, 100),),
    "rule": ((2, 100),),
    "profile": ((2, 100),),
}
# source_kind consistent with trust_tier (web=0; observed/rule=1; stated/vault=2).
SOURCE_BY_TIER = {
    0: (("web", 100),),
    1: (("observed", 50), ("rule", 30), ("consolidation", 20)),
    2: (("stated", 65), ("vault", 25), ("consolidation", 10)),
}
STATUSES = (("active", 86), ("under_review", 5), ("superseded", 5), ("archived", 4))
SENSITIVITIES = (("normal", 90), ("sensitive", 7), ("private", 3))
# Episode cadence (06 §2.1B): plans daily, reviews weekly, retrospectives per project.
EPISODE_TYPES = (
    ("plan", 55),
    ("review", 20),
    ("session", 12),
    ("decision", 8),
    ("retrospective", 5),
)
EPISODE_STATUSES = (("active", 85), ("compressed", 10), ("archived", 5))
# Filler links beyond the invariant-mandated ones, with endpoint kinds (06 §9.1).
FILLER_LINKS = (
    ("relates_to", 40),
    ("about_project", 15),
    ("references_note", 12),
    ("evidence_for", 8),
    ("evidence_against", 4),
    ("about_competition", 5),
    ("about_goal", 4),
    ("from_conversation", 6),
    ("about_person", 6),
)
LINK_STATUSES = (("active", 94), ("broken", 3), ("retired", 3))
PROJECT_STATUSES = (
    ("active", 30),
    ("completed", 40),
    ("archived", 15),
    ("paused", 8),
    ("abandoned", 7),
)
TASK_STATUSES = (
    ("done", 70),
    ("open", 12),
    ("scheduled", 6),
    ("dropped", 7),
    ("deferred", 5),
)
DEADLINE_STATUSES = (
    ("met", 45),
    ("tracked", 15),
    ("missed", 8),
    ("alerted", 7),
    ("cancelled", 25),
)
SECOND_DEVICE_SHARE = 0.05  # D4: a small second-device minority
