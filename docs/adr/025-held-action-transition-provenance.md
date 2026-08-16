# ADR-025 — Held-action transition provenance: `decided_at` / `decided_by`

**Status:** accepted
**Date:** 2026-08-17
**Supersedes:** none
**Affected documents:** 07_DATABASE §5.5 (schema delta), `src/kang/domain/ports/held_action.py`, `src/kang/adapters/{sqlite,fakes}/held_action_store.py`, `src/kang/api/operations/held_action_ops.py`
**Cites:** `migrations/0005_held_action_lifecycle.sql` + `migrations/0016_held_action_expired_state.sql` (the table-rebuild pattern this migration follows), ADR-021 §Amendment (the dataclass-bundling fix for a parameter-limit crossing, reused here), ADR-024 (the D1 slice; this is D2)
**Related:** [[024-held-action-terminal-state-split.md]] (same investigation, split into three ADRs), ADR-026 (event registration — D3, explicitly out of scope here)

---

## Context

The 2026-08-16 read-only investigation established, and this session **re-verified independently against code before drafting** (not trusting the prior report):

**No held-action transition is attributable in durable state.** Five links, each re-checked:

- `reason` is written once at creation (`consequential.py:71`) and records why the action was *requested*, never why it *transitioned*. Every `UPDATE` in `held_action_store.py` touches only `status`.
- `correlation_id` is likewise set once at creation (`consequential.py:72`), never rewritten — so it threads back to the *requesting* invocation, not the deciding one.
- The dispatcher's audit payloads carry no request params: `_record_start` logs `{"trigger": ...}` (`dispatch.py:241`), `_finish` logs `None` (`dispatch.py:252`). Neither function even *receives* `request` — a structural non-availability, not an omission in what gets logged.
- `Invocation` has no `params` field (`ports/invocation.py:35-44`), so the execution ledger cannot say which row a given `held_action.cancel` acted on.
- No `held_action.*` event type is registered (`event_registry.py:171-330`, 13 types, none matching).

"Who cancelled this, and when" is unanswerable from durable state. ADR-024 made the *what* distinguishable (`cancelled` vs. `expired`); this ADR makes the *who* and *when* recorded. That matters because `kang explain` shipped at M4 and the approval queue is Kang's own authority surface — an entry that cannot explain its own outcome contradicts the premise the queue exists to serve.

**Live database re-verified before drafting** (read-only connection, no lock taken): zero `held_action` rows; `schema_version` head is 15, meaning the running Core has not booted since ADR-024 landed — migrations `0016` and this ADR's `0017` will both apply on its next start.

---

## Decision

### D2 — Two nullable provenance columns, written on every transition out of `pending`

`held_action` gains:

| Column | Type | Written when | Contents |
|---|---|---|---|
| `decided_at` | `TEXT NULL` | any transition out of `pending` | ISO-8601, from the injected `Clock` (never wall time — 11 §25) |
| `decided_by` | `TEXT NULL` | any transition out of `pending` | the deciding principal |

Both nullable, because `pending` rows legitimately have no decision yet.

### Which transitions write them — and which deliberately do not

Transitions **out of `pending`** (all three write both columns):

| From → To | Method | `decided_by` |
|---|---|---|
| `pending → approved` | `approve` / `approve_in_txn` | the approving principal (`kang`, via the first-party channel ADR-002 already enforces) |
| `pending → cancelled` | `cancel` | the declining principal |
| `pending → expired` | `expire_due` | `kernel:scheduler` — see below |

**`approved → executed` does NOT write them, and that is the substantive design call in this ADR, not an omission.** `mark_executed`/`mark_executed_in_txn` are untouched — no signature change, no write. `executed` inherits the approve-step's `decided_at`/`decided_by`, because the *decision* was the approval; execution is the effect landing, which is an outcome, not a decision. Overwriting the approval's provenance at the execute step would destroy the very record this ADR exists to create — for `transactional` mode both happen inside one transaction microseconds apart, so the overwritten value would also be nearly meaningless. This also means the highest-risk file in this change (below) needs no edit at all.

### `decided_by` for the expiry sweep: `kernel:scheduler`, obtained structurally rather than hardcoded

Ruled in advance, and code-verified here as an already-load-bearing identity rather than a new value: `kernel:scheduler` is the principal the `held_action_expire` job already mints its session under (`scheduler_wiring.py:115`) and already audits under (`scheduler.py:116`, `:202`). No collision found — it appears in no unrelated stored row.

**It is not hardcoded anywhere.** `HandlerContext.principal` derives from `session.principal` (`dispatch.py:125`, `:137`), so the expire handler simply passes `context.principal` — which *is* `kernel:scheduler` when the scheduler dispatches the job, and correctly `kang` if Kang ever invokes `held_action.expire` manually. No sentinel, no special case, no principal literal in the adapter layer (which must not know about principals at all).

