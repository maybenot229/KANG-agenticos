# ADR-026 — `held_action.*` events are NOT registered yet: the consumer test, and what changes when one appears

**Status:** accepted
**Date:** 2026-08-17
**Supersedes:** none
**Affected documents:** none — this ADR deliberately changes no schema, no registry, and no code (see Decision); `03_ROADMAP.md` §8 gains a RESERVED row carrying the trigger
**Cites:** ADR-021 §Consequences (declined `job.updated` for want of a named consumer), ADR-022 §Decision 1 (declined `held_action.*` for the same reason), ADR-024 (which scoped this as D3), ADR-025 (which removed D3's original motivation — below), 15_EVENT_BUS EB-003 (`docs/15_EVENT_BUS.md:82`) and §6.1 (`:180`)
**Related:** [[024-held-action-terminal-state-split.md]], [[025-held-action-transition-provenance.md]] — the other two thirds of the same investigation

---

## Context

The 2026-08-16 investigation produced three slices. D1 shipped as ADR-024 (`cancelled`/`expired`); D2 shipped as ADR-025 (`decided_at`/`decided_by`). D3 — register `held_action.*` on the bus and publish on each transition — was carried forward to this ADR.

**D3's stated motivation no longer holds, and recording that is why this ADR exists.** ADR-024's draft justified D3 as the fix for F2: "no held-action transition is attributable in durable state… this is the mechanism the project already uses to make state visible." ADR-025 solved F2 directly, in row state. The ADR-024 draft had itself already ruled on the ordering, in its own alternative A3: *"Events only, no columns — Rejected. Events are a notification channel, not a system of record. A row must be able to explain itself from its own state without replaying a bus."* The columns shipped. The row now explains itself. D3's original job is done by other means.

What remains for D3 to justify itself is a **consumer** — and there is none. Confirmed by grep, not assumed:

- **No event-channel client binding exists.** `api/http_binding.py:9` states it directly: *"The event channel (§6) is a later binding (needs the bus subscription surface exposed to clients — M5+)."* The HTTP binding carries the operation channel only (`POST /op`). No client, UI or CLI, can receive a bus event today by any path.
- **Exactly two subscribers are registered**, both halves of the notifier, both deadline-specific: `notifier.enqueue` and `notifier.drain` (`kernel/runtime/composition.py:206-213`). Neither would act on a held-action event.

A `held_action.approved` published today would be appended to `eventlog.db`, delivered to two handlers that ignore it, and observed by nobody.

**This is the exact test ADR-021 and ADR-022 both already applied, and both times the answer was the same.** ADR-021 declined `job.updated`: "no current consumer names a need for one; building it speculatively would repeat the 'enum allows it' anti-pattern." ADR-022 declined `held_action.*` in nearly those words. Nothing changed between then and now except that ADR-025 made the row self-explaining — which weakens the case for D3 rather than strengthening it.

---

## Decision

**Do not register `held_action.approved` / `.cancelled` / `.expired`, and do not publish from the held-action handlers. No code changes.**

This closes ADR-024's D3 as *decided*, not as *pending*. The distinction matters: a slice left silently unbuilt reads as an oversight to the next session, and this one is a judgment.

Recorded in `03_ROADMAP.md` §8's RESERVED registry with a real trigger rather than left as an ADR footnote — the same discipline ADR-021's idempotency gap already received.

### The trigger

Register these types when **either** becomes true:

1. **A real consumer exists.** Concretely: the event-channel client binding lands (`http_binding.py:9`'s own "M5+" note) and a UI surface needs the approval queue to update live rather than by polling. 09_UI §7's "they expire visibly, never silently" is the likeliest first claimant — a real claim, just not one anything can currently act on.
2. **M7's orchestrator needs held-action transitions as a trigger** — an agent whose invocation suspends at `awaiting_confirmation` and must resume on approval (05_AGENTS Appendix B). ADR-001 already scoped this as the M7 path and explicitly deferred it; if M7 builds agent-initiated confirmation, this event is how the resume fires.

Trigger 2 is **not** satisfied by M7 merely existing. ADR-001's client-initiated path (what is built) needs no event; only the agent-suspend/resume path does.

### What is pre-decided, so a future session does not re-litigate it

Two things are already settled by the constitution and should be read off rather than re-derived by analogy — ADR-013 flagged analogy-picking as the pattern that creates implicit commitments:

- **Category and grade for `held_action.approved` are not open questions.** `15_EVENT_BUS.md:180` (§6.1's taxonomy table) names `held_action.approved` explicitly as a **Lifecycle** example and states its grade in the same row: "`held_action.approved`: yes; others no." `:82` (EB-003, normative) independently requires recovery-grade for "held-action approvals." So: Lifecycle, `recovery_grade=True`. It would be the registry's **first Lifecycle-category type** — all 13 currently registered are `domain` except `notification.requested` (`kernel/bus/event_registry.py:171-330`).
- **`.cancelled` / `.expired` have no such precedent**, and their grade is genuinely open. EB-003's required list names approvals only. Whoever builds this decides them on their own merits and records the reasoning; they do not inherit `approved`'s grade by proximity.

Recovery-grade carries a real obligation, named here so it is costed rather than discovered: the payload MUST be self-sufficient for re-application (`15_EVENT_BUS.md:81`), and a payload-sufficiency test is REQUIRED per type (`:94`, 13_TESTING §16.2) — apply the event to an empty fixture, assert the resulting row equals the recorded row.

### The transaction shape it will need

Designed here because the investigation surfaced it and the cost belongs on the record — not because it is being built.

`_approve_transactional` (`api/operations/held_action_ops.py`) owns one `BEGIN IMMEDIATE`/`COMMIT` spanning the approve-flip, the effect, and mark-executed. EB-004's write order (`15_EVENT_BUS.md:100-110`) requires the event be appended to `eventlog.db` **before** the `kang.db` state commit. `EventBus.publish(envelope, commit_state)` (`kernel/bus/bus.py:79-107`) is shaped for exactly this — `commit_state` is "the caller's kang.db transaction." So the integration is structurally available: put `publish(envelope, commit_state=lambda: connection.execute("COMMIT"))` where the bare `COMMIT` is today, with the three preceding writes unchanged.

**But it adds a crash boundary that does not exist today:** the window between event-append and state-commit — EB-004's own "ghost event" case. ADR-021's crash-kill suite (`tests/suites/replay/test_transactional_approve_crash.py`, five real `os._exit(9)` kills) covers the four boundaries the current shape has. A publish inserts a fifth. That suite would need extending, or an explicit argument that C2's existing coverage (`test_crash_replay.py`) subsumes it — which is not obvious, since C2 covers the bus's own write order, not this handler's composite transaction. **Whoever builds this owns that test, and should assume it is the expensive part**, not the registration.

---

## Alternatives considered

**Register the types now, publish later.** Rejected: a registered type with no publisher is dead vocabulary CI must still carry — every registered type needs a schema and a fixture (`15_EVENT_BUS.md:196`), and recovery-grade types additionally need a payload-sufficiency test. "Just registering" is not free, and buys nothing until a publisher exists.

**Publish `held_action.expired` only**, on the argument that expiry is the one transition with no other visible trace. Rejected: same zero consumers, and the premise is now false — ADR-024 gave expiry a distinct terminal status and ADR-025 gave it an attributed decider. The row says everything the event would.

**Treat 15_EVENT_BUS §6.1's naming of `held_action.approved` as itself the mandate.** Rejected, and worth stating plainly since it is the strongest counter-argument: that table is a *taxonomy illustration* — it fixes which category the type occupies and what grade it carries *if registered*. Read as a build order it would equally mandate `provider.circuit_open`, `integrity.frozen`, `backup.verified`, `vault.note_changed`, and `capture.created`, none of which exist either. It fixes the answer; it does not set the date.

---

## Consequences

- **ADR-024's three-way split is now closed**: D1 built (ADR-024), D2 built (ADR-025), D3 decided-not-yet (this ADR). No slice is left ambiguous.
- **`held_action.*` stays absent from `event_registry.py`** — so `held_action_ops.py`'s existing docstrings, which state that no such type is registered and explain why, remain accurate rather than going stale. Checked: `make_held_action_expire_handler`'s docstring says exactly this and needs no edit.
- **A RESERVED row now carries the trigger**, so the next session finds it by lookup instead of by reading three ADRs.
- **What this ADR does not claim:** that events are the wrong mechanism here, or that they will never be built. Only that the consumer does not exist yet, and that building the mechanism before the consumer is the failure mode this project has already declined twice by name.
