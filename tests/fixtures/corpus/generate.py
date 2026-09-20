"""The synthetic corpus generator (ADR-049; 07_DATABASE Part XVI, "the single
most valuable test asset in the project").

`generate(profile, out_path, seed=..., fraction=...)` builds a fresh kang.db
at HEAD through the real migration harness (`open_connection` +
`apply_migrations` — the code `Core`'s own startup runs), then fills it with a
seeded, deterministic population by raw parameterized SQL in <=1,000-row
transactions. Change-capture and FTS triggers stay ON: `change_log` fills
itself and `fts_*` index as they would in life, so the corpus does not lie
about size or trigger cost.

It is a schema-level asset (D6): rows are placed in the states 06 allows, not
driven through the write gate or the lifecycle. Determinism is per
(profile, seed, fraction): per-table digests over rows in key order — never
file bytes, which SQLite does not promise.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from random import Random

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.migrations import apply_migrations

from ._ctx import Ctx
from ._links import generate_links
from ._memory import generate_episodes, generate_memory, generate_vault
from ._structured import (
    generate_conversations,
    generate_structured,
    generate_tombstones,
)
from .profiles import Profile
from .text import Vocabulary

__all__ = ["CorpusReport", "REPO_ROOT", "generate", "table_digest"]

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "migrations"

# table -> ORDER BY key (rows are digested in key order, never insertion order)
DIGEST_TABLES = {
    "goal": "id",
    "project": "id",
    "competition": "id",
    "milestone": "id",
    "task": "id",
    "deadline": "id",
    "conversation": "id",
    "message": "id",
    "vault_note": "path",
    "vault_chunk": "id",
    "memory_record": "id",
    "memory_revision": "record_id, revision",
    "memory_candidate_queue": "id",
    "episode": "id",
    "link": "id",
    "link_index": "src, dst, type, origin",
    "tombstone": "id",
    "change_log": "seq",
}


@dataclass(frozen=True)
class CorpusReport:
    profile: str
    seed: int
    fraction: float
    counts: dict[str, int]
    digests: dict[str, str]

    @property
    def root_digest(self) -> str:
        joined = "".join(f"{t}={d}\n" for t, d in sorted(self.digests.items()))
        return hashlib.sha256(joined.encode()).hexdigest()

    def to_json(self) -> str:
        return json.dumps(
            {
                "profile": self.profile,
                "seed": self.seed,
                "fraction": self.fraction,
                "counts": self.counts,
                "digests": self.digests,
                "root_digest": self.root_digest,
            },
            indent=2,
            sort_keys=True,
        )


def table_digest(conn: sqlite3.Connection, table: str, order: str | None = None) -> str:
    """sha256 over every row of `table`, selected in key order."""
    key = order or DIGEST_TABLES[table]
    digest = hashlib.sha256()
    for row in conn.execute(f"SELECT * FROM {table} ORDER BY {key}"):
        digest.update(repr(row).encode())
    return digest.hexdigest()


def assert_outside_repo(path: Path) -> Path:
    """PS-002: no .db artifact inside the repository, ever."""
    resolved = path.resolve()
    if resolved == REPO_ROOT or REPO_ROOT in resolved.parents:
        raise ValueError(
            f"refusing to write a corpus inside the repository ({resolved}): "
            "PS-002 — generated databases live only in a temp or external path"
        )
    return resolved


def generate(
    profile: Profile,
    out_path: Path | str,
    *,
    seed: int,
    fraction: float = 1.0,
    clock: FakeClock | None = None,
) -> CorpusReport:
    target = assert_outside_repo(Path(out_path))
    if target.exists():
        raise FileExistsError(f"{target} already exists; the corpus is built fresh")
    scaled = profile.scaled(fraction)
    rng = Random(seed)
    conn = open_connection(target)
    try:
        # A disposable asset: durability buys nothing; fsyncs would cost minutes.
        conn.execute("PRAGMA synchronous = OFF")
        apply_migrations(conn, MIGRATIONS_DIR, clock or FakeClock())
        ctx = Ctx(conn=conn, rng=rng, vocab=Vocabulary(rng), profile=scaled)
        generate_structured(ctx)
        generate_conversations(ctx)
        generate_vault(ctx)
        generate_memory(ctx)
        generate_episodes(ctx)
        generate_links(ctx)
        generate_tombstones(ctx)
        counts = {
            t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in DIGEST_TABLES
        }
        digests = {t: table_digest(conn, t) for t in DIGEST_TABLES}
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()
    return CorpusReport(scaled.name, seed, fraction, counts, digests)
