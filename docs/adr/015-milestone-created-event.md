# ADR-015 — Register `milestone.created`: the Milestones sub-domain's first write path

**Status:** proposed
**Date:** 2026-08-07
**Decides:** the same class of gap ADR-013/ADR-014 closed for `project`/`competition` — no `milestone.*` event type exists, and `milestone.create` cannot commit without one (EB-004).
**Affected documents:** 15_EVENT_BUS §6.1/§6.3 (closed taxonomy gains one entry), 07_DATABASE §5.6 (the `milestone` table's change-capture trigger, missing since 0006 — added alongside this ADR's implementation), 13_TESTING §16.2 (payload-sufficiency obligation follows for a recovery-grade type).
**Cites:** ADR-013 (`project.created` — the direct template this ADR follows line for line), ADR-014 (`competition.created` — same pattern, second precedent), EB-006 §6.1 (closed taxonomy; additions require an ADR), EB-004 (the five-step publish order), 07_DATABASE Appendix B (`project → milestone` is a pre-sanctioned CASCADE — cited, not re-decided: milestone rows die with their project, no orphan-handling logic owed here).

---

## 1. Context

`milestone` (`migrations/0006_domain_entities.sql`) has existed since M5 alongside `project`/`competition`, with the identical shape of gap ADR-013 and ADR-014 already closed twice this session: real schema, `NOT NULL REFERENCES project(id) ON DELETE CASCADE`, no domain-layer code above it, no change-capture trigger (0006 wired triggers only for `task`/`deadline`, the two entities with a write path at the time), and no registered event type.

Unlike `project`/`competition`, `milestone` is not itself one of 03_ROADMAP's M4 objective-line entities ("tasks/projects/deadlines/competitions") — it is `project`'s own sub-resource (07 §5.2's own grouping, and Appendix B's sanctioned-CASCADE list treats `project → milestone` as a unit). Building it now is not scope-creep past that line: a project's tracked milestones are the natural depth-2 view 09_UI §2's hub-and-spoke shape already calls for (domain → entity → detail, max depth 3) once a domain has real entities to click into — which Projects now does (ADR-013).

---

## Ruling — register `milestone.created`

### Options

Identical structure to ADR-013/ADR-014's own options; not re-argued from scratch for the third time.

**A — Register `milestone.created` only, recovery-grade (recommended).** A milestone row is Tier-1 truth by the same argument as `project`: it is real, addressable state a project's own view depends on, and losing one on crash recovery would silently corrupt that project's milestone list. `milestone.updated` is deliberately NOT registered — no status-transition operation exists yet (no `milestone.reach`/`.miss`/`.drop`), same non-speculation discipline as `project.updated`/`competition.updated`.

**B — Register both `.created` and `.updated`.** Rejected for the same reason as both prior ADRs: `.updated` would have zero consumer at registration time.

**C — Skip the bus.** Not a real option — EB-004's write order is structural. Rejected outright, as in both prior ADRs.

### Decision

**Adopt A.** Register one type:

| Type | Category | `recovery_grade` | Why |
|---|---|---|---|
| `milestone.created` | domain | **true** | A milestone row is real, addressable project state; losing one on crash recovery silently corrupts that project's own milestone list. Full-row payload. Mirrors `project.created`/`competition.created` exactly. |

---

## Consequences

- **A payload-sufficiency fixture becomes owed** (13_TESTING §16.2) for `milestone.created` — added alongside this ADR's implementation, mirroring the `project.created`/`competition.created` fixtures.
- **A recovery applier becomes owed** — mirrors `_apply_project_upsert`/`_apply_competition_upsert`.
- **`milestone`'s change-capture trigger, missing since `0006`, is added in the same migration** that gives it its first write path.
- **`milestone.updated` stays unregistered** — the next increment that adds a status-transition operation (`reach`/`miss`/`drop`) files that ADR against real code.
- **Third instance of the identical pattern this session** (`project`, `competition`, now `milestone`) — worth naming plainly: if a fourth M5-scoped entity needs the same treatment, that is the point at which "register the write-path event" stops being novel enough to deserve its own ADR each time and might warrant a single standing ADR covering the shape generically. Not decided here; flagged for whoever hits the fourth case.

---

*When code and this document disagree, one of them is wrong on purpose — file the ADR.*
