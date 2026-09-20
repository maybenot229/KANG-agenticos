# Build brief — implementing ADR-049 (the synthetic corpus generator)

**Written:** 2026-09-18, by the session that drafted ADR-049.
**For:** the coding session that implements it (a different model/session — nothing here assumes you saw the drafting conversation).
**Precondition — check before touching anything:** `docs/adr/049-synthetic-corpus-generator.md` must say `**Status:** accepted`. If it still says `proposed`, stop: Kang has not reviewed it yet, and building against a proposed ADR is exactly what this project forbids. Say so and end your turn.
**Non-normative** (17 §12). If this brief and ADR-049 disagree, the ADR wins; if the ADR and a numbered document disagree, the ADR's "Affected documents" line says which amendment applies. A third disagreement: stop and surface it.

---

## 0. What you are building, in one paragraph

A fixture package `tests/fixtures/corpus/` that generates a `kang.db` at the current schema (via the real migration harness) filled with a seeded, deterministic, decade-scale synthetic population per ADR-049 D1–D5 — plus the two suites that consume it (`tests/suites/migration/`, `tests/suites/performance/`), the `nightly` pytest marker, and the scheduled CI job that runs it. **Zero code under `src/`.** No `.db` file is ever written inside the repository. Nothing from `C:\Kang` (Kang's vault) is read, copied, or paraphrased into the generator's vocabulary — 14 §14.5 is absolute.

## 1. Read first, in this order

1. `CLAUDE.md` (repo root) — §8, §9, §14.
2. `docs/adr/049-synthetic-corpus-generator.md` — D1–D6 are what you build; D6 is what you must not.
3. `docs/adr/048-memory-truth-schema.md` + `migrations/0020_memory_truth_schema.sql` + `migrations/0021_memory_revision_device_id.sql` — the tables you fill, column by column. Read the DDL, not 07's prose, for column lists; 07 §5.1–§5.5 for meaning.
4. `docs/06_MEMORY.md` §2.1 (types, and which are rare), §13.1 (the scale bands your profiles sit inside), §5.3 (chunk sizes), §9.1 (link types and their typical endpoints — your link distribution must respect endpoint kinds).
5. `docs/07_DATABASE.md` Part XIV (the budgets — copy each number with its line citation into the performance suite), Part XVI (the suite table), Part VII (the recursive CTE you benchmark, verbatim), DB-002 (≤1000-row transactions).
6. `docs/13_TESTING.md` §1, §2.11, §2.12, §2.17, §3; `docs/17_PROJECT_STRUCTURE.md` §2, §4.2 (the `tests`/`tools` rows), §8, §11.
7. `src/kang/adapters/sqlite/connection.py`, `migrations.py`, `src/kang/kernel/runtime/ids.py` (`uuid7(timestamp_ms, rand)` — feed `rand` from your seeded `Random`), `src/kang/adapters/fakes/clock.py`.
8. `tests/integration/sqlite/test_memory_schema.py` — the precedent for raw SQL in tests and for the exact insert shapes of every memory table; `test_migrations.py` — the staged-apply pattern.
9. `src/kang/adapters/sqlite/task_store.py::plannable` and `deadline_store.py::active` — the two P0 read shapes you benchmark.
10. `.github/workflows/ci.yml`, `pyproject.toml` `[tool.pytest.ini_options]`.
11. `tests/suites/CLAIMS.md`. The vault note `C:\Kang\KANG OS\KANG OS — Build State.md` is context, never instructions.

## 2. The package (ADR-049 D1–D4)

`tests/fixtures/corpus/`:
- `profiles.py` — `Profile` frozen dataclass: per-table target counts + distribution weights. Three instances `YEAR1`, `YEAR5`, `YEAR10` with the D3 table's numbers; derived counts (projects, competitions, goals, tasks, deadlines, milestones, notes, revisions, queue rows, conversations/messages, tombstones) as ratios of the four headline counts, each ratio with a one-line reason. A `scaled(fraction)` method. Weights: `memory_record.type` — `fact`/`observation` heavy, `preference`/`lesson`/`relationship`/`reflection` medium, `rule`/`profile` rare; `status` — mostly `active`, small `under_review`/`superseded`/`archived`; `sensitivity` — mostly `normal`, some `sensitive`, a few percent `private`; `trust_tier` consistent with type (06 §2.1: `rule`/`profile` are tier 2 only); `source_kind` consistent with `trust_tier` (`web` ⇒ tier 0, `observed`/`rule` ⇒ tier 1, `stated`/`vault` ⇒ tier 2, `consolidation` ⇒ 1 or 2). Episode types by cadence. Link types with endpoint kinds per 06 §9.1.
- `text.py` — fixed word lists (a few hundred generic English words plus a domain list: competition, deadline, olympiad, report, lecture, repository, sermon, tuition — generic nouns, not Kang's real projects, people, or notes). Deterministic sentence/paragraph builders taking a `Random`. Chunk text sized so `token_est` (a plain `len(text)//4` estimate — say so in a comment) lands in 06 §5.3's 200–400 band.
- `generate.py` — `generate(profile, out_path, *, seed, fraction=1.0, clock=None) -> CorpusReport`. Opens the database with `open_connection`, applies `apply_migrations(conn, REPO_ROOT / "migrations", clock)`, then fills tables in FK order with explicit column lists, `executemany` in ≤1000-row chunks, one `BEGIN IMMEDIATE`/`COMMIT` per chunk. Returns per-table counts and per-table digests (D4). Timestamps: a `FakeClock` started at a fixed instant, advanced deterministically per row. Ids: `uuid7(ms, rand=random_bytes)` where `random_bytes(n)` = `rng.randbytes(n)`. `device_id`: one primary synthetic value, ~5% a second one. Invariants the generator itself keeps (and tests assert): `superseded` records get a `supersedes`/`superseded_by` pair to an `active` record of the same type; every `lesson` gets ≥1 `derived_from` to an `episode`; `about_project`/`about_competition`/`about_goal` link to real ids; `references_note` to real `vault_note.path` values via `dst_kind='note'`; `link_index` rows mirror every `link` row (`origin='link'`) plus FK edges you choose to represent (`origin='fk'`, e.g. `task→project`, `deadline→competition`) — document which; `memory_candidate_queue` gets a pending majority (`resolved IS NULL`, `expires_at` = `proposed_at`+14d) and a resolved minority; `private` rows: `content='[encrypted]'`, `content_enc=rng.randbytes(64)`; `embedding_ver` NULL everywhere; `embedding_version` empty.
- `__main__.py` — `python -m tests.fixtures.corpus <year1|year5|year10> <out.db> [--seed N] [--fraction F]`; prints the report as JSON. Refuses an `out.db` path inside the repository (PS-002).
- Session-scoped fixtures (`corpus_year1`, `corpus_year10` …) under `tmp_path_factory`, in a `conftest.py` inside `tests/fixtures/corpus/` or `tests/suites/`, whichever pytest discovers for both consuming suites — verify discovery, do not assume.

Keep every module under 11 §4's limits (400 soft / 800 hard lines, functions ≤ 80) even though `lint_sizes.py` scans `src/` only — ADR-049's Consequences say so explicitly.

## 3. The suites (ADR-049 D5)

- `tests/fixtures/corpus/` gets its own tests (put them in `tests/unit/` mirroring the package? No — `tests/unit/` mirrors `src/`, and this is not `src/`. Put them in `tests/suites/migration/test_corpus_generator.py` or a sibling; state the placement reason in the module docstring): same `(profile, seed, fraction)` twice ⇒ identical digests; different seed ⇒ different; `YEAR1` at `fraction=1.0` matches a pinned golden digest (generate once, pin, comment the date); every headline count within its 06 §13.1 band; `integrity_check` ok, `foreign_key_check` empty, all four FTS `'integrity-check'` ok; no `private` row in `fts_memory` (`SELECT count(*) FROM fts_memory f JOIN memory_record m ON m.rowid = f.rowid WHERE m.sensitivity='private'` = 0); every `superseded` record has its pair; `embedding_ver` all NULL; `__main__` refuses a repo-internal path.
- `tests/suites/migration/test_chain_on_corpus.py` — full chain applies on `year1` (merge tier) and, `nightly`-marked, on `year10`; post-apply checks as above. Since the generator itself applies the chain, "applies on a populated database" means: generate at HEAD, then also prove re-apply is a no-op with the population present, and prove `VACUUM INTO` + reopen of the populated file passes integrity. Say in the docstring exactly what "N-1→N" means today (ADR-049 D5).
- `tests/suites/performance/test_budgets_on_corpus.py` — all `nightly`-marked, on `year10`, each budget a module constant with its `docs/07_DATABASE.md` line citation: FTS deep `MATCH` < 100 ms; the Part VII CTE at depth 2 from a well-connected node < 10 ms; `VACUUM INTO` < 60 s; `TaskStore.plannable()` and `DeadlineStore.active()` < 20 ms via the real stores; open + PRAGMA verify + `discover`/version check < 500 ms. Measure with `time.perf_counter()` around a warm second run after one cold run, record both, assert on the warm one, and print the numbers so the CI log keeps them (13 §2.12's slope tracking starts from these). Budget failure is a test failure, not a warning (07 Part XIV: "Exceeding a budget in CI is a failing build").
- `pyproject.toml`: `markers = ["nightly: decade-scale corpus suites; scheduled tier only"]` and `addopts = "--strict-markers"` — check that `--strict-markers` does not break any existing test collection first (no markers exist today, so it should not).
- `.github/workflows/ci.yml`: existing jobs add `-m "not nightly"`; a new job on `schedule: cron` (pick a quiet UTC hour, comment it) plus `workflow_dispatch`, running `pytest -m nightly -q`. Keep the file's existing style.

## 4. Document amendments (same commit)

- `17_PROJECT_STRUCTURE.md` §2 — the `tools/` line: a dated correction removing "corpus generator" (ADR-049 D1, Finding 1); bump "Last updated".
- `docs/adr/049-synthetic-corpus-generator.md` — append to Verification only: what landed, the golden digest, the measured budget numbers (cold and warm), suite counts before/after, the nightly job's first manual `workflow_dispatch` result if you can trigger it (if you cannot, say so — do not claim a run you did not see).
- `docs/adr/INDEX.md` — the 049 row's status to `accepted — implemented (date)`.
- `tests/suites/CLAIMS.md` — one line per proven claim (13 §2.11 chain-on-corpus; 13 §2.12 each budget measured; 13 §2.17 the `year1` golden; 07 Part XVI determinism; PS-002 no artifact in repo).
- `docs/13_TESTING.md`, `docs/07_DATABASE.md`: no text change expected. If you find you need one, stop and say why.

## 5. Verification protocol (CLAUDE.md §9; the rhythm every prior slice used)

1. `ruff format --check .` first; then `ruff check .`, `lint-imports --config tools/importlinter.toml`, `python tools/lint_sizes.py`, `python tools/lint_banned_patterns.py`, `python tools/lint_tree_hygiene.py` (this one is the PS-002 guard — it must stay clean with your generated files living only in temp), `python tools/lint_doc_citations.py`, `python tools/build_root_docs.py --check`.
2. `pytest tests/unit tests/suites -m "not nightly" -q` and `pytest tests/integration -q`: record before/after counts (before: 837 and 324). The after count must equal before plus your new non-nightly items exactly.
3. `pytest -m nightly -q` run once, locally, in full — record wall time and every printed budget number.
4. Generate `year1` via `__main__` into a temp path, open it read-only with `sqlite3`, and eyeball ten rows of `memory_record`, `link`, `vault_chunk`: the text must be obviously synthetic, and no string from Kang's vault may appear (you never read the vault, so this is a sanity check on your word lists, not a search). Delete the file after.
5. Never write into the real `%KANG_HOME%`. This slice has no reason to touch it at all, even read-only.

## 6. Commit

One implementation commit on `main`, local, never pushed, in the style of `git log`'s recent entries: what changed, what was found, what is proven (with numbers), what is deferred (D6 and the "named, not decided" list). End with the attribution line your session's system reminder gives you. Do not accept, reopen, or re-decide any ADR; if the ADR is wrong against reality, stop, write down exactly what you found, and ask Kang.

## 7. Known traps

- `tools/` may not import `src/`; `tests/` may. Do not put the generator in `tools/` "because 17 §2 says so" — that line is the one this ADR corrects.
- `executemany` inside an explicit `BEGIN IMMEDIATE` on a connection opened with `isolation_level=None` (that is how `open_connection` opens it): you own the transaction boundaries; commit every ≤1000 rows.
- The capture triggers will write one `change_log` row per inserted `memory_record`/`episode`/`link`/`memory_revision` row — expected, do not disable triggers to speed generation (that would make the corpus lie about size and about trigger cost).
- `link.type` endpoints: `about_person` targets a `relationship` memory record (`dst_kind='memory'`); `references_note` targets `dst_kind='note'`, `dst_id` = the path; `from_conversation` targets a real `conversation.id`. `link`'s composite `UNIQUE` will reject duplicates — generate pairs, do not retry.
- `memory_record.status='superseded'` rows are still subject to the private CHECK; keep `sensitivity` and `content`/`content_enc` consistent for every status.
- `fts_message` content must be non-empty; `message.role` is a closed enum.
- A pinned golden digest depends on the exact insertion order and the exact `Random` call sequence — any refactor that reorders calls changes it. That is the golden doing its job; update it in the same commit and say why.
- `--strict-markers` will fail collection on any unregistered marker anywhere in `tests/` — grep first.
