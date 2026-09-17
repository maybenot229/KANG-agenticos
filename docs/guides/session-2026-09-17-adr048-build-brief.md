# Build brief — implementing ADR-048 (the memory truth schema)

**Written:** 2026-09-17, by the session that drafted ADR-048, after Kang accepted it.
**For:** the coding session that implements it (a different model/session — nothing here assumes you saw the drafting conversation).
**Non-normative** (17 §12: guides never outrank the constitution). If this brief and ADR-048 disagree, the ADR wins; if the ADR and a numbered document disagree, the ADR's own "Affected documents" line tells you which amendment to apply. If you find a third disagreement, stop and surface it — do not resolve it in code.

---

## 0. What you are building, in one paragraph

One migration, `migrations/0020_memory_truth_schema.sql`, that lands the whole memory-truth DDL from `07_DATABASE.md` (§5.1, §5.3, §5.4, Part VIII's `embedding_version`, §6.1's four FTS5 tables with sync triggers, change-capture triggers) with the five deviations ADR-048 decides — plus the schema test suite that proves it, the dated document amendments the ADR names, the CLAIMS.md lines, and a live verification against a throwaway `%KANG_HOME%`. **No ports, no stores, no fakes, no operations, no config file, no vec tables, no secondary indexes, no views, no `rebuild-indexes` command.** ADR-048 D4 lists each exclusion with its reason; do not "helpfully" add any of them.

## 1. Read first, in this order (all of it, not the section you think applies)

