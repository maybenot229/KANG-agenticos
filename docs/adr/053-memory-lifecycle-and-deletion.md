# ADR-053 — The record lifecycle and the deletion covenant: two "restores" separated, and delete never ships without its recovery path

**Status:** accepted (2026-09-24) — Kang's own "accept it", same session as drafting; Options 1B / 2B / 3B as recommended, D1–D9 accepted as written. The fourth slice of the Phase 2 slicing plan (048 the schema, 049 the corpus, 051+052 the gate). **Not yet implemented** — implementation is delegated to a separate coding session; its build brief is `docs/guides/session-2026-09-24-adr053-build-brief.md`.
**Date:** 2026-09-24
**Supersedes:** none
**Affected documents (if accepted):** `12_API.md` §10 (a dated amendment: its `memory.restore` names the archived→active transition; the snapshot undelete 06 §7.2 and 07 XII.4 both describe is a *different* operation and gets its own name, D1 — plus the dated note ADR-051 already started, extended with the operations this slice adds); `06_MEMORY.md` M-002/Part III (a dated note: `under_review` and `superseded` have no producer until their slices, so the transition table is implemented in part, D3); `15_EVENT_BUS.md` §6.1 (the closed taxonomy gains `memory.updated`; `memory.deleted` is deliberately *not* registered, D6); `05_AGENTS.md` Appendix D (a dated note: `memory.delete` is now a real entry on the closed consequential list, not a reserved one, D4); `config/defaults/permissions.toml` (two new scopes, D7); `17_PROJECT_STRUCTURE.md` §4.3 + `tools/importlinter.toml` (a fourth composition-root file, forced by D8 — the same ADR-023/037/044 trigger)
**Cites:** 06_MEMORY §1.5 covenant 1 ("Every record is viewable, editable, and deletable by Kang... A memory KANG has that Kang cannot see is a critical bug") and covenant 3 ("Delete removes the record, its embedding, its index entries, and its future retrievability. What remains: a tombstone (id + deletion timestamp + actor — no content)"), M-002/Part III (the state machine and its transition table), §7.2 verbatim ("a mistaken deletion is recoverable for 30 days via backup restore of the record... implemented as snapshot-attach + row copy... After 30 days, single-record restore is no longer offered... Deleted content additionally persists inside backup snapshots until those snapshots age out... **The deletion confirmation dialog states both facts**"), §8.2 (revision semantics: "Edits never overwrite silently"), §12.3 (every transition and every deletion audited, with its policy citation); 07_DATABASE Part XII.4 ("Single-record restore: `ATTACH` snapshot → copy row(s) + revisions → detach. Exposed in the memory browser as 'restore from snapshot'"), Part XII.2 (30 daily + 12 monthly snapshots — the retention that bounds D5's window), §5.1 (`tombstone`), DB-001 (the event-before-commit pairing), Part X §4 (tombstones for every destroyed synchronizable row); 12_API §10 (`memory.update`/`pin`/`archive`/`restore`/`delete`, and delete's "response includes the 30-day recovery note as data"); 05_AGENTS Appendix D (the closed consequential list, which already names `memory.delete`); 09_UI_DESIGN §6 (the record view's actions and the confirmation's required content), §7 ("One action, one dialog... the reversibility statement"); 11_CODING §3 (one concept, one name — the reason D1 exists); ADR-021 (the consequential machinery: `require_confirmation`, `held_action`, `commit_mode="transactional"`, and the registration-time `transactional_effects` gate), ADR-018 (the standing `<entity>.updated` pattern), ADR-026 (do not register an event without a consumer), ADR-048 D1 (the four live statuses), ADR-051/052 (the gate this slice sits beside but does not touch), ADR-023/037/044 (the composition-root split precedent D8 invokes)
**Related:** [[051-memory-write-gate.md]], [[052-gate-merge-and-tier-amendment.md]], [[048-memory-truth-schema.md]]

---

## Context

