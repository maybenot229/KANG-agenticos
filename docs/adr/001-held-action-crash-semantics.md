# ADR 001 — Held-action lifecycle and crash-semantics

**Status:** accepted (with amendment, 2026-07-20)
**Date:** 2026-07-20
**Batch:** B (pre-M3 ruling #2 of 5)
**Affected documents:** 05_AGENTS §6 + Appendix B (Confirmation-resume mode; invocation state diagram), 12_API §7 (held_action lifecycle), 07_DATABASE §5.5 (held_action schema — delta owed, §Consequences)
**Cites (inlined decisions amended/extended):** 05_AGENTS §6 (invocation modes), SEC-003 (10_SECURITY), D006 (at-least-once + reconciliation), API-004 (idempotency)
**Related:** [[002-approval-channel]] (the gate that admits the approval this ADR then executes)

---

## Context

M3 shipped the consequential-action gate's data plumbing: `held_action`
(`migrations/0002_held_action.sql`, `held_action.py` port + sqlite/fake
stores). The record has three states — `pending → approved | cancelled` — and
a 24h expiry sweep. It is a **standalone durable record**: create pending,
transition status, never edit substance.

Two constitutional statements describe a *different* model:

- **05_AGENTS §6 (Confirmation-resume mode):** "Resumes the *held invocation*,
  same correlation id — approval is a lifecycle event, not a new invocation."
- **05_AGENTS Appendix B (state diagram):** `awaiting_confirmation → running :
  Kang approves (resume)`.

Neither the docs nor the code answer the question this ruling is named for:
**if KANG dies between recording Kang's approval and the held effect actually
being performed, what does restart do?** The schema cannot even express the
question — `approved` means "Kang said yes," not "the effect happened," and
nothing distinguishes the two. A crash in that gap leaves an `approved` row
whose effect may or may not have committed, with no persisted way to tell.

A second confusion sits underneath: the constitution conflates **two paths**
to a consequential action.

1. **Agent-initiated (M7, not yet built).** A cognitive agent, mid-invocation,
   wants a consequential effect → the invocation suspends at
   `awaiting_confirmation` → Kang approves → *that same agent invocation*
   resumes. This is what Appendix B draws.
2. **Client-initiated (M4, what exists).** Kang or a plugin issues a
   consequential *command* directly through the API → the command returns
   `confirmation_required` + a `held_action` → Kang approves via
   `held_action.approve` → the effect happens. The originating command was a
   sub-3-second request/response (API-007); **there is no long-running
   invocation to "resume"** — it finished when it returned `confirmation_required`.

The "resume the same invocation, same correlation id" language is faithful to
path 1 and does not map onto path 2, which is the only path that exists today.

## Options

### Option A — True suspend/resume (faithful to Appendix B for all paths)

Give `invocation` an `awaiting_confirmation` state; persist a **continuation**
(what to perform on resume); on approval, re-enter the *same* invocation and run
the effect; crash-recovery re-enters suspended invocations.

- **For:** literal fidelity to 05_AGENTS Appendix B; one correlation id, one
  invocation row, end to end.
- **Against:** introduces a durable *continuation* concept the kernel does not
  have and would have to grow (a serialized "what to do next" captured mid-flight
  — exactly the kind of hidden control-flow the architecture avoids). For path 2
  it models a suspension that does not exist: an M4 command has already returned
  and finished; there is no live frame to suspend. Heavy new crash-recovery
  surface (re-entering partial invocations) for a case (M7 agents) not yet built.

### Option B — Held action is durable intent; approval drives an idempotent effect (recommended)

The `held_action` row **is** the durable intent — not a suspended invocation.
Approval flips it to `approved` and drives the held effect through the **same
idempotent command path every effect already uses** (state-commit + event
publish, transactional, per D006/EB-004; or a world-touching adapter call).
Add a terminal state **`executed`** so "Kang approved" and "the effect
completed" are distinct, persisted, and therefore recoverable. The origin
`correlation_id` is threaded origin → approval → effect, honoring §6's *intent*
(one causal thread for `explain`) without pretending a finished request
suspended.

Crash-recovery reuses machinery M2 already built and kill-tested (Checkpoint
C2): on restart, every `approved`-but-not-`executed` held action is **re-driven**
through its effect's idempotent path, then advanced to `executed`. The bus's
existing (state + event) transactionality plus the idempotency store answer
"did it happen?" — no bespoke recovery logic.

- **For:** reuses proven invariants (at-least-once + reconciliation +
  idempotency) instead of inventing continuation/suspension; fits the M4 command
  reality exactly; `explain` still renders one correlation chain; the M7
  agent-suspend case can be decided later on its own terms without unwinding this.
- **Against:** adds one state to the schema (delta owed); the recovery guarantee
  is only as strong as the effect's idempotency — genuinely idempotent for
  bus-carried state effects, but **honest limit:** a world-touching effect whose
  adapter offers no idempotency (e.g. a naive calendar write) could double-apply
  on re-drive. Named and bounded below, not hidden.

### Option C — Perform the effect in the same transaction as the approval flip

Make `pending → approved` and the effect one DB transaction, so `approved`
*means* "committed" and no gap exists.

- **For:** eliminates the crash gap entirely, for the cases it covers.
- **Against:** works only when the effect is a `kang.db` write. World-touching
  effects (calendar, vault) cannot join a DB transaction, so this cannot be the
  general rule — it would answer the easy half and leave the hard half exactly
  as ambiguous as today. Kept only as B's degenerate fast-path where applicable.

## Decision (proposed)

Adopt **Option B.**

1. **A held action is durable intent, not a suspended invocation.** The
   record carries everything needed to perform its effect. The "resume the
   same invocation" model of 05_AGENTS §6/Appendix B is scoped **explicitly to
   the M7 agent-initiated path** and deferred to it; the M4 client-initiated
   path does not suspend a finished request.

2. **Add a terminal state `executed`.** Lifecycle becomes
   `pending → approved → executed`, plus `pending → cancelled` (decline or 24h
   expiry). `approved` is a *resumable* state: it records intent, not
   completion.

3. **The effect rides the existing idempotent command path.** Approval drives
   the effect exactly as any command drives one — state commit + event publish
   transactionally (D006/EB-004), keyed by an idempotency key derived from the
   held-action id (API-004). The effect is owed once approved: it is driven to
   `executed` or to an explicit, audited failure — **never silently expired.**
   The 24h expiry governs the `pending` window only.

4. **Crash-recovery re-drives, it does not decide.** On restart, every
   `approved`-but-not-`executed` held action is re-driven through its effect's
   idempotent path and then marked `executed`. No new recovery machinery: this
   is the bus's at-least-once + idempotency guarantee (Checkpoint C2), inherited.

5. **`held_action.approve` is itself an idempotent command** (API-004), so
   double-approval returns the cached outcome — already covered, stated for
   completeness.

## Consequences

- **Schema delta owed** (to 07_DATABASE §5.5 / the `held_action` table and the
  `HELD_ACTION_STATUSES` tuple in the port): add `executed` to the status
  `CHECK`; record the effect linkage (the resulting effect's `correlation_id`
  or event id) so recovery and `explain` can confirm completion. Recorded here,
  applied by the follow-through PR **after this ADR is accepted** — not now.
- **05_AGENTS §6 / Appendix B amended:** the resume-same-invocation model is
  annotated as the agent-path (M7) semantics; the client-path (M4) semantics
  are this ADR. Version bump on 05_AGENTS when applied.
- **New test obligation** (13 §2.5 replay class): a held-action-specific
  crash case — kill between `approved` and effect-commit, and between
  effect-commit and `executed`; assert re-drive reaches `executed` exactly once,
  no double-effect for idempotent effects.
- **Honest limit carried forward:** re-drive safety equals effect idempotency.
  World-touching effects without adapter-level idempotency are the residual
  risk; until an effect proves idempotent (or re-confirms), it MUST NOT be
  eligible for silent re-drive. This constrains which effects may be held —
  a constraint to make explicit when the first world-touching consequential
  effect is built (calendar.write is the likely first; its ADR inherits this).
- **What gets harder:** a held action now has a state (`executed`) that only the
  effect-driver may set, so the approval path and the effect path are coupled by
  a small protocol rather than a single status flip. Accepted: the coupling is
  the honest shape of "approved ≠ done."
- **Explicitly not decided here:** the M7 agent-suspend/resume mechanism
  (continuation capture, re-entry of a live agent invocation). That is a
  separate ADR when agents arrive; this ADR only ensures the M4 gate is
  crash-correct and does not foreclose it.

## Amendment — 2026-07-20 — split commit mode

**Status:** accepted (Batch B follow-through task).

Option B's single re-drive path is split into **two mechanisms, chosen at
registration time** (a property of the *operation type*, not the individual
held-action row):

- **`commit_mode = "transactional"`** — the approval-flip and the effect
  commit in **one `kang.db` transaction**. Default for any consequential
  action whose entire effect is representable as a `kang.db` write
  (`memory.delete`, `grant.modify`, `plugin.install` where DB-representable).
  This is the base ADR's Option C, promoted from "degenerate fast-path" to a
  first-class, declared mode: for these actions there is no crash gap to
  re-drive through — a crash before commit leaves the row `approved` with no
  effect applied, which is indistinguishable from (and recoverable exactly
  like) a still-pending approval that hasn't been acted on yet. No `executed`
  *sweep* is needed for this mode; the transaction boundary *is* the
  distinction between "approved" and "done."

- **`commit_mode = "redrive"`** — for effects crossing the tool executor into
  `adapters/` (world-touching: `calendar.write` and similar). This is the base
  ADR's re-drive path, now gated by a **structural registration-time
  validation rule**: an operation MUST NOT be registered with
  `commit_mode="redrive"` unless its target adapter has a documented
  idempotency contract **and** a passing conformance test proving it. This
  validation runs at startup/CI, not at runtime — an adapter that hasn't
  proven idempotency cannot become eligible for silent re-drive by omission.
  This closes the base ADR's "honest limit" from a documented caveat into an
  enforced gate: the risk named in the original Consequences section (a naive
  non-idempotent adapter silently double-applying) is now structurally
  unrepresentable in the registry, not merely discouraged in prose.

**Schema:** `held_action.status` gains `executed` regardless of mode (verified
against the base ADR, not duplicated — `executed` already covered pending-vs-
done for the general case; the split adds `commit_mode` as *registry*
metadata, not a new `held_action` column, since it governs how an operation
type's effect is applied, not a fact about one instance). **Registry:**
`commit_mode` is a required field, enum `transactional | redrive`, on every
consequential operation.
