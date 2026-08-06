# ADR-014 — Register `competition.created`: the Competitions domain's first write path

**Status:** proposed
**Date:** 2026-08-06
**Decides:** ADR-004's other explicitly-deferred item — *"`competition.*` events are NOT registered... Whichever increment adds [project/]competition write behavior files that ADR"*. ADR-013 closed the `project` half; this closes the `competition` half.
**Affected documents:** 15_EVENT_BUS §6.1/§6.3 (closed taxonomy gains one entry), 07_DATABASE §5.6 (the `competition` table's change-capture trigger, missing since 0006 — added alongside this ADR's implementation), 13_TESTING §16.2 (payload-sufficiency obligation follows for a recovery-grade type).
**Cites:** ADR-004 (the deferral this ADR closes: *"M5 tracks competitions that already exist as rows; evaluation, discovery, and scouting are Phase 3... registering ahead of a real consumer is the speculative-structure anti-pattern PS-006 rejects"*), ADR-013 (the identical ruling for `project`, followed here line for line — same reasoning, same structure, same options considered and rejected for the same reasons), EB-006 §6.1 (closed taxonomy; additions require an ADR), EB-003 (recovery-grade REQUIRED for "task/deadline/competition truth mutations" — competition is named explicitly here, unlike project in ADR-013), EB-004 (the five-step publish order — `commit_state` only runs inside `bus.publish`).

---

## 1. Context

`src/kang/domain/competitions/` has been an empty stub since M5's schema migration (`0006_domain_entities.sql`) landed the real `competition` table (`id, name, url, status, evaluation, result, project_id` + sync quartet) with no domain-layer code above it. `03_ROADMAP.md`'s M4 objectives name "tasks/projects/deadlines/competitions (**tracking only**)" explicitly — the same scope line ADR-013 built `project.create`/`.list` against. `evaluation`/`result` are the table's own Phase-3 columns (07_DATABASE §5.2's comment: "M5 tracks competitions that already exist as rows. Discovery, evaluation, and scouting are Phase 3... `evaluation` and `result` are columns awaiting those consumers, deliberately unwritten until then") — tracking (create + list of a competition Kang already knows about) is real M4/M5 scope; discovery/evaluation is not, and this ADR does not touch it.

Building `competition.create` means writing to `competition` for the first time, and per EB-004's five-step write order, that write cannot commit without a registered, publishable event type. No `competition.*` type exists — ADR-004 named this gap explicitly and deferred it to whichever increment adds real write behavior. This is that increment, for `competition` (ADR-013 was the same increment for `project`).

The same secondary gap ADR-013 found for `project` recurs here: `0006_domain_entities.sql` wired change-capture triggers for `task`/`deadline` only (the two entities with a write path at the time), never for `competition`. Its trigger arrives in the same migration as this ADR's implementation, for the same reason ADR-013 gave.

`CompetitionsScreen.tsx`'s existing docstring claims *"tracking and discovery are both later-phase work (Phase 2 of the roadmap)"* — checked against `03_ROADMAP.md` directly (not assumed), this over-states the gap: discovery is Phase 2/M7; tracking is M4/M5, same scope line as `project`/`deadline`. That docstring is corrected as part of this ADR's implementation, not left to silently contradict the roadmap it cites.

---

## Ruling — register `competition.created`

### Options

Identical to ADR-013's own options, decided the same way, for the same reasons — restated briefly rather than re-argued from scratch, since re-deriving an already-settled argument would itself be the kind of drift this project's ADR discipline exists to prevent.

**A — Register `competition.created` only, recovery-grade (recommended).** Mirrors `project.created`/`deadline.created`/`task.created`. `competition.updated` is NOT registered — no status-transition operation exists yet (no `competition.evaluate`/`.enter`/`.submit`/etc.), and those are exactly the Phase-3 operations this ADR is not building. EB-003 names "competition truth mutations" explicitly (unlike `project`, which ADR-013 had to argue by analogy) — the recovery-grade call here is textually direct, not inferred.

**B — Register `competition.created` and `competition.updated` together.** Rejected for the identical reason ADR-013 rejected it for `project`: `competition.updated` has zero consumer at registration time, and registering ahead of one is the speculative-structure anti-pattern ADR-004 already named and avoided once for this exact entity.

**C — Skip the bus; write directly to `competition`.** Not a real option — EB-004's write order is structural, not a convention. Rejected outright, as ADR-013 rejected it for `project`.

### Decision

**Adopt A.** Register one type:

| Type | Category | `recovery_grade` | Why |
|---|---|---|---|
| `competition.created` | domain | **true** | EB-003 names "competition truth mutations" as REQUIRED recovery-grade directly. Full-row payload (`id`/`name`/`url`/`status`/`evaluation`/`result`/`project_id` + sync quartet — `evaluation`/`result` always `null` from this handler, since nothing populates them yet, but present in the payload shape for when Phase 3 does). Mirrors `project.created`/`task.created`/`deadline.created`. |

---

## Consequences

- **A payload-sufficiency fixture becomes owed** (13_TESTING §16.2) for `competition.created` — added alongside this ADR's implementation, mirroring the `project.created` fixture ADR-013 added.
- **A recovery applier becomes owed** (`adapters/sqlite/recovery.py`) — mirrors `_apply_project_upsert`.
- **`competition`'s change-capture trigger, missing since `0006`, is added in the same migration** that gives it its first write path.
- **`competition.updated` stays unregistered** — the next increment that adds a status-transition or evaluation-write operation (Phase 3 territory) files that ADR against real code.
- **`CompetitionsScreen.tsx`'s docstring is corrected**: tracking is real M4/M5 scope (this ADR proves it, in code), discovery remains the actual Phase-2 gap.
- **ADR-004's deferred item is now fully closed** — both halves (`project`, `competition`) registered, each by its own ADR, neither guessed ahead of a real consumer.
- **What gets harder:** a second recovery-grade type with a full-row payload sitting mostly `null` (evaluation/result) in the 90-day event-log window until Phase 3 populates them — the same accepted "transient operational redundancy" ADR-004/ADR-013 both named.

---

*When code and this document disagree, one of them is wrong on purpose — file the ADR.*