The gate can put a record into the store. Nothing can edit, pin, archive, or remove one — `MemoryStore` has exactly `insert_record`, `get`, `find_active_duplicate`, `merge_provenance`, and the six registered operations are all write-path. 06 §1.5's first covenant ("viewable, editable, and deletable by Kang") is therefore two-thirds unmet, and the third covenant — deletion is real, with a tombstone — is entirely unbuilt.

Four things found by reading the documents and the code together, each of which shapes a decision:

**Finding 1 — "restore" names two different operations.** 12 §10 lists `memory.restore` in a lifecycle series (`update`, `pin`, `archive`, `restore`, `delete`), where it plainly means M-002's `archived → active : Kang restores`. 06 §7.2 and 07 Part XII.4 describe something else entirely under the same English word: *"single-record restore"*, *"restore from snapshot"* — reviving a **deleted** record by attaching a backup file and copying the row back. One name, two concepts, in a project whose §3 rule is one concept one name. If both ship as "restore", the memory browser will have two buttons whose difference is invisible, and the more dangerous one (undelete) will be the less obvious.

**Finding 2 — two of M-002's states have no producer.** `under_review` is entered by "contradiction detected; staleness probe; per-type review cadence" — contradiction detection needs the NLI probe ADR-052 confirmed absent, staleness probes and review cadence need the janitor, and none of those exist. `superseded` is entered when "resolution names a winner", which needs either the `supersedes` link (the link-layer slice) or an explicit supersession operation nothing has asked for. Building manual operations to reach states nothing can legitimately produce would be inventing a second, Kang-driven path into a machine designed around automatic detection.

**Finding 3 — deletion's recovery half lives in a different subsystem, and does not exist.** `BackupService` has `take_snapshot`, `verify_latest`, `latest_status`, `external_backup_status` — no attach-and-copy. 07 XII.4 specifies the mechanism and nothing implements it. So `memory.delete` could ship today with a 30-day recovery window that exists only as a sentence: the snapshot files would genuinely contain the row, but KANG would offer no way to get it back, and Kang would be reduced to `sqlite3` on a backup file.

**Finding 4 — the confirmation must state two facts, and only one of them is about recovery.** 06 §7.2 ends: *"The deletion confirmation dialog states both facts."* The facts are (a) single-record restore is available for 30 days, and (b) the deleted content nevertheless persists inside backup snapshots until the last containing snapshot rotates — up to twelve months under 07 XII.2's 30-daily-plus-12-monthly retention. The second is not a reassurance; it is an honest limit on what "deleted" means, and it belongs in the `reversibility` string `require_confirmation` already carries.

**A mechanical consequence worth stating up front:** `composition.py` is at **799 of its 800-line hard limit**. A consequential operation requires a `transactional_effects` entry built from live adapter closures in the composition root (ADR-021, enforced at startup by `_check_transactional_effects_registered`). This slice therefore *forces* the split ADR-023/037/044 each performed. That is not incidental — it is a known, predicted cost of this slice and is decided in D8 rather than discovered mid-implementation.

**What is settled and not re-opened:** the gate and everything ADR-051/052 decided; ADR-048 D1's four live statuses; the tombstone table and its shape; the consequential machinery itself; that all of this is Kang-only (06 §1.5 covenant 1 — no agent archives, edits, or deletes a memory).

---

## Options

### Option 1 — Naming the two restores (Finding 1)

**1A — `memory.restore` is the snapshot undelete; the lifecycle transition becomes `memory.unarchive`.** *For:* "restore" matches the more dramatic operation, and `archive`/`unarchive` is a clean pair. *Against:* 12 §10 already uses `memory.restore` in its lifecycle list, so this renames an operation the API document has named; and 07 XII.4's own phrase for the other one is "restore **from snapshot**", not "restore".

