# ADR-004 — Register the M5 event types: deadline lifecycle, notification, plan

**Status:** accepted
**Date:** 2026-07-26
**Affected documents:** 15_EVENT_BUS §6.1/§6.3 (the closed taxonomy gains five entries), 05_AGENTS Appendix F (event-trigger table — already names three of them), 13_TESTING §16 (payload-sufficiency obligations follow)
**Cites:** EB-006 §6.1 (closed taxonomy; additions require an ADR — this is that ADR), EB-003 (the dual-duty doctrine and the `recovery_grade` contract), EB-008 (the three-log boundary), 15 §6.2 (the `notification.requested` accelerant ruling — cited, not reopened)
**Related:** [[005-notification-queue-schema]] (the durable row `notification.requested` accelerates)

---

## Context

M5 must prove a lifecycle end to end: **create → approach → notification per
ladder → acknowledge**, fully offline (18 §3 M5's "Proves"). Every step that
crosses the bus needs a registered event type, because EB-006 §6.3 makes
publishing an unregistered type a bug-level failure rejected at validation.

The registry today holds exactly two types: `task.created`, `task.updated`.

Three of the types M5 needs are already named in constitutional text but were
never formally registered: `deadline.approaching` and `plan.generated`
(05_AGENTS Appendix F's trigger table) and `notification.requested` (15 §6.2's
ruling, 09_UI §9). EB-006 §6.1 makes the taxonomy closed and additions
ADR-gated, so naming them elsewhere did not register them.

Drafting this ADR surfaced two problems that the "just register the three
already-named types" framing hides:

1. **`plan.generated` cannot be recovery-grade.** There is no `plan` table —
   all 33 tables in 07_DATABASE were enumerated to confirm this. 15 §16's
   item 2 makes a payload-sufficiency test **mandatory** for every
   recovery-grade type ("apply the fixture event to an empty store; assert
   the resulting record equals the recorded record") and states that a
   recovery-grade type without that test **fails CI**. With no record to
   reconstruct, that test cannot be written, so a recovery-grade
   `plan.generated` would make M5's own gate unreachable by construction.

2. **Two deadline truth mutations have no recovery-grade carrier.** EB-003's
   consequence list is explicit that recovery-grade classification is
   REQUIRED for "task/**deadline**/competition truth mutations." Creating a
   deadline, and the `tracked → alerted` transition the sweep performs under
   its `deadlines.mark_alerted` scope, are both deadline truth mutations.
   Neither `deadline.approaching` (which EB-008's rule 2 states literally
   "changes no row") nor anything else registered covers them.

## Options

### Option A — Register the three already-named types, as first framed

`deadline.approaching`, `notification.requested`, `plan.generated`.

- **For:** smallest diff; every type is already named in existing docs, so
  it looks like pure formalization.
- **Against:** leaves both problems above unfixed. Deadline creation — the
  first step of M5's own proof chain — would have no publishable event, and
  the alerted-status mutation would have no redo record, violating EB-003's
  REQUIRED clause. It also forces a wrong call on `plan.generated`: marking
  it recovery-grade breaks CI, and marking it non-recovery-grade while
  leaving deadline mutations uncovered is internally inconsistent about what
  recovery-grade is *for*.

### Option B — Register five types: the three named, plus the two truth-mutation carriers (recommended)

Add `deadline.created` and `deadline.updated`, mirroring the existing
`task.created`/`task.updated` pair exactly.

- **For:** satisfies EB-003's REQUIRED clause for deadline truth mutations;
  makes M5's proof chain publishable from its first step; keeps
  `deadline.approaching` faithful to EB-008 rule 2 (a fact that changes no
  row) rather than overloading it into a mutation carrier; reuses an
  established shape instead of inventing a convention.
- **Against:** two more types than "formalize what's already named" implies.
  Accepted: they are not new design — they are the deadline entity's half of
  a pattern the task entity already has, and the payload builder for them
  (`deadline_event_payload`, full-row) already exists from Increment 1.

### Option C — Defer and redesign the event vocabulary now that real schema exists

- **For:** the schema landed after the vocabulary was written; a fresh look
  is defensible in principle.
- **Against:** re-litigates settled design for no new information. Nothing
  discovered while building Increment 1 contradicts the existing taxonomy —
  the gaps found are *omissions* within it, not evidence against it.
  Rejected.

## Decision

Adopt **Option B**. Register five types:

| Type | Category | `recovery_grade` | Why |
|---|---|---|---|
| `deadline.created` | domain | **true** | A deadline row is Tier-1 truth; losing one is the exact failure "never misses a deadline" forbids (02_PRD R9). Full-row payload. Mirrors `task.created`. |
| `deadline.updated` | domain | **true** | Carries the `tracked → alerted → met/missed` transitions — deadline truth mutations, REQUIRED recovery-grade by EB-003. Full-row payload. Mirrors `task.updated`. |
| `deadline.approaching` | domain | **false** | EB-008 rule 2: "changes no row." Its consumers are `notifier; planner` (05 Appendix F) — a trigger, not a redo record. EB-003 classes informational events non-recovery-grade. |
| `notification.requested` | notification | **false** | 15 §6.2's own ruling: an accelerant, not the work item. The durable state is the queue row ([[005-notification-queue-schema]]). This ADR registers the type §6.2 names; it does not reopen that ruling. |
| `plan.generated` | domain | **false** | No `plan` table exists, and none should: 02_PRD's dependency map calls the daily plan **derived state**, and M5's determinism premise (same inputs ⇒ identical plan) makes it rebuildable — 07 §1.4 reserves authority for non-derivable truth. Its durable effect (setting `plan_date` on N tasks) rides the already-recovery-grade `task.updated`. |

The `calendar_cache` table is the governing precedent for the
`plan.generated` call: 07 §5.2 marks it `-- DERIVED (truth = provider);
rebuildable` and deliberately omits the sync quartet. Derived things are
rebuilt, not replayed.

## Consequences

- **Payload-sufficiency tests become a required CI gate** (15 §16 item 2) for
  `deadline.created` and `deadline.updated` — the two recovery-grade
  additions. Both are writable: `deadline_event_payload()` already returns
  the full field set. No such test is owed for the three non-recovery-grade
  types, and none can be written for `plan.generated`, which is precisely why
  it is not recovery-grade.
- EB-008's rule 2 becomes coherent rather than paradoxical: "one
  `plan.generated` changes many" now means *many `task.updated` redo records
  plus one informational fact*, not one fat event carrying N task rows.
- Publishing these types no longer requires an ADR; the bus's §6.3 validation
  will accept them once registered.
- **Open question deliberately left for the increment that builds it:**
  whether one `tracked → alerted` flip publishes *both* `deadline.updated`
  and `deadline.approaching`, or whether the approaching-fact is derived
  structurally from the status transition. Registering both types does not
  decide their emission order or cardinality — that is an implementation
  ruling for Increment 2, to be made against real code rather than guessed
  here.
- **Explicitly deferred, recorded so it is not silently forgotten:**
  - **`competition.*` events are NOT registered.** M5 tracks competitions
    that already exist as rows; evaluation, discovery, and scouting are
    Phase 3 (03_ROADMAP §4). With nothing in M5 writing competition state,
    there is nothing to publish, and registering ahead of a real consumer is
    the speculative-structure anti-pattern PS-006 rejects. Whichever
    increment adds competition write behavior files that ADR.
  - **No `notification.ack` event type.** 12 §13 already defines
    `notification.list/ack` as a **command** ("acking is a command; it
    changes beacon state"), mutating the queue row's state directly. Events
    carry facts other subscribers react to; nothing in M5 reacts to an ack.
    If a later need appears (cross-window live ack sync), that is a new ADR
    at that time.
- **What gets harder:** five types instead of two means five schemas to keep
  truthful, and the two recovery-grade ones carry full-row payloads that
  duplicate data also living in `kang.db`. Accepted — EB-003 names this as
  "transient operational redundancy inside a 90-day window," and the flag is
  the contract that keeps payload-thinning regressions visible.
