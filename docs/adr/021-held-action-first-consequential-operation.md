# ADR-021 — `job.enable`/`job.disable`: the first real consequential operation, and how `held_action.approve` actually drives an effect

**Status:** accepted
**Date:** 2026-08-13
**Affected documents:** 07_DATABASE §5.5 (`held_action` schema — the `params` delta ADR-001 called "owed"), 12_API §7 (the gate contract, exercised for the first time), `src/kang/api/operations/held_action_ops.py`, `src/kang/api/registry/__init__.py`, `src/kang/kernel/runtime/composition.py`, `src/kang/adapters/sqlite/{held_action_store,job_store}.py`
**Cites:** ADR-001 (held-action crash semantics — the lifecycle and `commit_mode` split this ADR finally exercises), ADR-002 (the approval channel — `first_party_only` on `held_action.approve`, unchanged, reused as-is), 05_AGENTS Appendix D (the closed consequential-tool list; `job.enable`/`.disable` already named there), 12_API.md:182 ("`job.enable/disable` (consequential for core jobs)" — already spec'd, not invented here)
**Related:** [[019-scheduler-tick-loop.md]] (the live tick — named as the future home for the `redrive`-mode sweep, not built here), [[020-deadline-sweep-automatic-job.md]] (the last addition to the same `JOB_OPERATIONS`-style composition-root table this ADR extends the pattern of)

---

## Context

`held_action` has a fully built, presumably-tested lifecycle store (`create`/`get`/`approve`/`cancel`/`mark_executed`/`approved_not_executed`/`expire_due`/`pending`) — and zero live callers. Confirmed by grep, not assumed: nothing in `src/` ever raises `confirmation_required` or calls `held_actions.create()`. `held_action.approve`'s own handler docstring already names why: the row carries `operation` (registry name) and `action` (free text) but no column for the original request's params, so nothing can replay an approved action's effect — ADR-001's Consequences called this schema delta "owed... applied by the follow-through PR." Nothing on 05_AGENTS Appendix D's closed list has ever been built as a live operation, so the gate that would create a held action in the first place has never fired either.

This ADR is that follow-through, scoped to the smallest real instance: **`job.enable`/`job.disable`**, already named directly in 12_API §7 ("`job.enable/disable` (consequential for core jobs)") — not a new decision, an existing one finally exercised. It is deliberately the `transactional` commit_mode case, not `redrive`: no external adapter, no idempotency-contract proof required, using `JobStore` infrastructure that already exists (`enabled: bool` on `Job`, `set_quarantined`'s exact shape to mirror for a new `set_enabled`). `calendar.write` and the `redrive` path stay untouched — a harder, separate problem for its own session.

**A real mechanical gap found while designing this, not previously named anywhere:** every store method in this codebase (`milestone_store`, `job_store`, `held_action_store`, all of them) opens its own self-contained `BEGIN IMMEDIATE ... COMMIT`. There is no existing precedent for two different stores' writes sharing one transaction — but ADR-001 Amendment's `transactional` commit_mode promises exactly that ("the approval-flip and the effect commit in one `kang.db` transaction"). That promise has never been implemented; this ADR is what implements it, for the first time.

---

## Decision

### 1. The gate — `job.disable`'s own handler never disables anything

`job.disable`/`job.enable` are registered as ordinary commands (scope `jobs.write`, new — granted to `kang` for free via the existing `*` wildcard, no new principal grant needed) with `commit_mode="transactional"` declared on **their own** registry entry (this is what `held_action.approve` looks up later — not `held_action.approve`'s own entry, which already declares its own effect's `commit_mode` for its own status-flip write, per the existing code comment on that entry).

Called directly, the handler:
1. Validates `{job_id, reason}` (new request schema; `reason` is a required, UI-collected string — matching `HeldAction.reason`'s own docstring, "the requester's stated reasoning," not a synthesized one).
2. Builds a `HeldAction` (`operation="job.disable"`, `action=f"Disable job '{job_id}'"`, `principal` from `HandlerContext`, `reversibility="re-enable via job.enable"`, `params={"job_id": job_id}`, 24h expiry).
3. Calls `held_actions.create(...)`.
4. Raises `ApiError("confirmation_required", ..., details={the held action})` — an existing error code in `api/errors.py`'s closed enum, never raised by anything until now.

It **never** performs the effect itself, on any call — the effect only ever happens via step 2 below, reached exclusively through approval. This is a new shared pattern (`require_confirmation(...)`, a new `api/operations/consequential.py`) so the second future consequential operation doesn't reinvent it.

### 2. Driving the effect — extending `held_action.approve`, not re-dispatching

`held_action.approve`'s handler is rewritten to, once it resolves `commit_mode="transactional"` for the held action's named operation (looked up from the registry, not stored redundantly on the row):

1. `BEGIN IMMEDIATE` on the shared `kang.db` connection.
2. Call `held_action_store.approve_in_txn(...)` — a new private variant of the existing write, doing the same SQL without opening its own transaction.
3. Look up the operation's registered effect function in a new composition-root table, `TRANSACTIONAL_EFFECTS: dict[str, Callable[[Connection, dict], None]]` — the *exact same shape* `JOB_OPERATIONS` already established (ADR-006/ADR-020's precedent: a plain, greppable literal, SEC-005/P5's "answerable by reading" bar). For this ADR: `{"job.disable": ..., "job.enable": ...}`, each calling a new `JobStore.set_enabled_in_txn(conn, job_id, enabled)`.
4. Call `held_action_store.mark_executed_in_txn(...)`.
5. `COMMIT`. Any exception anywhere in 2–4 rolls back the whole thing — the row never durably leaves `pending`, which is ADR-001 Amendment's own promise made real: "a crash before commit is indistinguishable from still-pending" (no partial `approved`-with-no-effect state can persist).

This reuses `dispatcher.dispatch()`'s re-invocation pattern **not at all** — deliberately. Re-dispatching the target operation through the full pipeline (as `_make_job_runner` does for scheduled jobs) would open a *second*, separate transaction inside that handler's own store call, breaking the one-transaction promise. The effect functions in `TRANSACTIONAL_EFFECTS` are therefore plain store calls, not operations re-entering the dispatcher — `job.disable`'s registered handler (the gate) and its transactional effect function are two different pieces of code that happen to share a name in two different tables, and that distinction is deliberate, not an accident to clean up later.

### 3. Schema

`held_action` gains `params TEXT NOT NULL DEFAULT '{}'` (JSON, same pattern `notification.payload` already uses — `json.dumps`/`json.loads` at the SQLite adapter boundary, no new serialization idiom invented). `HeldAction.params: dict[str, Any]` on the domain dataclass, defaulting to `{}` for the (zero, confirmed) existing rows this migration touches — the same "no live callers yet, a plain copy is sufficient" precedent migration `0005` already used for `operation`.

---

## Options considered (the two real forks)

**Gate mechanism: dispatcher-generic vs. per-handler.** A generic dispatcher-level check (something registry-flagged, "this operation is consequential, gate it automatically") was considered and rejected: 12_API §2's thinness rule ("this layer contains NO domain logic... an `if` here about tasks or memory would be a defect") means the dispatcher cannot itself decide what a "held action" for `job.disable` should say — only the handler knows the right `action`/`reversibility` text. Per-handler it is, with the shared `require_confirmation` helper preventing the boilerplate from being reinvented per operation.

**Transaction sharing: a new cross-store transaction primitive vs. `_in_txn` method splits.** A general-purpose "run these N store calls in one transaction" primitive (a context manager any future code could use) was considered and rejected as premature infrastructure for a two-caller need — the same "don't build a primitive for one caller" instinct ADR-019 already applied to the tick loop. `_in_txn` splits on exactly the two methods this ADR needs (`HeldActionStore.approve`/`mark_executed`, `JobStore.set_enabled`) are the minimum real surface; a general primitive can be extracted later if a third real caller appears, per the smell checklist's own "a port with exactly one conceivable implementation" caution — this is deliberately the same shape, inverted (build the narrow thing now, generalize when a second real need shows up, not before).

---

## Consequences

- **New module `api/operations/job_ops.py`** — `job.disable`/`job.enable`'s gate handlers.
- **New module `api/operations/consequential.py`** — `require_confirmation(...)`, the shared gate helper every future consequential operation reuses.
- **`held_action_ops.py`'s `make_held_action_approve_handler` signature changes** — needs the raw connection, the registry's `commit_mode` lookup, and `TRANSACTIONAL_EFFECTS`, in addition to `held_actions`/`clock`. A real, visible signature change, not hidden.
- **New scope `jobs.write`** — `permissions.toml` needs no edit (`kang`'s `*` already covers it); named here because CLAUDE.md §4 treats a new scope kind as an authority-path change regardless of who currently holds it.
- **`held_action` schema gains `params`** — the delta ADR-001 named as owed, finally applied, following migration `0005`'s own "no live rows to backfill" precedent.
- **`JobStore` gains `set_enabled`/`set_enabled_in_txn`** — mirrors `set_quarantined`'s exact shape.
- **What gets harder:** `held_action.approve` is no longer a one-line status flip — it now branches on the target operation's `commit_mode` and, for `transactional`, owns a real multi-store transaction. Accepted: this is the honest shape of "approval drives an effect," not incidental complexity — ADR-001 always said it would look like this, this ADR is what finally builds it.
- **Explicitly NOT decided/built here, flagged not guessed:**
  - **`redrive` mode and `calendar.write`** — untouched. `approved_not_executed()`'s sweep still has no caller; ADR-019's live tick remains the named future home for it, not wired now.
  - **No event publication** (`job.updated`/similar) for enable/disable — no current consumer names a need for one; building it speculatively would repeat the "enum allows it" anti-pattern this project already rejected for `project.pause` etc. Revisit if a real UI/notification need appears.
  - **No de-duplication of repeated `job.disable` calls carrying the same idempotency key.** Confirmed by reading `dispatch.py::_execute`: `_store_idempotent` only runs on the success path — a handler that raises `ApiError` (including `confirmation_required`) is never cached, so a retried `job.disable` call creates a second `held_action` row rather than replaying the first. Not a safety issue (Kang can cancel the duplicate; nothing executes twice), but a real, minor, named rough edge — not silently absent.

## Amendment — 2026-08-13 — found in implementation: two parameter-count hard-limit violations

**Status:** accepted (found while building, same session).

`require_confirmation`'s naive first signature (9 parameters) and `job_ops.py`'s internal `_make_gate_handler` (7 parameters) both crossed the size lint's hard parameter limit (11 §4: beyond a few parameters, a dataclass). Fixed the way the codebase already fixes this everywhere else, not by relaxing the limit: `ConfirmationDeps` (the collaborators: `held_actions`/`clock`/`new_id`) and `ConfirmationRequest` (the held action's own content: `operation`/`action`/`reason`/`reversibility`/`params`) bundle `require_confirmation` down to 3 parameters; `job_ops.py`'s `_GateSpec` does the same for `_make_gate_handler`. `composition.py` also crossed the file-level 800-line hard limit the moment this ADR's wiring landed — split out `_build_consequential_handlers`, mirroring `_build_project_cluster_handlers`'s own precedent (ADR-018's session already established this exact fix shape for this exact file).

## Live verification (2026-08-13)

Against a real, throwaway `%KANG_HOME%` (never the real one), a real `python -m kang.kernel.runtime.composition` process, driven entirely over real HTTP — not just the automated integration tests above:

- `job.disable {job_id: "deadline_sweep", reason: "..."}` returned a real `confirmation_required` error with a real held-action id in `details`; `system.health` confirmed `deadline_sweep.enabled` was still `true` — the gate created intent, nothing executed.
- `held_action.approve {id}` returned `{"status": "executed"}`; `system.health` immediately after showed `deadline_sweep.enabled: false` — the real effect, driven through the real transactional path, not a test double.
- The full round trip was proven both directions: `job.enable` → approve → `system.health` showed `enabled: true` again.
- Direct inspection of the real `kang.db`: both `held_action` rows carry `status='executed'` and `params='{"job_id": "deadline_sweep"}'` — the schema delta genuinely round-trips.
- The real audit log shows the complete honest trail: `job.disable.dispatched`/`.failed` (the gate's `confirmation_required` is correctly recorded as the operation's own outcome — it never completes successfully, by design), `held_action.approve.dispatched`/`.ok` twice — one full, real, attributable causal chain.
- Process stopped, throwaway `%KANG_HOME%` deleted. The real, persistent Core was not touched by this verification (it still needs a restart to run this code — a separate, deliberate step, same discipline as ADR-008/019/020).