**1B — `memory.restore` stays the archived→active transition; the undelete is `memory.restore_from_snapshot`. (Recommended.)** *For:* each name is the one its own document already uses — 12 §10 says `memory.restore` among lifecycle verbs, 07 XII.4 says "restore from snapshot" twice; the longer name falls on the rarer, more dangerous operation, which is where verbosity belongs; no existing document sentence needs rewriting, only a dated note recording that the two are distinct. *Against:* a long operation name, and a reader skimming the registry sees two restores. Mitigated by the dated note and by the two carrying different scopes (D7).

### Option 2 — Whether `memory.delete` ships before its recovery path (Finding 3)

**2A — Ship `memory.delete` now; `memory.restore_from_snapshot` follows in a later slice.** *For:* a smaller slice; the covenant's *destruction* half is what 06 §1.5 covenant 1 actually promises Kang, and the snapshot files do genuinely retain the row regardless. *Against:* it ships the one irreversible operation in the memory system during a window in which KANG offers no undo for it. 06 §7.2 does not describe the 30-day window as a nice-to-have; it is the sentence that makes "deletion is real" acceptable. Shipping the irreversible half first is the exact inversion of "policy before power".

**2B — Delete and snapshot-restore are one unit; neither ships without the other. (Recommended.)** *For:* the covenant lands whole or not at all, which is the only form in which it is honest; the confirmation dialog can truthfully promise a recovery path that exists (D6); and a mistaken deletion during the slice's own live verification is itself recoverable. *Against:* a larger slice that reaches across two subsystems (memory store and backup adapter) in one commit. Accepted, and bounded by D3 keeping the lifecycle transitions narrow.

### Option 3 — How much of M-002 to build (Finding 2)

**3A — Build the whole transition table now, adding Kang-driven operations for `under_review` and `superseded`.** *For:* the state machine is complete and M-002 is fully implemented. *Against:* it invents manual entry points into states the document describes as *detected*, not chosen — a Kang who can hand-mark a record `superseded` without a `supersedes` link produces a record whose loser has no winner, which is a worse data shape than not having the operation. It also front-runs the link layer's own design.

**3B — Build only the transitions with a real actor today: edit, pin, archive, restore. `under_review` and `superseded` arrive with their producers. (Recommended.)** *For:* every operation built has a caller and a meaning; M-002's other states stay reachable only by the mechanisms designed to reach them; a dated note in Part III records that the table is implemented in part and what each remaining transition waits on. *Against:* M-002 is partially implemented for a while, and someone reading the diagram will not know which edges are live without the note. The note is therefore required, not optional.

---

## Decision

### D1 — Two names, each its own document's (Option 1B)

`memory.restore` is the `archived → active` transition. `memory.restore_from_snapshot` is the undelete. 12 §10 gets a dated amendment recording that the two are distinct operations with distinct scopes and that its own `memory.restore` entry means the former.

### D2 — Delete and snapshot-restore are one unit (Option 2B)

Neither lands without the other, in the same commit. The brief sequences `memory.restore_from_snapshot` **before** `memory.delete` so that at no point in the slice's own development does a delete path exist without its undo.

### D3 — The lifecycle operations built, and the transitions left to their producers (Option 3B)

Built, all `first_party_only`, all Kang-only:

