# Build brief — implementing ADR-053 (the record lifecycle and the deletion covenant)

**Written:** 2026-09-24, by the session that drafted ADR-053.
**For:** the coding session that implements it.
**Precondition — check before touching anything:** `docs/adr/053-memory-lifecycle-and-deletion.md` must say `**Status:** accepted`. If it still says `proposed`, stop, say so, and end your turn.
**Non-normative** (17 §12). ADR beats brief; a numbered document beats the ADR except where the ADR's "Affected documents" line names the amendment. A third disagreement: stop and surface it.

> **This slice builds the only irreversible operation in the memory system.** Past 30 days a deletion cannot be undone by KANG at all. ADR-053 D2 is therefore a hard sequencing rule, not a preference: **build `memory.restore_from_snapshot` before `memory.delete`**, so that at no point in your own development — including your own live verification — does a delete path exist without its undo. If you find yourself about to test deletion before restore works, stop and reorder.

---

## 0. What you are building

Six Kang-only operations over records that already exist, one registered event, a new `BackupService` capability, a fourth composition-root file, and the tests. **No schema change, no migration** — every column this slice touches was migrated by ADR-048. No read path, no UI, no gate change (D9).

## 1. Read first, in this order

1. `CLAUDE.md` (repo root) — §8 and §9.
2. `docs/adr/053-memory-lifecycle-and-deletion.md` — D1–D9. Its Context's four findings explain *why* each decision is shaped the way it is; D9 is what you must not build.
3. `docs/06_MEMORY.md` §1.5 (the four covenants — 1 and 3 are what this slice discharges), Part III / M-002 **including the transition table**, §7.2 **verbatim** (the recovery paragraph D5 and D6 both implement), §8.2, §12.3.
4. `docs/07_DATABASE.md` Part XII.2 and XII.4 (snapshot retention and the attach-copy-detach mechanism), §5.1 (`tombstone`), Part X §4–§5.
5. `docs/12_API.md` §10; `docs/05_AGENTS.md` Appendix D; `docs/09_UI_DESIGN.md` §7 (what the confirmation renders).
6. Pattern sources: `src/kang/api/operations/held_action_ops.py` + `consequential.py` + `kernel/runtime/composition.py`'s `_check_transactional_effects_registered` (ADR-021's machinery — read all three before wiring `memory.delete`); `src/kang/adapters/sqlite/task_store.py::delete` (the delete-plus-tombstone shape, copy it); `src/kang/adapters/sqlite/backup.py` and `domain/ports/backup.py` (where D5's new capability goes); `kernel/runtime/model_wiring.py` (the most recent composition-root split, ADR-044 — your model for D8).
7. `tests/suites/CLAIMS.md`.

## 2. Order of work (D2 is not negotiable)

1. Store surface first: `MemoryStore` gains update-with-revision, transition, delete-with-tombstone, and re-insert; `memory_revision` writes. Fakes and SQLite adapters, contract-paired per 13 §2.3.
2. `BackupService`'s attach-copy-detach capability, with its own tests against a real snapshot file.
3. **`memory.restore_from_snapshot`** — built and green before the next step.
4. `memory.update`, `memory.pin`, `memory.archive`, `memory.restore`.
5. **`memory.delete`** last, with its `transactional_effects` entry and the held-action path.
6. The `memory.updated` event, applier, and payload-sufficiency fixture.
7. The composition-root split (D8), then documents.

## 3. The things most likely to go wrong

- **`active → deleted` does not exist.** M-002's only edge into `deleted` is from `archived` — confirmed in both the diagram (`docs/06_MEMORY.md:166`) and the transition table (`:181`). `memory.delete` must refuse an `active` record. This is a safety property, not an oversight; do not "helpfully" allow it.
- **`memory_revision.device_id` is `NOT NULL`** (ADR-048's amendment, migration 0021) and is the **editing** device, not the record's. Supply it explicitly. This slice is that column's first real writer.
- **`transactional_effects` is startup-enforced.** An operation registered `commit_mode="transactional"` without a matching entry fails the startup check, not the request. Read `_check_transactional_effects_registered` before you register.
- **`composition.py` is at 799 of 800.** D8 requires the split *before* you add wiring, not after you hit the lint. Mirror `model_wiring.py`: the new file, its own `tools/importlinter.toml` entries, and its line in 17 §4.3's exemption list — all three, same commit.
- **The 30-day window is enforced by which snapshots exist**, not by arithmetic on a date (D5). Do not add a cutoff comparison, and do not fall back to monthly snapshots when a daily lacks the row.
- **Restoring must remove the tombstone and bump `revision`**, or a future sync merge would order the deletion after the restoration.
- **The `reversibility` string carries both of D6's facts.** The second one is a limit, not a reassurance — deletion from KANG is not destruction from your backups. Do not soften it.
- Deleting a record cascades `memory_revision` and fires the FTS and change-capture delete triggers. Assert all of that, rather than assuming the triggers fire.

## 4. Documents (same commit)

- `12_API.md` §10 — dated amendment per D1 (the two restores are distinct operations with distinct scopes), extending the note ADR-051 already started.
- `06_MEMORY.md` Part III — dated note per D3: which transitions are live and what each remaining one waits on.
- `15_EVENT_BUS.md` §6.1 — `memory.updated` joins the taxonomy; record in the same note that `memory.deleted` is deliberately absent and why (D6 of the Consequences: no consumer, and a replayed delete after a snapshot restore would silently re-delete).
- `05_AGENTS.md` Appendix D — dated note: `memory.delete` is now live.
- `17_PROJECT_STRUCTURE.md` §4.3 — the fourth composition-root file.
- `config/defaults/permissions.toml` — the three new scopes (D7).
- `docs/adr/INDEX.md` row; `tests/suites/CLAIMS.md` lines; ADR-053's Verification appended.

## 5. Verification protocol

1. `ruff format --check .` first, then `ruff check .`, `lint-imports`, `lint_sizes.py`, `lint_banned_patterns.py`, `lint_tree_hygiene.py`, `lint_doc_citations.py`, `build_root_docs.py --check`.
2. Both non-nightly halves with exact before/after counts. Before: **1075** and **357**. `-m nightly` before: **15**.
3. Everything ADR-053's Verification section lists. The `active → deleted` refusal and the both-facts `reversibility` string are the two most likely to be skipped; do not skip them.
4. Live-verify on a **throwaway** `%KANG_HOME%` (delete after; never the real one): a real snapshot taken, a real record archived then deleted through the real held-action confirmation path, the row and its revisions and its FTS entry gone with a content-free tombstone present, then **really restored from that snapshot** with its revisions back, the tombstone gone, and the record findable in `fts_memory` again. Also: `active → deleted` refused; a non-first-party session refused on all six; a stale expected-revision `memory.update` refused.
5. Never touch the real `%KANG_HOME%`.

## 6. Commit

One commit on `main`, local, never pushed, in `git log`'s established style: what changed, what was found, what is proven (with numbers), what is deferred (D9). End with the attribution line your session's system reminder gives you. Do not accept, reopen, or re-decide any ADR. If reality contradicts ADR-053 anywhere near deletion, stop and ask Kang.

## 7. One stale comment to fix while you are here

`tests/suites/memory_integrity/test_no_code_path_to_active.py` has a comment above its post-call assertion reading that a silent merge may bump provenance and revision but never the words. ADR-052 made that false — the assertion directly below it now forbids any column change. Correct the comment to match the code. It is one line, it sits in the project's most safety-critical test, and left alone it invites someone to weaken the assertion to match the prose.
