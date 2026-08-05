# ADR-013 — Register `project.created`: the Projects domain's first write path

**Status:** accepted
**Date:** 2026-08-06
**Decides:** ADR-004's own deferred item — *"`competition.*` events are NOT registered... Whichever increment adds [project/]competition write behavior files that ADR"* — this is that increment, for `project`.
**Affected documents:** 15_EVENT_BUS §6.1/§6.3 (closed taxonomy gains one entry), 07_DATABASE §5.6 (the `project` table's change-capture trigger, missing since 0006 — added alongside this ADR's implementation), 13_TESTING §16.2 (payload-sufficiency obligation follows for a recovery-grade type).
**Cites:** ADR-004 (the exact precedent and reasoning template this ADR follows — `deadline.created`'s registration, and the explicit deferral this ADR now closes), EB-006 §6.1 (closed taxonomy; additions require an ADR), EB-003 (recovery-grade REQUIRED for "task/deadline/competition truth mutations" — this ADR's own reasoning for why `project` belongs in that set too, even though EB-003's sentence doesn't name it explicitly), EB-004 (the five-step publish order — `commit_state` only runs inside `bus.publish`, so a domain write cannot commit without a registered type to publish under).

---

## 1. Context

`src/kang/domain/projects/` has been an empty stub (`__init__.py`, `__all__: list[str] = []`) since M5's schema migration (`0006_domain_entities.sql`) landed the real `project`/`milestone`/`goal`/`competition` tables with no domain-layer code above them. Building the first real Projects-domain operation (`project.create`, "tracking only" per 03_ROADMAP's M4/M5 objective line) means writing to `project` for the first time — and per EB-004's five-step write order, `commit_state` only ever runs *inside* `bus.publish`, so this write cannot commit without a registered, publishable event type.

No `project.*` event type exists in the closed taxonomy (`kernel/bus/event_registry.py`) — confirmed by grep, not assumed. ADR-004 named this gap explicitly for `competition.*` and, by the same reasoning, it applies to `project.*` too: *"M5 tracks competitions that already exist as rows... With nothing in M5 writing [project/]competition state, there is nothing to publish, and registering ahead of a real consumer is the speculative-structure anti-pattern PS-006 rejects. Whichever increment adds [project/]competition write behavior files that ADR."* This is that increment.

A second, smaller gap surfaced while reading `0006_domain_entities.sql` directly (not assumed from the doc alone): it added change-capture triggers (`trg_task_capture_*`, `trg_deadline_capture_*`) for `task` and `deadline` — the two entities that already had write paths at the time — but none for `project`/`milestone`/`goal`/`competition`, which had no write path yet. 07_DATABASE §5.6 states change capture is "populated by narrow AFTER-triggers on synchronizable tables... exercised (and tested) from day one." Since this ADR's implementation gives `project` its first real write path, the matching capture trigger is added in the same migration — filling in already-specified infrastructure (07 §5.6), not inventing new design.

---

## Ruling — register `project.created`

### Options

**A — Register `project.created` only, recovery-grade (recommended).**

Mirrors `task.created`/`deadline.created` exactly: full-row payload, `recovery_grade=True`.

- *For:* a `project` row is Tier-1 truth by the same argument ADR-004 made for `deadline` — it is referenced by `task.project_id`, `competition.project_id`, and `deadline.project_id` (all real foreign keys in the already-migrated schema), so losing one on crash recovery doesn't just lose a project, it silently orphans or corrupts the read-shape of every task/competition/deadline that pointed at it. EB-003's sentence names "task/deadline/competition truth mutations" without saying "project" explicitly, but the underlying test — *would losing this row silently corrupt other truth?* — is met identically. `project.updated` is deliberately NOT registered here: this pass's scope is "tracking only" (create + list), no status-transition operation exists yet (no `project.archive`/`.pause`/etc.), and registering an event type with no consumer is exactly the speculative-structure anti-pattern ADR-004 rejected for `competition.*` — the same discipline, applied to this ADR's own scope this time. Whichever future increment adds a project status-transition operation files the ADR for `project.updated` then, same as this one does for `project.created` now.
- *Against:* one more type in the closed taxonomy; the usual, accepted cost of extending it (ADR-004 accepted the same cost for five types at once).

**B — Register both `project.created` and `project.updated` now, for symmetry with `task`/`deadline`.**

- *For:* `task` and `deadline` both have `.created`/`.updated` pairs; matching that shape now avoids a second small ADR later.
- *Against:* `project.updated` would have zero consumer at registration time — no operation in this pass mutates an existing project. ADR-004 rejected exactly this shape for `competition.*` ("registering ahead of a real consumer is the speculative-structure anti-pattern PS-006 rejects"); adopting it here for `project.updated` would repeat the mistake ADR-004 named and avoided, not follow its precedent. Rejected.

**C — Skip the event/bus path; write directly to `project` from the operation handler.**

- *For:* smallest possible diff — no registry entry, no recovery applier, no payload-sufficiency test.
- *Against:* violates EB-004's five-step write order structurally, not just by convention — `commit_state` is a parameter *of* `bus.publish`, not a free-standing function a handler can call on its own. This isn't a style preference to relax; it is the mechanism every other domain write (`task.create`, `deadline.create`) already goes through, and bypassing it for `project` alone would create exactly the "one concept, two names/two paths" defect 14_CLAUDE.md §5 warns against. Rejected outright — not a real option, included only to make explicit why it isn't one.

### Decision

**Adopt A.** Register one type:

| Type | Category | `recovery_grade` | Why |
|---|---|---|---|
| `project.created` | domain | **true** | A project row is Tier-1 truth, referenced by `task`/`competition`/`deadline` FKs already live in the schema; losing one on crash recovery would silently corrupt those other entities' read-shape. Full-row payload. Mirrors `task.created`/`deadline.created` exactly (ADR-004's own template). |

---

## Consequences

- **A payload-sufficiency fixture becomes owed** (13_TESTING §16.2) for `project.created` — added alongside this ADR's implementation in `tests/suites/replay/test_payload_sufficiency.py`, following the existing `deadline.created` fixture shape exactly.
- **A recovery applier becomes owed** (`adapters/sqlite/recovery.py`'s `_APPLIERS` map) — `EB-006 §6.3`: a recovery-grade type without one is a registry defect. Added in the same pass, mirroring `_apply_deadline_upsert`.
- **`project`'s change-capture trigger, missing since `0006`, is added in the same migration** that gives `project` its first write path — closing the 07 §5.6 gap named in Context, not a separate decision.
- **`project.updated` stays unregistered**, same discipline ADR-004 used for `competition.*` — the next increment that adds a project status-transition operation is the one that files that ADR, against real code, not guessed here.
- **What gets harder:** one more recovery-grade type means one more full-row payload living in the 90-day event-log window, duplicating data already in `kang.db` — the same accepted "transient operational redundancy" ADR-004 named for its own five types.

---

*When code and this document disagree, one of them is wrong on purpose — file the ADR.*