The semantic awkwardness the original draft flagged — "recording a decider for a non-decision is a small lie" — is answered rather than accepted: `decided_by = kernel:scheduler` on an `expired` row is not claiming the scheduler *decided* anything. Paired with ADR-024's `expired` status, the row reads exactly as what happened: *the sweep, acting as `kernel:scheduler`, closed this window at this time because no decision arrived.* The status carries "nobody decided"; the provenance columns carry "who effected the transition, and when."

### Shape for a future fourth outcome (M7), without adding it now

M7's orchestrator may introduce approved-but-admission-declined. Per ADR-024's F3 that case cannot occur today, and this ADR **does not add the state** (ADR-024's D4 reasoning, unchanged). What it commits to: two generic nullable `TEXT` columns — a principal and an ISO timestamp — carry any future transition's provenance **without a further schema migration**. A future `approved → not_admitted` transition would populate these same two columns.

**Left explicitly open, not silently decided:** whether such a transition should *overwrite* the approve-step's provenance (losing who approved) or require a second pair of columns (a real schema change) or a transitions table. This ADR does not foreclose any of the three, and does not pretend to have chosen. Whoever designs M7's admission path decides; the column shape is the part that is settled.

### Migration

`migrations/0017_held_action_provenance.sql`, following `0005`/`0016`'s rebuild pattern.

A plain `ALTER TABLE ADD COLUMN` would technically suffice (no `CHECK` change — the same reasoning `0015` used for `params`). **The rebuild is chosen anyway**, for one reason stated honestly: `0016` just rebuilt this table one migration ago, and a rebuild keeps the full column list — including `NULL`ability and comments — visible in one readable `CREATE TABLE` that matches 07 §5.5's own snippet, rather than leaving the table's true shape to be reconstructed by mentally replaying two migrations. The cost (a copy of a table verified to hold zero rows) is nil.

**`NULL` on a terminal row means "predates ADR-025," not "no decision occurred."** Stated directly in the migration's SQL comment, because the two readings are indistinguishable from the data and the wrong one is actively misleading — a `cancelled` row with `decided_by IS NULL` had a decider; the system simply did not record them at the time. On a `pending` row, `NULL` correctly means no decision has been made yet. Verified moot in practice (zero live rows), recorded anyway, because the migration outlives the verification.

### Verification step, now standard

The migration is applied against a raw in-memory SQLite connection and the resulting schema inspected **before** the suite runs. `0016`'s missing comma produced 181 unrelated errors and cost a full cycle; that failure is cheap to prevent and expensive to discover. **This is the standard step for every migration from here on**, recorded in this ADR so it is a practice, not a one-off reaction.

---

## Consequences

- **`HeldActionStore` Protocol signature change** on four methods: `approve`/`approve_in_txn` gain `decided_by`; `cancel` gains `now` and `decided_by` (it currently takes neither); `expire_due` gains `decided_by`. `mark_executed`/`mark_executed_in_txn`/`create`/reads are unchanged.
- **`HeldAction` gains `decided_at: str | None = None` and `decided_by: str | None = None`** — defaulted and last, so every existing positional construction keeps working.
- **`_approve_transactional` will cross the parameter hard limit** (currently exactly 6; `HARD_PARAMS = 6`, `self` excluded — `tools/lint_sizes.py:28`). Predicted here rather than discovered mid-implementation, and fixed the way ADR-021's own amendment fixed the identical crossing in this same file: bundle into a frozen dataclass (11 §4), never relax the limit.
- **`tests/fixtures/held_action_store_contract.py`: 13 call-site edits**, no structural change. Both adapters subclass this one mixin, so this is the entire adapter-facing test cost.
- **`tests/fixtures/transactional_approve_worker.py`: zero edits.** Re-verified directly: it decorates `approve_in_txn`/`mark_executed_in_txn` with `*args, **kwargs` passthrough (`:60`, `:68`) and `__getattr__` (`:74`) — signature-agnostic by construction — and `make_held_action_approve_handler`'s factory signature is deliberately left unchanged (the principal arrives via `context.principal` at call time, not via the factory). **ADR-021's crash-kill proof is untouched by this ADR.**
- **No event publication** — that is ADR-026 (D3), out of scope here by explicit instruction. This ADR deliberately solves provenance in row state alone, which is also the right layering: a row must explain itself from its own state without replaying a bus.
- **`held_action.list` is deliberately unchanged**, and its schema gains no fields. Checked rather than assumed: that operation returns `HeldActionStore.pending()` only, and a `pending` row has NULL provenance by definition — surfacing the two columns there would add permanently-null fields to the API contract for zero information. The operation that would want them is a not-yet-existing "recently decided" view; building the response shape for an absent consumer is the speculative-structure anti-pattern this project rejects elsewhere. The columns are readable today via `explain`-style direct row access; a list operation can expose them when something actually renders them.
- **What gets harder:** every reader of a terminal `held_action` row must handle `NULL` provenance (pre-ADR-025 rows, and `pending` rows). Accepted as strictly simpler than a separate transitions table for a single-user system.
- **Not addressed:** the `redrive` reconciliation gap (`approved_not_executed()` still has zero callers) — unchanged from ADR-021/024, not this ADR's subject.