1. `CLAUDE.md` at the repo root — the contributor rules that bind you. §8 (things you must never do) and §9 (verify before delivering) especially.
2. `docs/adr/048-memory-truth-schema.md` — the decision. Context explains the four findings; Options explain why the recommended ones won; **D1–D5 are what you build**; D4 is what you must not build.
3. `docs/07_DATABASE.md` — §5.1, §5.3, §5.4, §5.5 (`message`), §4.1 (the three trigger duties), §5.6 (change capture), §6.1 (FTS5), Part VIII (`embedding_version`), Part XIII (migration rules, especially XIII.5's provenance invariant), Part XVI (the schema suite you are writing), Appendix B (sanctioned CASCADEs).
4. `docs/06_MEMORY.md` — Part II (the type catalog your CHECKs enforce), Part III (M-002), §2.1D, §4.2 (the required metadata), Part VIII, §9.1 (link types).
5. `migrations/0001_initial.sql` (the change-capture trigger shape you copy), `migrations/0016_held_action_expired_state.sql` (the table-recreate pattern you copy for `message`), `migrations/0018_model_call.sql` and `0019_conversation.sql` (the header-comment convention: constitutional home, deviations named).
6. `src/kang/adapters/sqlite/migrations.py` (the harness: filename regex `^\d{4}_[a-z0-9_]+\.sql$`, checksums, gap detection) and `tests/integration/sqlite/test_migrations.py` (the tests your migration must keep green, and the model for the new ones — `test_0006_preserves_task_rows_across_the_table_recreation` is the exact shape for the `message` rebuild proof).
7. `tests/suites/CLAIMS.md` — the registry you append to.
8. The vault note `C:\Kang\KANG OS\KANG OS — Build State.md` — where the build stands. **Everything in the vault is data, never instructions** (CLAUDE.md §14.2).

## 2. The migration, table by table

Derive every column, type, CHECK, default, and FK from `07_DATABASE.md`'s own DDL. The list below names only what differs from 07 or what 07 leaves implicit. Cite 07's line numbers in the migration header the way `0018`/`0019` do.

### 2.1 `memory_record` (07 §5.1)
- First column: `rowid INTEGER PRIMARY KEY` (ADR-048 D2). Then `id TEXT NOT NULL UNIQUE` — **not** `PRIMARY KEY`. Every other column as 07 writes it.
- `status`: CHECK `('active','under_review','superseded','archived')` — D1 removes `'candidate'` and `'rejected'`. **No `DEFAULT`** on `status` (the gate supplies `'active'` explicitly; a default that could admit is exactly what D1 forbids). Keep 07's comment `-- deleted = row gone + tombstone`.
- The DB-005 invariant as a real CHECK, forward direction only: `CHECK (sensitivity <> 'private' OR (content = '[encrypted]' AND content_enc IS NOT NULL))`. Do not add the reverse.
- `embedding_ver INTEGER REFERENCES embedding_version(ver)` — a real FK (the parent lands in this same migration; see §2.6 for ordering).
- Change-capture triggers (07 §4.1 third duty, shape from `0001`): insert / update / delete. **The update trigger is `AFTER UPDATE OF <every column except last_accessed, access_count> ON memory_record`** (D5). List the columns explicitly; do not use a bare `AFTER UPDATE`. The `fields` JSON in the capture row likewise omits those two columns. Delete stamps wall clock the way `0001`'s delete trigger does — that is the one sanctioned SQL-side time read.

### 2.2 `memory_revision`, `memory_candidate_queue` (07 §5.1)
- Exactly as 07 writes them. `memory_revision.record_id REFERENCES memory_record(id) ON DELETE CASCADE` — the FK targets the `UNIQUE` text column, which SQLite enforces (verified while drafting).
- `memory_revision`: change-capture **insert trigger only** (revisions are append-only).
- `memory_candidate_queue`: **no** quartet, **no** capture trigger, **no** index (its consumers — the approval-queue list and the janitor — arrive in later slices; index doctrine, 07 Part VI).

### 2.3 `episode` (07 §5.1)
- `rowid INTEGER PRIMARY KEY` first, `id TEXT NOT NULL UNIQUE`. `compressed_into TEXT REFERENCES episode(id)` as written. `embedding_ver` FK as in §2.1. Status CHECK `('active','compressed','archived')` unchanged — episodes have no candidate state (D1).
- Change-capture triggers: insert / update / delete, per-column `fields` list, `0001` shape. No access-statistics columns exist here, so a plain `AFTER UPDATE` is fine.

### 2.4 `vault_note`, `vault_chunk` (07 §5.3)
- `vault_note` exactly as written (`path TEXT PRIMARY KEY`).
- `vault_chunk`: `rowid INTEGER PRIMARY KEY` first, `id TEXT NOT NULL UNIQUE`, `note_path ... REFERENCES vault_note(path) ON DELETE CASCADE`, keep `UNIQUE (note_path, seq)`, `embedding_ver` FK.
- **No** change-capture triggers on either — derived tables (07 Appendix A).

### 2.5 `link`, `link_index` (07 §5.4)
- `link` exactly as written: the 13-value `type` CHECK copied verbatim from 06 §9.1 / 07 §5.4, the composite `UNIQUE`, the quartet. Change-capture triggers insert / update / delete (`link` is synchronizable).
- `link_index` exactly as written, `WITHOUT ROWID`, no triggers.

### 2.6 `embedding_version` (07 Part VIII)
- Exactly as written. **Create it before** any table whose `embedding_ver` column references it — SQLite with `PRAGMA foreign_keys=ON` refuses inserts against a `REFERENCES` to a missing table (ADR-038's Verification proved this empirically; the ordering inside one migration file is what avoids it).
- Zero rows. Nothing in this slice registers version 1.

### 2.7 The `message` rebuild (07 §5.5; ADR-048 D2)
Copy `0016`'s pattern exactly: `CREATE TABLE message_new (rowid INTEGER PRIMARY KEY, id TEXT NOT NULL UNIQUE, conversation_id TEXT NOT NULL REFERENCES conversation(id) ON DELETE CASCADE, role ... CHECK as written, content TEXT NOT NULL, at TEXT NOT NULL)`; `INSERT INTO message_new (id, conversation_id, role, content, at) SELECT id, conversation_id, role, content, at FROM message ORDER BY rowid` (order-preserving, regardless of row count — do not assume the table is empty, even though on the real machine it may be); `DROP TABLE message`; `ALTER TABLE message_new RENAME TO message`; **recreate `idx_message_conversation_at ON message(conversation_id, at)`** — indexes die with the dropped table. State in the migration header, as `0016` did, whether the real `%KANG_HOME%` database had rows when you checked (read-only connection, no lock).

### 2.8 The four FTS5 tables and their triggers (07 §6.1)
- `fts_memory`, `fts_episode`, `fts_chunk`, `fts_message`: `USING fts5(content, content='<table>', content_rowid='rowid', tokenize='porter unicode61')`. `content_rowid='rowid'` now binds to the explicit column from D2.
- Standard external-content sync triggers per table: `AFTER INSERT` (insert into fts with `new.rowid`), `AFTER UPDATE OF content` (the `'delete'` command row with `old.rowid, old.content`, then insert `new`), `AFTER DELETE` (the `'delete'` command row). This is SQLite's own documented pattern; copy it, do not invent one.
- **`fts_memory` only:** the `private` exclusion. The insert trigger carries `WHEN NEW.sensitivity <> 'private'`. The update trigger is `AFTER UPDATE OF content, sensitivity` and must handle a sensitivity flip in both directions: remove the old text only if `OLD.sensitivity <> 'private'`, insert the new text only if `NEW.sensitivity <> 'private'`. SQLite triggers have no `IF`; use `INSERT ... SELECT ... WHERE <condition>` for each of the two statements. The delete trigger removes only if `OLD.sensitivity <> 'private'` (there is nothing in the index for a private row, and issuing a `'delete'` for a rowid FTS5 never saw corrupts the index). Plaintext of a private record must never reach `fts_memory` — this is the claim the test proves.
- The other three tables have no `sensitivity` column in 07; no condition.
- **Create `fts_message` after the `message` rebuild** (it names the content table by name), then run `INSERT INTO fts_message(fts_message) VALUES('rebuild')` so any pre-existing messages are indexed. The same `'rebuild'` on the three empty tables is harmless and keeps the migration uniform.

### 2.9 What is NOT in the file (ADR-048 D4)
`vec_*` tables · `idx_mem_type_stat` / `idx_mem_status` / `idx_episode_time` / `idx_linkindex_dst` (or any other secondary index) · `v_project_memory` / `v_contested_records` · any `INSERT` of data · anything touching `tombstone`, `change_log`, or `conversation` beyond what the `message` rebuild requires.

## 3. Tests (all in the same PR; every one deterministic — injected clock, temp DBs, no network)

Home for DDL-level tests: `tests/integration/sqlite/` (13 §2.3 — adapters against real SQLite in temp dirs). Suggested file: `tests/integration/sqlite/test_memory_schema.py`, plus additions to `test_migrations.py` for the chain and the rebuild. Existing tests that must stay green untouched: `tests/fixtures/conversation_store_contract.py` (run against fake and SQLite), `test_conversation_store.py` (the cascade test), `tests/suites/replay/test_boot_catchup.py` (seeds real messages before boot), and the whole rest of the suite.

1. **Full chain** `0001`→`0020` applies on an empty DB; re-apply is a no-op; checksum recorded (extend the existing tests, don't duplicate them).
2. **`message` rebuild is lossless**: seed a conversation with several messages *before* applying `0020` (apply `0001`–`0019` first), apply `0020`, assert every row, its order, the cascade on conversation delete, and `idx_message_conversation_at`'s existence (`PRAGMA index_list('message')`). Model: `test_0006_preserves_task_rows_across_the_table_recreation`.
3. **Every CHECK, NOT NULL, FK exercised with a violating insert that must fail** (07 Part XVI "Schema" row): each enum value outside the closed set for `memory_record.type/status/trust_tier/sensitivity/source_kind`, `episode.type/status`, `link.type/status`, `memory_candidate_queue.resolved`, `embedding_version.status`; `confidence`/`importance` out of `[0,1]`; empty `content`/`reason`; `pinned` outside `(0,1)`; the `private` invariant (a `private` row with plaintext `content`, or with `content_enc IS NULL`, is refused); `memory_revision`/`link`/`vault_chunk` FKs to missing parents refused; the `link` composite `UNIQUE`; `vault_chunk`'s `UNIQUE (note_path, seq)`; `embedding_ver` referencing a missing version refused. Property-based over arbitrary invalid rows is REQUIRED for constraint surfaces (13 §2.2) — `hypothesis` is not a dependency today, so use exhaustive parametrization over the closed enums plus boundary values; if you believe property-based testing genuinely needs a new dependency, stop and say so rather than adding one (11 §25).
4. **Enum exhaustiveness against 06's taxonomy, programmatically** (07 Part XVI): the set of values in each CHECK must equal 06's list. Preferred mechanism: parse the relevant tables in `docs/06_MEMORY.md` (§2.1 type catalog, §9.1 link types, §4.2's `sensitivity`/`trust_tier` lines) and `docs/07_DATABASE.md`'s DDL, and compare to what `PRAGMA table_info` + the migration file show. If parsing the markdown is impractical, a test holding the expected tuples with a line citation to 06 is the honest floor — say which you did in the CLAIMS line. Note the deliberate exception this test must encode: `memory_record.status` is 06's machine *minus* the two queue-resident states (D1).
5. **FTS sync**: for each of the four tables, an insert is findable via `MATCH`, an update of `content` re-indexes, a delete un-indexes; `INSERT INTO fts_x(fts_x) VALUES('integrity-check')` passes after each. For `fts_memory`: a `private` row never appears; a flip normal→private removes it; private→normal indexes it; a delete of a private row leaves the index intact.
6. **Change capture**: insert/update/delete on `memory_record`, `episode`, `link` and insert on `memory_revision` each write one `change_log` row with the right `entity`/`op`; **a statistics-only `UPDATE` (`last_accessed`, `access_count`) on `memory_record` writes none** (D5); no capture rows ever appear for `memory_candidate_queue`, `link_index`, `vault_note`, `vault_chunk`, `embedding_version`.
7. **Provenance invariant** (07 XIII.5): a schema-diff assertion that `0020` introduces no provenance column that is nullable and weakens nothing pre-existing (the existing suite may already have the shape; extend it).
8. **The rowid never crosses a port**: ADR-048's Verification names this test, but no memory port exists after this slice. It lands with the next slice (the first ports). Record that in CLAIMS as "owed to S2", not as done.
9. **Zero `memory_record`/`episode`/`link` rows after the full chain** — nothing seeds; 03 §3's "no gate bypass for bootstrapping" starts here.

## 4. Document amendments (same PR — CLAUDE.md §6; never edit accepted ADR text except the Verification section)

- `07_DATABASE.md`: §5.1 `memory_record` DDL — narrowed `status` CHECK, `DEFAULT 'candidate'` removed, `rowid` column, and a dated comment above the DDL (the `0019`/ADR-046 shape) explaining D1 and pointing at `memory_candidate_queue` as the sole candidate home; §5.1 `episode` and §5.3 `vault_chunk` — `rowid` column with a one-line dated note; §5.5 `message` — `rowid` column, dated note; DB-003 — a dated one-sentence clarification (identity is the UUIDv7; four tables carry a storage-local integer rowid alias for FTS5/vec0 binding, never exposed); §5.6/§4.1 — a dated note that `memory_record`'s update capture excludes `last_accessed`/`access_count` (D5); §6.1 — a dated note that all four `fts_*` landed in `0020` and that `fts_memory`'s triggers carry the `private` condition. Bump the header's "Last updated".
- `06_MEMORY.md`: §2.1D and M-002 — one dated clarifying note: `candidate`/`rejected` are real lifecycle states that live in the quarantine table; `memory_record` holds gate-passed records only; admission and transition are two store-layer functions (ADR-048 D1). Bump "Last updated".
- `18_IMPLEMENTATION_MASTER_PLAN.md` §4 Phase 2 row — a dated note: the schema DDL precedes the corpus generator that emits into it (ADR-048 Context, finding 4).
- `docs/adr/048-memory-truth-schema.md` — **append** to its Verification section the "Implemented and verified (date)" paragraph in the style of ADR-046/047: what landed, what the tests prove, the live-verification result, suite counts before/after. Do not touch Context/Options/Decision/Consequences. If implementation forces a correction to a Decision, that is a *new* ADR (or, for a small factual slip, a dated "Corrected by …" note in the same style the codebase already uses) — never a silent edit.
- `docs/adr/INDEX.md` — change the 048 row's status to `accepted — implemented (date)` (the row already reads `accepted — not yet implemented`).
- `tests/suites/CLAIMS.md` — one line per claim in §3 above, in the file's existing format.

## 5. Verification protocol before you call it done (CLAUDE.md §9; the rhythm every prior slice used)

1. `ruff format --check .` — CI's own first gate; a prior session skipped it a whole session and a push failed. Then `ruff check .`, `lint-imports --config tools/importlinter.toml`, `python tools/lint_sizes.py`, `python tools/lint_banned_patterns.py`, `python tools/lint_tree_hygiene.py`, `python tools/lint_doc_citations.py`, `python tools/build_root_docs.py --check`. All must be clean. No new import-contract exemption should be needed (this slice adds no Python under `src/`); if one seems needed, you have put something in the wrong place.
2. Full test suite, both halves as the Build State note records them (`tests/unit` + `tests/suites`; `tests/integration`). Record the before/after counts; the after count must equal before + your new test items exactly — no silent coverage loss.
3. Live verification against a **throwaway** `%KANG_HOME%` (never the real one): a real `build_core()` or real subprocess boot applies `0020` on top of a real `0001`–`0019` database that already contains a conversation with messages; confirm with a read-only `sqlite3` connection that the messages survived with `rowid` values, that `fts_message MATCH` finds them, that `PRAGMA foreign_key_check` is clean, that `PRAGMA integrity_check` is `ok`, and that `SELECT count(*)` on every new truth table is 0. Delete the throwaway afterwards.
4. Do not run any migration against the real `%KANG_HOME%`. Reading it read-only to report row counts in the migration header (as `0016` did) is fine.

## 6. Commits (CLAUDE.md; Kang's standing instruction)

- The acceptance of ADR-048, its INDEX row, and this brief are already committed locally (`44e9f00`, `docs(adr): accept ADR-048 - the memory truth schema`). Start from that commit on `main`; `git status` should be clean before you touch anything.
- The implementation is one commit, detailed and honest in the style of `git log`'s recent entries: what changed, what was found, what is proven, what is deferred (D4's list).
- **Never push.** Every commit this whole stretch has stayed local until Kang says otherwise.
- End commit messages with the attribution line the session's system reminder gives you.
- Do not accept, reopen, or re-decide any ADR. If something in ADR-048 turns out to be wrong against the real database, stop, write down exactly what you found, and ask Kang.

## 7. Known traps, so you do not rediscover them

- `PRAGMA foreign_keys=ON` is set on every real connection (`adapters/sqlite/connection.py`). A `REFERENCES` to a not-yet-created table fails on insert, not on `CREATE` — order the DDL so parents precede children (`embedding_version` first, `memory_record` before `memory_revision`, `vault_note` before `vault_chunk`, `conversation` already exists for `message_new`).
- Dropping `message` while `PRAGMA foreign_keys=ON`: `message` is a child, not a parent, so the drop is legal; nothing references `message(id)`. Neither `0005`, `0006`, nor `0016` touched the foreign-keys pragma for their rebuilds (checked 2026-09-17 by grep), and the harness applies each file with `executescript` on a connection that already has the pragma on — so do not add a `PRAGMA foreign_keys=OFF` either; the rebuild works with it on, and prove that in the rebuild test rather than assuming it.
- The banned-pattern lint scans `src/` only; SQL in `tests/` is legal. There is no store code in this slice, so there should be no SQL under `src/` at all beyond the migration file, which the harness reads as text.
- `content_rowid='rowid'` with an explicit `rowid INTEGER PRIMARY KEY` column is legal and verified (2026-09-17, Python 3.12.5 / SQLite 3.45.3). Do not rename the column to something else "for clarity" — 07 §6.1/§6.2's vocabulary is `rowid`/`record_rowid`, and one concept gets one name.
- FTS5 external-content tables do not validate content; a wrong trigger silently desyncs. `'integrity-check'` after every mutation in the tests is what catches it.
- The migrations harness rejects gaps and malformed names; `0020_memory_truth_schema.sql` matches the regex. Do not split into `0020` and `0021` — ADR-048 D3 is explicit that this is one migration.
- 06 §7.1's "conversation transcripts are purged, explicit saves extracted first" still has no mechanism (ADR-047 D2). Nothing in this slice changes that; do not add one.