| Operation | Effect |
|---|---|
| `memory.update` | Edits `content` and `reason` of an `active` record. Revision-checked (expected revision in the request; mismatch ⇒ `conflict`). Writes the **prior** content to `memory_revision` with the editing `device_id` (ADR-048's amendment made that column `NOT NULL`), then bumps `revision`. Does **not** change `type`, `trust_tier`, `sensitivity`, or `status` — those are not edits, and one of them is ADR-052 D3's own explicit path. |
| `memory.pin` | Sets `pinned`; takes the desired state, so it is its own inverse and idempotent. 06 §5.2: a pin is Kang's thumb on the retrieval scale, which nothing reads yet. |
| `memory.archive` | `active → archived`. |
| `memory.restore` | `archived → active`. |
| `memory.delete` | `archived → deleted`, consequential (D4). |
| `memory.restore_from_snapshot` | Undeletes from a backup snapshot (D5). |

**`memory.delete` requires the record to be `archived` first**, per M-002's own table, which has no `active → deleted` edge. Deleting is therefore deliberately a two-step act, which is a safety property, not an inconvenience — and it is worth saying plainly because a reader will otherwise assume the missing edge is an oversight.

06 Part III gets a dated note: `under_review` and `superseded` are unreachable until the janitor's staleness probes and contradiction detection (embeddings/NLI) and the link layer's `supersedes` edges exist respectively.

### D4 — `memory.delete`: consequential, transactional, tombstoned

Registered `commit_mode="transactional"` with its `transactional_effects` entry (ADR-021's machinery, unchanged), `first_party_only`, scope `memory.delete`. The held action's `action` names the record and quotes enough of its content for Kang to recognise what he is destroying; its `reversibility` carries D6's two facts.

The effect, in one transaction: delete the `memory_record` row (which cascades `memory_revision`, fires the FTS delete trigger, and fires the change-capture delete trigger), and insert a `tombstone` row carrying id, entity, `deleted_at`, `deleted_by`, and `policy_ref = 'kang:explicit'`. Content is destroyed; the tombstone carries none of it (06 §1.5 covenant 3). The deletion is audited with its policy citation (06 §12.3). The response carries the 30-day recovery note as data, which 12 §10 already requires.

05 Appendix D gets a dated note: `memory.delete` is now a live entry on the closed consequential list rather than an anticipated one.

### D5 — `memory.restore_from_snapshot`: the window, enforced by what exists

A new `BackupService` capability implementing 07 XII.4: attach the chosen snapshot read-only, read the record row **and its `memory_revision` rows**, detach, and insert them back — in one transaction, removing the `tombstone` row for that id and bumping `revision` so a future sync merge orders the restoration after the deletion (07 Part X §5's `(revision, device_id)` ordering).

**The 30-day window is enforced by the snapshots that exist, not by a date comparison.** 07 XII.2 retains 30 daily snapshots; a record deleted more than 30 days ago is simply absent from every daily snapshot, and the operation reports honestly that it cannot be found rather than computing a cutoff. This means the monthly snapshots (12 of them) may still contain it — which is exactly why D6's second fact is stated, and the operation does *not* search monthlies: 06 §7.2 says single-record restore is not offered after 30 days, and offering it opportunistically from a monthly would make the window unpredictable.

Refuses with `conflict` if a record with that id already exists. `first_party_only`, scope `memory.restore_snapshot`.

### D6 — The confirmation states both facts, in the `reversibility` field

Verbatim in substance, from 06 §7.2: *this record can be restored from a daily snapshot for 30 days; after that it cannot. The deleted content nevertheless remains inside existing backup snapshots until the last one containing it rotates, which can be up to twelve months — deletion from KANG is not destruction from your backups.* The second sentence is an honest limit, not a reassurance, and 09 §7's dialog renders the `reversibility` string as written.

### D7 — Scopes

`memory.curate` for `update`, `pin`, `archive`, `restore` — one authority, "manage records Kang already has". `memory.delete` and `memory.restore_snapshot` each get their own, because the first is irreversible and the second reaches into the backup subsystem; both deserve to be separately visible on the permission screen and separately grantable, even though only `kang` will hold any of the three for the foreseeable future. All six operations are additionally `first_party_only` (ADR-002 — a channel control, not a scope), which is what actually prevents an agent session from curating memory.

### D8 — The composition root splits into a fourth file

`composition.py` at 799/800 cannot absorb this slice's wiring. Following ADR-023/037/044 exactly: a new `kernel/runtime/memory_wiring.py` holding the memory stores, the gate's dependencies, and this slice's `transactional_effects` entry; its own named entries in `tools/importlinter.toml`; a line in 17 §4.3's composition-root exemption list. **Four files, one conceptual composition root** — the phrasing 17 §4.3 already uses for three.

### D9 — What this slice does not do

No schema change or migration (every column already exists). No read path — `memory.get`, `memory.search`, `explain.memory` and the browser's record view remain the retrieval slice's. No `memory.deleted` event (D6 of ADR-051's reasoning extended: see Consequences). No change to the gate. No embedding or index work beyond what the existing triggers do on their own. No UI.

---

## Consequences

**What becomes true.** 06 §1.5's first covenant is met: every record is editable and deletable by Kang, through operations that exist. The third covenant lands whole — deletion is real, tombstoned, audited, *and* undoable for 30 days, with the honest limit stated at the moment of decision rather than discovered later. `memory_revision` gets its first writer, which is also the first real use of the `device_id` column ADR-048's amendment added.

**What becomes harder, or costs something.** Deleting is two steps (archive, then delete), which is friction by design and will feel like a bug to anyone who has not read M-002. M-002 is implemented in part, and the dated note is the only thing telling a reader which edges are live. The composition root becomes four files — more indirection, and a fourth import-linter exemption, each of which 17 §4.3 requires be individually named and justified. And `memory.restore_from_snapshot` couples the memory slice to the backup adapter for the first time, so a change to snapshot layout now has a second consumer to check.

**One registered event, and one deliberately absent.** `memory.updated` is registered recovery-grade with a full-row payload, an applier, and a payload-sufficiency fixture, following ADR-018's standing pattern — losing an edit on crash would silently revert Kang's own words, which is the failure DB-001's pairing exists to prevent. `memory.deleted` is **not** registered, for two reasons: ADR-026's rule (no consumer), and a hazard specific to deletion — a recovery-grade delete event replayed during reconciliation *after* a snapshot restore would silently re-delete the just-restored record. Losing a delete event instead fails safe: the record survives, the tombstone is in the same transaction as the row removal, and the audit log carries the act. Deletion is durable through the transaction, not through the bus.

**Named, not decided:** the memory browser and every read path (retrieval slice); `under_review` and `superseded` and their producers; whether `memory.update` should ever be allowed to change `sensitivity` (blocked today anyway — no encryptor); bulk operations of any kind; and whether the monthly snapshots should ever be searchable for an older undelete, which 06 §7.2 currently answers no.

## Verification

**Implemented and verified, 2026-09-24.** Every claim this section named going in was checked, against real code and — for the operational ones — a real throwaway `%KANG_HOME%` (deleted after, the real one never touched):

- **`active → deleted` refused, `archived → deleted` succeeds.** Refused twice over: `memory.delete`'s handler refuses an `active` record before a held action is even created (`conflict`, no confirmation offered), and `MemoryStore.delete_and_tombstone_in_txn` refuses again at the SQL layer (`WHERE status = 'archived'`) even if called directly — a structural safety property, not a UI convenience. `archived → deleted` succeeds and was exercised for real (below).
- **The delete transaction.** Against a real connection: the row is gone, `memory_revision` rows are gone by `ON DELETE CASCADE`, the `fts_memory` entry is gone, a `tombstone` row is present carrying `entity/deleted_by/policy_ref` and no content, a `change_log` delete row is written, and the audit log carries `memory.deleted` with `{"id", "policy_ref": "kang:explicit"}`. `memory.delete` raises `confirmation_required` without a token and, through the real `held_action.approve` path, executes — one shared transaction with the approve-flip and mark-executed writes; a forced-failure effect rolls back both; `_check_transactional_effects_registered`'s startup gate proves the `transactional_effects` pairing (proven both as a unit test and by `build_core` itself booting clean against the real table).
- **The `reversibility` string** carries both of D6's facts, unsoftened: the 30-day window and the "deletion from KANG is not destruction from your backups" limit — checked verbatim in the real held action's own field.
- **`memory.update`** writes the prior content to `memory_revision` with the editing `device_id` (never the record's own) before bumping revision, refuses a stale `expected_revision` without touching the store or publishing, and refuses a non-`active` record.
- **`memory.restore_from_snapshot`** revives a deleted record **with its revisions**, from a real daily snapshot file via `ATTACH`/cross-database copy/`DETACH`, removes the tombstone, bumps `revision` one past the snapshot's own, re-indexes it in `fts_memory` (the schema's own trigger, not a manual step), refuses `conflict` when the id already exists live, refuses `not_found` — never an invented cutoff — when no remaining daily snapshot has the row, and searches snapshots newest-first when more than one has it.
- **All six operations refused twice over** for an unauthorized session: a principal holding none of the three new scopes is refused `permission_denied`; a principal holding all three but not first-party is refused `first_party_required` — proving the channel gate (ADR-002/D7) independently of the scope gate.
- **`memory.updated`** is registered recovery-grade with the full `memory_record` shape, reconstructs the row on an empty store, replays idempotently by id+revision, and is published (event-before-commit, EB-004) by `update`/`pin`/`archive`/`restore` — never by `delete` or `restore_from_snapshot`. `memory.deleted` is confirmed absent from the registry.
- **The registry sweep** (`suites/memory_integrity/test_no_code_path_to_active.py`) now covers all twelve memory/candidate operations and the three legitimate `memory_record` writers (the store, the recovery applier, and — new — the backup adapter's own cross-database copy); the stale comment about a silent merge bumping provenance was corrected to match ADR-052's actual (stricter) assertion.
- **Composition root.** `composition.py` stayed at 799/800 by moving the write gate's and this slice's wiring into a fourth sibling, `kernel/runtime/memory_wiring.py` — named in `tools/importlinter.toml` and 17 §4.3 (which also gained a missed `model_wiring.py`/ADR-044 entry, corrected in the same pass rather than left silent). Import contracts: 8 kept, 0 broken.

**Test counts.** Before this slice: 1075 (unit+suites, non-nightly), 357 (integration, non-nightly), 15 (nightly, unchanged by this slice). After: **1110** (unit+suites), **376** (integration), **15** (nightly) — all green, including six pre-existing tests that had to be updated because `memory.delete` became a real registered operation for the first time (`test_held_action_operations.py`'s fixture had used `"memory.delete"` as a stand-in name for "an operation nothing has registered," `test_transactional_effects_gate.py`'s hand-built table, and `query_routing.py`'s own `_HandlerWiring` consumer, which needed updating for the `_Stores`/`_BusWiring` nesting D8's line-budget forced).

**Full lint suite:** `ruff format --check`, `ruff check`, `lint-imports`, `lint_sizes.py` (0 hard violations), `lint_banned_patterns.py`, `lint_tree_hygiene.py`, `lint_doc_citations.py`, `build_root_docs.py --check` — all clean.

**What the brief/ADR got wrong or left under-specified, resolved rather than silently worked around:**
- `17_PROJECT_STRUCTURE.md` §4.3's composition-root exemption list had only ever named three files (`composition.py`, `scheduler_wiring.py`, `query_routing.py`) — `model_wiring.py` (ADR-044) was missing from it the whole time. Corrected in this same commit alongside adding the fifth (`memory_wiring.py`), rather than perpetuating the gap.
- `query_routing.py` (a separate file, not touched by the ADR's own text) turned out to be a second, undocumented consumer of `_HandlerWiring`'s shape — D8's line-budget pressure forced `_HandlerWiring` to nest `stores`/`wiring` instead of flattening them, which broke `query_routing.py`'s own field access (`w.audit`, `w.permission_engine`) until fixed. Found by the full non-nightly run, not by inspection — worth naming since nothing in the ADR or brief flagged this file as in scope.
- SQLite ATTACH's `file:...?mode=ro` URI form silently fails on the shared write connection (`open_connection` never sets `SQLITE_OPEN_URI`) — `restore_memory_record` attaches by plain path instead; read-only-ness is structural (the copy statements never write `snap.*`), not URI-enforced, which the port's own docstring now says explicitly.
