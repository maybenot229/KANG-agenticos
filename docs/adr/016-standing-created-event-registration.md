# ADR-016 — Standing pattern: registering a new entity's first `.created` event, applied to `goal.created`

**Status:** accepted
**Date:** 2026-08-08
**Decides:** the fourth instance of the gap ADR-013/014/015 each closed individually (`project`, `competition`, `milestone`) — ADR-015's own Consequences section flagged this exact moment: *"if a fourth M5-scoped entity needs the same treatment... it might warrant a single standing ADR covering the shape generically."* This is that entity (`goal`), and this is that standing ADR.
**Affected documents:** 15_EVENT_BUS §6.1/§6.3 (closed taxonomy gains one entry: `goal.created`), 07_DATABASE §5.6 (the `goal` table's change-capture trigger, missing since 0006 — added alongside this ADR's implementation), 13_TESTING §16.2 (payload-sufficiency obligation follows for a recovery-grade type).
**Cites:** ADR-013/014/015 (the three prior instances this ADR generalizes — their reasoning is not re-argued here, it is promoted to a standing rule), EB-006 §6.1 (closed taxonomy; additions require an ADR), EB-004 (the five-step publish order — `commit_state` only runs inside `bus.publish`), 07_DATABASE §5.2 goal table comment ("Not a migration; not applied here — this is intent for M5's first runtime population").

---

## 1. Context

`goal` (`migrations/0006_domain_entities.sql`) has existed since M5 alongside `project`/`competition`/`milestone`, with the identical shape of gap ADR-013/014/015 already closed three times: real schema, no domain-layer code above it, no change-capture trigger (0006 wired triggers only for `task`/`deadline`), no registered event type. `goal` is self-standing (no required FK, like `project`/`competition` — not `milestone`'s `NOT NULL REFERENCES project(id)` shape): `project.goal_id` optionally points *at* a goal (`ON DELETE SET NULL`), but a goal itself depends on nothing.

`goal` is not named on 03_ROADMAP's M4 objective line, the same gap already noted for `milestone` in ADR-015 §1 and named again in the 2026-08-08 session handoff (§4 item 6, the M4/M5 doc-tension). It is nonetheless real, committed M5 scope: 07_DATABASE §5.2's own `goal` table comment states plainly *"Not a migration; not applied here — this is intent for M5's first runtime population,"* and names the exact seed content (quarter/year goals per the user-profile intake, `docs/guides/user-profile-intake-2026-07.md` D15, ADR-003's own `horizon` ruling). The schema was built expecting this write path to arrive.

### Why this ADR is generic, not a fourth near-identical document

ADR-013, ADR-014, and ADR-015 are, sentence for sentence, the same ruling: a self-standing or FK-anchored entity gets its first write path; EB-004 structurally requires a registered event to commit through; the entity's row is Tier-1 truth (referenced by, or referencing, other real schema) so `recovery_grade=True`; `.updated` stays unregistered because no transition operation exists yet (PS-006 non-speculation); a missing change-capture trigger from 0006 is closed in the same migration. Three instances established the pattern is real and stable, not coincidental. Writing a fourth copy of this prose would itself be the "second name for an existing concept" defect 14_CLAUDE.md §5/§10 warns against — this time applied to *decisions* instead of *code*. This ADR states the rule once, applies it to `goal.created` as its first instance, and stands as the authority for any future entity in the same shape (a fifth, sixth, ... instance cites this ADR rather than writing a new one, unless its shape genuinely differs — as `milestone`'s FK-required shape did from `project`/`competition`, which stayed worth noting inline even under this rule).

---

## Ruling

### The standing rule

When a real schema entity (already migrated, no domain-layer code above it) gets its first write operation:

1. **Register `<entity>.created`, recovery-grade, full-row payload.** The row is Tier-1 truth the moment it is addressable state something else can reference or a view can depend on — the same test ADR-004 first applied to `deadline`, reapplied identically since. This is the default; do not re-derive it from scratch.
2. **Do not register `<entity>.updated`, `.deleted`, or any other lifecycle event** until a real operation exists to write through it. Registering ahead of a consumer is PS-006's speculative-structure anti-pattern regardless of how likely a future consumer seems.
3. **Add the missing change-capture trigger in the same migration** that adds the write path, if 0006 (or whichever migration created the table) did not already wire one — mirroring `trg_task_capture_*`/`trg_deadline_capture_*` exactly, narrowed to the entity's own columns.
4. **Add a recovery applier and a payload-sufficiency fixture** in the same pass — EB-006 §6.3's obligation for any recovery-grade type, non-negotiable, proven by test not asserted in prose.
5. **If the entity has a required FK to a parent row** (as `milestone.project_id` does), the payload-sufficiency fixture needs `seed_sql` for that parent — `goal` does not, being self-standing, so this step is inapplicable to this instance but stays part of the rule for the next one that needs it.

A future entity that fits this shape may cite this ADR directly in its implementing commit/PR instead of filing a new one. **File a new ADR only if the shape genuinely differs** from all four instances on record (e.g., a required multi-parent FK, a non-`created_at`/`revision`-shaped sync quartet, or a case where recovery-grade is genuinely arguable rather than a re-application of the same test).

### Applying the rule to `goal.created`

| Type | Category | `recovery_grade` | Why |
|---|---|---|---|
| `goal.created` | domain | **true** | A goal row is real, addressable state — `project.goal_id` can reference it, and 07 §5.2 already commits to this table being populated with Kang's real quarter/year goals at M5's first runtime use. Losing one on crash recovery silently drops a real, referenced goal. Full-row payload. Mirrors `project.created`/`competition.created` exactly (self-standing, no required FK — unlike `milestone.created`). |

`goal.updated` is deliberately NOT registered — no status-transition operation exists yet (`goal.achieve`/`.revise`/`.retire` are all real enum values in the schema's `status` CHECK, with zero operations behind any of them). Same non-speculation discipline as `project.updated`/`competition.updated`/`milestone.updated`.

---

## Consequences

- **A payload-sufficiency fixture becomes owed** (13_TESTING §16.2) for `goal.created` — added alongside this ADR's implementation, mirroring the `project.created`/`competition.created` fixtures (no `seed_sql` needed — self-standing, same as those two).
- **A recovery applier becomes owed** — mirrors `_apply_project_upsert`/`_apply_competition_upsert`.
- **`goal`'s change-capture trigger, missing since `0006`, is added in the same migration** that gives it its first write path.
- **`goal.updated` stays unregistered** — the next increment that adds a status-transition operation (`achieve`/`revise`/`retire`) files an ADR against real code, citing this one for the pattern rather than re-deriving it.
- **This ADR is now the standing citation for the pattern.** A fifth instance (if one arrives) implements against this ADR's rule directly; a new ADR is filed only if its shape genuinely diverges from the four now on record (`task`, `deadline` under ADR-004; `project`/`competition`/`milestone` under ADR-013/014/015; `goal` here).
- **07_DATABASE §5.2's own stated intent — real seed goals at M5's first runtime population — becomes actionable** now that `goal.create` exists as a real operation. This implementation live-verified the write path by creating those exact rows (quarter="Ship KANG v0.1", the ranked year list, empty life) against a throwaway `KANG_HOME`, then tore it down — the doc already names exactly what to seed, but whether and when to write them into Kang's real, persistent `KANG_HOME` is Kang's own call, not this ADR's to make.

---

*When code and this document disagree, one of them is wrong on purpose — file the ADR.*
