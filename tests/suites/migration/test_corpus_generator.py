"""The synthetic corpus generator's own proofs (ADR-049 D3/D4; 07 Part XVI:
"deterministic seeds produce 1-/5-/10-year databases").

Placement: `tests/unit/` mirrors `src/`, and the generator is not `src/` code;
the generator's only consumers are the migration and performance suites, so
its proofs sit beside them. Every database is built under pytest's temp
directories — never inside the repository (PS-002).
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys

import pytest

from tests.fixtures.corpus import PROFILES, YEAR1, YEAR5, YEAR10, generate
from tests.fixtures.corpus.__main__ import main as corpus_main
from tests.fixtures.corpus.generate import REPO_ROOT

# 13 §2.17: a changed golden is a changed promise. Pinned 2026-09-21 for
# (YEAR1, seed=1, fraction=1.0). Any change to the generator's distributions,
# vocabulary, insertion order, or Random call sequence changes it — update it
# in the same commit as the change, and say why.
YEAR1_SEED1_ROOT_DIGEST = (
    "0374d36164e5a0c7ac85c1d4d3e8e4c93415ac0fb2bdeb9e597b81cdba904ae4"
)

# 06_MEMORY §13.1 bands: (low, high) per horizon.
BANDS = {
    "year1": {
        "memory_record": (2_000, 5_000),
        "episode": (3_000, 6_000),
        "vault_chunk": (20_000, 50_000),
        "link": (10_000, 30_000),
    },
    "year5": {
        "memory_record": (15_000, 30_000),
        "episode": (15_000, 30_000),
        "vault_chunk": (100_000, 250_000),
        "link": (80_000, 200_000),
    },
    "year10": {
        "memory_record": (30_000, 60_000),
        "episode": (30_000, 60_000),
        "vault_chunk": (200_000, 500_000),
        "link": (150_000, 400_000),
    },
}


@pytest.fixture
def db(corpus_year1):
    conn = sqlite3.connect(f"file:{corpus_year1.path}?mode=ro", uri=True)
    yield conn
    conn.close()


def _scalar(conn, sql):
    return conn.execute(sql).fetchone()[0]


# ------------------------------------------------------------- determinism


def test_same_inputs_produce_identical_digests(tmp_path):
    first = generate(YEAR1, tmp_path / "a.db", seed=7, fraction=0.03)
    second = generate(YEAR1, tmp_path / "b.db", seed=7, fraction=0.03)
    assert first.digests == second.digests
    assert first.root_digest == second.root_digest


def test_a_different_seed_produces_different_digests(tmp_path):
    first = generate(YEAR1, tmp_path / "a.db", seed=7, fraction=0.03)
    second = generate(YEAR1, tmp_path / "b.db", seed=8, fraction=0.03)
    assert first.root_digest != second.root_digest


def test_a_different_fraction_produces_different_digests(tmp_path):
    first = generate(YEAR1, tmp_path / "a.db", seed=7, fraction=0.03)
    second = generate(YEAR1, tmp_path / "b.db", seed=7, fraction=0.04)
    assert first.root_digest != second.root_digest


def test_year1_matches_its_pinned_golden(corpus_year1):
    assert corpus_year1.report.root_digest == YEAR1_SEED1_ROOT_DIGEST


# -------------------------------------------------------- 06 §13.1 scale bands


@pytest.mark.parametrize("profile", [YEAR1, YEAR5, YEAR10], ids=lambda p: p.name)
def test_every_profiles_headline_counts_sit_inside_their_band(profile):
    for table, (low, high) in BANDS[profile.name].items():
        target = {
            "memory_record": profile.memory_records,
            "episode": profile.episodes,
            "vault_chunk": profile.vault_chunks,
            "link": profile.links,
        }[table]
        assert low <= target <= high, f"{profile.name}.{table}={target}"


def test_year1_generated_counts_sit_inside_their_band(corpus_year1):
    for table, (low, high) in BANDS["year1"].items():
        actual = corpus_year1.report.counts[table]
        assert low <= actual <= high, f"year1.{table}={actual}"


def test_year1_headline_counts_are_exactly_the_profiles(corpus_year1):
    counts = corpus_year1.report.counts
    assert counts["memory_record"] == YEAR1.memory_records
    assert counts["episode"] == YEAR1.episodes
    assert counts["vault_chunk"] == YEAR1.vault_chunks
    assert counts["link"] == YEAR1.links


def test_chunk_token_estimates_land_in_06_5_3s_band(db):
    row = db.execute(
        "SELECT AVG(token_est), "
        "SUM(token_est BETWEEN 200 AND 400) * 1.0 / COUNT(*) FROM vault_chunk"
    ).fetchone()
    assert 200 <= row[0] <= 400
    assert row[1] >= 0.98  # a chunk's estimate is a plain len//4


# ------------------------------------------------------------ database health


def test_generated_database_is_structurally_sound(db):
    assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize(
    "fts", ["fts_memory", "fts_episode", "fts_chunk", "fts_message"]
)
def test_every_fts_index_is_consistent_with_its_content(corpus_year1, fts):
    # 'integrity-check' writes to the FTS shadow tables' check path only; open
    # a private read-write connection to a copy-free view of the file.
    conn = sqlite3.connect(corpus_year1.path)
    try:
        conn.execute(f"INSERT INTO {fts}({fts}) VALUES ('integrity-check')")
    finally:
        conn.close()


def test_the_corpus_is_not_inside_the_repository(corpus_year1):
    resolved = corpus_year1.path.resolve()
    assert REPO_ROOT not in resolved.parents


# ------------------------------------------------------------- invariants


def test_private_records_exist_and_never_reach_fts_memory(db):
    """Reads the FTS index's own doc table, not `fts_memory` itself: a MATCH-less
    scan of an external-content table reads the *content* table, so a join
    through `fts_memory` would count every record, indexed or not."""
    private = _scalar(
        db, "SELECT COUNT(*) FROM memory_record WHERE sensitivity = 'private'"
    )
    assert private > 0
    leaked = _scalar(
        db,
        "SELECT COUNT(*) FROM fts_memory_docsize d JOIN memory_record m "
        "ON m.rowid = d.id WHERE m.sensitivity = 'private'",
    )
    assert leaked == 0
    indexed = _scalar(db, "SELECT COUNT(*) FROM fts_memory_docsize")
    assert indexed == _scalar(db, "SELECT COUNT(*) FROM memory_record") - private


def test_private_rows_carry_fake_ciphertext_and_the_placeholder(db):
    bad = _scalar(
        db,
        "SELECT COUNT(*) FROM memory_record WHERE sensitivity = 'private' AND "
        "(content <> '[encrypted]' OR content_enc IS NULL "
        "OR length(content_enc) <> 64)",
    )
    assert bad == 0


def test_every_superseded_record_has_its_link_pair(db):
    assert (
        _scalar(db, "SELECT COUNT(*) FROM memory_record WHERE status = 'superseded'")
        > 0
    )
    missing = _scalar(
        db,
        "SELECT COUNT(*) FROM memory_record s "
        "WHERE s.status = 'superseded' AND NOT EXISTS ("
        " SELECT 1 FROM link a JOIN memory_record n ON n.id = a.dst_id "
        " WHERE a.src_id = s.id AND a.type = 'superseded_by' "
        " AND a.dst_kind = 'memory' "
        " AND n.status = 'active' AND n.type = s.type "
        " AND EXISTS (SELECT 1 FROM link b WHERE b.src_id = n.id AND b.dst_id = s.id "
        "             AND b.type = 'supersedes'))",
    )
    assert missing == 0


def test_every_lesson_derives_from_a_real_episode(db):
    assert _scalar(db, "SELECT COUNT(*) FROM memory_record WHERE type = 'lesson'") > 0
    missing = _scalar(
        db,
        "SELECT COUNT(*) FROM memory_record m WHERE m.type = 'lesson' AND NOT EXISTS ("
        " SELECT 1 FROM link l JOIN episode e ON e.id = l.dst_id "
        " WHERE l.src_id = m.id AND l.type = 'derived_from' "
        " AND l.dst_kind = 'episode')",
    )
    assert missing == 0


def test_link_endpoints_are_real_and_respect_their_kinds(db):
    checks = {
        "about_project": ("project", "id"),
        "about_competition": ("competition", "id"),
        "about_goal": ("goal", "id"),
        "from_conversation": ("conversation", "id"),
        "references_note": ("vault_note", "path"),
    }
    for ltype, (table, column) in checks.items():
        dangling = _scalar(
            db,
            f"SELECT COUNT(*) FROM link l WHERE l.type = '{ltype}' AND NOT EXISTS "
            f"(SELECT 1 FROM {table} t WHERE t.{column} = l.dst_id)",
        )
        assert dangling == 0, ltype
    wrong_person = _scalar(
        db,
        "SELECT COUNT(*) FROM link l WHERE l.type = 'about_person' AND NOT EXISTS "
        "(SELECT 1 FROM memory_record m WHERE m.id = l.dst_id "
        " AND m.type = 'relationship' "
        " AND l.dst_kind = 'memory')",
    )
    assert wrong_person == 0
    notes = _scalar(
        db,
        "SELECT COUNT(*) FROM link "
        "WHERE type = 'references_note' AND dst_kind <> 'note'",
    )
    assert notes == 0


def test_link_index_mirrors_every_link_and_adds_fk_edges(db):
    assert _scalar(
        db, "SELECT COUNT(*) FROM link_index WHERE origin = 'link'"
    ) == _scalar(db, "SELECT COUNT(*) FROM link")
    assert _scalar(db, "SELECT COUNT(*) FROM link_index WHERE origin = 'fk'") > 0
    assert _scalar(db, "SELECT COUNT(*) FROM link_index WHERE origin = 'wikilink'") == 0


def test_provenance_is_shape_correct_and_trust_consistent(db):
    expected = {"web": {0}, "observed": {1}, "rule": {1}, "stated": {2}, "vault": {2}}
    for kind, tiers in expected.items():
        found = {
            r[0]
            for r in db.execute(
                "SELECT DISTINCT trust_tier FROM memory_record WHERE source_kind = ?",
                (kind,),
            )
        }
        assert found <= tiers, kind
    assert (
        _scalar(
            db,
            "SELECT COUNT(*) FROM memory_record "
            "WHERE type IN ('rule','profile') AND trust_tier <> 2",
        )
        == 0
    )
    for kind, sql in {
        "web": "source_detail LIKE 'https://%'",
        "vault": "source_detail LIKE 'notes/%#%'",
        "rule": "source_detail LIKE 'rule:%'",
    }.items():
        bad = _scalar(
            db,
            "SELECT COUNT(*) FROM memory_record "
            f"WHERE source_kind = '{kind}' AND NOT ({sql})",
        )
        assert bad == 0, kind


def test_type_distribution_matches_the_documented_weights(db):
    counts = dict(db.execute("SELECT type, COUNT(*) FROM memory_record GROUP BY type"))
    assert counts["fact"] + counts["observation"] > sum(counts.values()) * 0.4
    for rare in ("rule", "profile"):
        assert counts[rare] < counts["fact"] / 3


def test_no_embedding_is_ever_set(db):
    for table in ("memory_record", "episode", "vault_chunk"):
        assert (
            _scalar(db, f"SELECT COUNT(*) FROM {table} WHERE embedding_ver IS NOT NULL")
            == 0
        )
    assert _scalar(db, "SELECT COUNT(*) FROM embedding_version") == 0


def test_queue_has_a_pending_majority_and_a_14_day_expiry(db):
    pending = _scalar(
        db, "SELECT COUNT(*) FROM memory_candidate_queue WHERE resolved IS NULL"
    )
    total = _scalar(db, "SELECT COUNT(*) FROM memory_candidate_queue")
    assert pending > total / 2
    assert 0 < total - pending
    off = _scalar(
        db,
        "SELECT COUNT(*) FROM memory_candidate_queue "
        "WHERE ROUND(julianday(expires_at) - julianday(proposed_at), 3) <> 14.0",
    )
    assert off == 0


def test_a_small_second_device_minority_exists(db):
    devices = dict(
        db.execute("SELECT device_id, COUNT(*) FROM memory_record GROUP BY 1")
    )
    assert len(devices) == 2
    share = min(devices.values()) / sum(devices.values())
    assert 0.02 <= share <= 0.10


def test_change_capture_ran_during_generation(db):
    assert _scalar(
        db, "SELECT COUNT(*) FROM change_log WHERE entity = 'memory_record'"
    ) == (_scalar(db, "SELECT COUNT(*) FROM memory_record"))
    assert _scalar(
        db, "SELECT COUNT(*) FROM change_log WHERE entity = 'link'"
    ) == _scalar(db, "SELECT COUNT(*) FROM link")


def test_revisions_never_hold_private_plaintext(db):
    leaked = _scalar(
        db,
        "SELECT COUNT(*) FROM memory_revision r JOIN memory_record m "
        "ON m.id = r.record_id "
        "WHERE m.sensitivity = 'private'",
    )
    assert leaked == 0


# ---------------------------------------------------- PS-002 / entry point


def test_main_refuses_a_path_inside_the_repository(capsys):
    target = REPO_ROOT / "corpus-must-not-exist.db"
    assert corpus_main(["year1", str(target), "--fraction", "0.01"]) == 2
    assert not target.exists()
    assert "PS-002" in capsys.readouterr().err


def test_generate_refuses_a_path_inside_the_repository():
    with pytest.raises(ValueError, match="PS-002"):
        generate(YEAR1, REPO_ROOT / "corpus-must-not-exist.db", seed=1, fraction=0.01)


def test_generate_refuses_to_overwrite(tmp_path):
    target = tmp_path / "exists.db"
    target.write_bytes(b"")
    with pytest.raises(FileExistsError):
        generate(YEAR1, target, seed=1, fraction=0.01)


def test_the_command_line_entry_point_prints_a_json_report(tmp_path):
    out = tmp_path / "cli.db"
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "tests.fixtures.corpus",
            "year1",
            str(out),
            "--seed",
            "3",
            "--fraction",
            "0.02",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    report = json.loads(done.stdout)
    assert report["profile"] == "year1"
    assert report["counts"]["memory_record"] == round(YEAR1.memory_records * 0.02)
    assert out.exists() and set(PROFILES) == {"year1", "year5", "year10"}
