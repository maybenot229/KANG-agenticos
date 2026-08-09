# ADR-018 — Standing pattern: registering `<entity>.updated` for a status transition, applied to milestone/goal/project

**Status:** accepted
**Date:** 2026-08-09
**Decides:** the mirror-image gap ADR-013/014/015/016 each named and deliberately left open — "`X.updated` is deliberately NOT registered... the next increment that adds a status-transition operation files the ADR." That increment is now, for three entities at once: milestone (`reach`/`miss`/`drop`), goal (`achieve`/`revise`/`retire`), project (`complete`).
**Affected documents:** 15_EVENT_BUS §6.1/§6.3 (closed taxonomy gains three entries: `milestone.updated`, `goal.updated`, `project.updated`), 13_TESTING §16.2 (payload-sufficiency obligation follows for each).
**Cites:** ADR-016 (the standing-ADR precedent this one follows — one document, generalized, instead of three or six near-identical ones), `deadline_service.py`'s `mark_alerted`/`mark_met`/`mark_missed` (the exact shape every transition function here mirrors — validate current status, `replace()` to the new one, no side effects), `task.complete` (2026-08-09, the exact API-handler shape every operation here mirrors — fetch, transition, publish, commit via the store's `update()`).

---

## 1. Context

Three entities built this session (`milestone`/ADR-015, `goal`/ADR-016) or the session before (`project`/ADR-013) shipped tracking-only: create + list, no way to mark anything done. Each ADR said so explicitly and named the real enum values already sitting unused in the schema — `milestone.status IN ('pending','reached','missed','dropped')`, `goal.status IN ('active','achieved','revised','retired')`, `project.status IN ('active','paused','completed','archived','abandoned')` — and each deferred the transition operation "to the next increment that adds one."

Unlike `task.complete` (built earlier this session), where `TaskStore.update()` and `complete_task()` already existed, fully tested, waiting for an API operation — **none of that exists for these three.** `MilestoneStore`/`GoalStore`/`ProjectStore` have `create` + list only, no `update()` at any layer (port, SQLite, fake). No transition function exists in any of the three domain services. This ADR's implementation builds the full stack for each, not just the API layer.

### Scope ruling — which verbs, and why not the full graph

**Milestone and goal get their full named verb sets** (three each) because both are already explicitly named, symmetric-cost, and terminal-from-one-state: milestone's `pending → {reached|missed|dropped}` and goal's `active → {achieved|revised|retired}` are each three structurally-identical transitions off the same starting status, no different in build cost whether one or three are built.

**Project gets `complete` only**, not the full five-status graph (`pause`/`resume`/`archive`/`abandon` stay unbuilt). No prior document names a specific project verb set the way milestone/goal's own ADRs did (ADR-013 only ever used `project.archive`/`.pause`/"etc." as illustrative examples, never a ruling). Building all four remaining transitions now, with no named consumer for `pause`/`resume`/`archive`/`abandon` beyond "the enum allows it," is exactly the speculative-structure anti-pattern ADR-004 rejected for `competition.*` and every `.updated` deferral since — applied here to transitions instead of whole entities. `project.complete` is the one with an obvious, immediate daily-use case (mirroring `task.complete`'s own shape and worth for the same reason); the rest is a real, named, deliberate gap.

---

## Ruling

### The standing rule (generalizing ADR-016's `.created` pattern to `.updated`)

When a tracking-only entity's first status-transition operation lands:

1. **Register `<entity>.updated`, recovery-grade, full-row payload** — same recovery-grade argument as the entity's own `.created` type (losing the transition on crash recovery silently reverts a completed/achieved/reached row to its prior state, corrupting whatever depends on it).
2. **The store gains `update(entity) -> entity`** with the exact optimistic-concurrency contract `TaskStore.update()`/`DeadlineStore.update()` already establish: `WHERE id = ? AND revision = ?`, `revision = revision + 1` in SQL, `RevisionConflictError` on a stale write, `NotFoundError` on an unknown id — proven once per store by a port-contract suite (mirroring `task_store_contract.py`), run identically against the fake and the real adapter (13 §2.3).
3. **The domain service gains one transition function per verb**, each mirroring `mark_alerted`'s exact shape: validate the current status accepts this transition, `replace()` to the new one, stamp `updated_at` (D009's sync quartet — `complete_task`'s own 2026-08-09 bugfix is the reason this is stated explicitly here rather than assumed).
4. **The API operation mirrors `make_task_complete_handler`'s exact shape**: fetch, transition (typed domain error -> `invalid_request`), publish under the entity's own principal, commit via the store's `update()` (a `RevisionConflictError` from a genuine concurrent write -> `conflict` with the current revision, API-006). Same scope family the entity's own `.create` operation already uses (`milestones.write`/`goals.write`/`projects.write`) — no new authority.
5. **A recovery applier + payload-sufficiency fixture become owed**, same EB-006 §6.3 obligation every recovery-grade type carries.

A future entity's first transition cites this ADR directly rather than earning its own document, unless its shape genuinely diverges (a transition needing a second entity's state, e.g., or a consequential action landing on 05_AGENTS Appendix D's closed list — none of these six do).

### Applying the rule

| Type | Category | `recovery_grade` | Verbs it carries |
|---|---|---|---|
| `milestone.updated` | domain | **true** | `reach` (`pending → reached`), `miss` (`pending → missed`), `drop` (`pending → dropped`) |
| `goal.updated` | domain | **true** | `achieve` (`active → achieved`), `revise` (`active → revised`), `retire` (`active → retired`) |
| `project.updated` | domain | **true** | `complete` (`active → completed`) only — see Context's scope ruling |

---

## Consequences

- **Three payload-sufficiency fixtures become owed** (13_TESTING §16.2), mirroring the entities' own `.created` fixtures — no `seed_sql` needed for goal/project (self-standing); milestone's fixture needs the same parent-project seed its `.created` fixture already uses.
- **Three recovery appliers become owed** (`_apply_milestone_upsert`/`_apply_goal_upsert`/`_apply_project_upsert`, mirroring `_apply_task_upsert`/`_apply_deadline_upsert` exactly).
- **Three stores gain `update()`** — the first update path any of the three has ever had; each gets its own port-contract suite (mirroring `task_store_contract.py`), not hand-rolled per-store tests.
- **`milestone.reach`/`.miss`/`.drop`, `goal.achieve`/`.revise`/`.retire`, `project.complete` become real registered operations** — six new operations, one commit-per-entity (three coherent slices, matching this session's own established discipline).
- **`project.pause`/`.resume`/`.archive`/`.abandon` stay unbuilt** — a real, named gap; the next increment that needs one of them files against real demand, citing this ADR for the pattern rather than re-deriving it.
- **`milestone.updated`/`goal.updated`/`project.updated` become the standing citation** for this pattern, same as ADR-016 already is for `.created` — a seventh, eighth, ninth entity's own first transition builds directly against this ADR's rule.

---

*When code and this document disagree, one of them is wrong on purpose — file the ADR.*
