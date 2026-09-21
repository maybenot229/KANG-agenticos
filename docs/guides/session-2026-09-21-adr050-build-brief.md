# Build brief — implementing ADR-050 (CI tier membership)

**Written:** 2026-09-21, by the session that drafted ADR-050.
**For:** the coding session that implements it.
**Precondition — check before touching anything:** `docs/adr/050-ci-tier-membership.md` must say `**Status:** accepted`. If it still says `proposed`, stop, say so, and end your turn.
**Non-normative** (17 §12). ADR beats brief; a numbered document beats the ADR except where the ADR's "Affected documents" line names the amendment. A third disagreement: stop and surface it.

---

## 0. What you are building

A small, mechanical slice: make the CI cadence vocabulary one mechanism, register it, select on it, add the one test that keeps it honest, and land four dated document amendments. **No test moves directory. No test changes cadence. No new suite directory. No Weekly or Monthly CI job.** Expect the full suite to come out at exactly the same count and outcome as it goes in — if it does not, you changed behavior and something is wrong.

## 1. Read first, in this order

1. `CLAUDE.md` (repo root) — §8, §9.
2. `docs/adr/050-ci-tier-membership.md` — D1–D5. D5 is what you must not do.
3. `docs/adr/049-synthetic-corpus-generator.md` — D3 (the table you correct) and its Verification paragraph (the finding that produced this ADR).
4. `docs/13_TESTING.md` §3 (the tier table) and §4 (gate 1).
5. `docs/17_PROJECT_STRUCTURE.md` §11.1, §11.2 (the sentence you amend), §16/PS-006.
6. `docs/03_ROADMAP.md` §8 (the RESERVED registry you add two rows to).
7. `.github/workflows/ci.yml`, `pyproject.toml` `[tool.pytest.ini_options]`.
8. `tests/suites/performance/test_budgets_on_corpus.py:36` and `tests/suites/migration/test_chain_on_corpus.py:30` — the two existing marker forms; both stay exactly as they are.
9. `tests/suites/CLAIMS.md`.

## 2. The changes

**`pyproject.toml`** — register all three markers, keeping `--strict-markers`:
```
markers = [
  "nightly: ...",
  "weekly: ...   (RESERVED — no CI job yet, ADR-050 D3)",
  "monthly: ...  (RESERVED — no CI job yet, ADR-050 D3)",
]
```
Each description cites ADR-050 D1. Registering is vocabulary, not a tier (D3).

**`.github/workflows/ci.yml`** — selection exactly per D1's table. The commit and merge jobs currently deselect only `nightly`; they must deselect all three, so a future `weekly`-marked test cannot silently run on every push. The `nightly` job is unchanged. Do **not** add a weekly or monthly job. Keep the file's existing comment style and cite ADR-050 D1 where you change a line.

**The one new test** (D1's honesty guard): every registered cadence marker is either selected by a CI job or listed as RESERVED. Put it in `tests/suites/architecture/` — it is a structural claim about the repo, which is that directory's job (13 §2.1). It should parse `pyproject.toml`'s marker list and `ci.yml`, and fail if a registered cadence marker is neither named in a job's `-m` expression nor in the RESERVED set the test declares with its ADR citation. Keep it simple: a YAML/TOML read and a set comparison, no regex archaeology. This test is itself unmarked, so it runs at the commit tier.

**Four dated document amendments, same commit:**
- `17_PROJECT_STRUCTURE.md` §11.2 — amend the sentence per D1 ("the tree states what is proven **and how expensive it is**; CI states when"), dated, citing ADR-050. Bump "Last updated".
- `13_TESTING.md` §3 — move "migration chain on corpus" from the Weekly row to the Nightly row, with the D2 reason in a dated note under the table.
- `13_TESTING.md` §4 gate 1 — the dated qualifier per D3 (all tiers **that exist**; the Weekly clause activates with the weekly tier).
- `docs/adr/049-synthetic-corpus-generator.md` — a dated "Corrected by ADR-050" note on D3's table only (its tier column said "merge (integration)"; `year1` runs at the commit tier). **Touch nothing else in ADR-049**, including its Verification section.
- `docs/03_ROADMAP.md` §8 — two RESERVED rows (Weekly CI tier, Monthly CI tier), trigger: the first test carrying the corresponding marker.

**`docs/adr/INDEX.md`** — 050's row to `accepted — implemented (date)`.
**`tests/suites/CLAIMS.md`** — one line for the new marker-coverage test.
**`docs/adr/050-ci-tier-membership.md`** — append to Verification only.

## 3. Verification protocol

1. `ruff format --check .` first, then `ruff check .`, `lint-imports --config tools/importlinter.toml`, `python tools/lint_sizes.py`, `python tools/lint_banned_patterns.py`, `python tools/lint_tree_hygiene.py`, `python tools/lint_doc_citations.py`, `python tools/build_root_docs.py --check`.
2. `pytest tests/unit tests/suites -m "not (nightly or weekly or monthly)" -q` and `pytest tests/integration -m "not (nightly or weekly or monthly)" -q`. Expected: **875 and 324** — that is 874 + your one new test, and integration unchanged. Any other number means you changed something you should not have; stop and find out what.
3. `pytest -m nightly -q` — expected 15 passed, unchanged. You do not need to re-measure the budgets; say in your report that you ran it and it was green, and do not restate timings you did not take.
4. `pytest -m weekly -q` and `pytest -m monthly -q` — expected: no tests collected, exit code 5. Confirm that is what happens, since it is the state D3 asserts.
5. Prove the marker-coverage test actually bites: temporarily register a fourth marker, confirm the new test goes red, remove it. Report that you did this (13 §1's red-test discipline).
6. Never touch the real `%KANG_HOME%`. This slice has no reason to.

## 4. Commit

One commit on `main`, local, never pushed, in `git log`'s established style: what changed, what was found, what is proven, what is deferred (D5). End with the attribution line your session's system reminder gives you. Do not accept, reopen, or re-decide any ADR.

## 5. Known traps

- The commit and merge jobs deselecting only `nightly` is the actual bug this slice fixes; it is easy to edit `ci.yml`'s nightly job and forget the other two.
- `pytest -m weekly` with no matching tests exits **5** ("no tests collected"), not 0. If you wire a weekly job later that would be a red build — which is one more reason D3 does not create one now.
- `--strict-markers` only validates markers that are *used*; it does not require registered markers to be used. That asymmetry is why the new test exists.
- ADR-049's D3 table is inside an accepted ADR. You are adding a dated correction note beside it, not editing the table's claim out of history.
- Do not "fix" the two existing marker forms into one style. Both are sanctioned by D1, and the parametrized form is the one future corpus-scaled suites need.
