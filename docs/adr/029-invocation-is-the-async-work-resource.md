# ADR-029 — `invocation`, not `task`, is the async-work resource: resolving a live doc/code contradiction before M7

**Status:** accepted (2026-09-13)
**Date:** 2026-08-17
**Supersedes:** none
**Amends:** 12_API API-007 (`docs/12_API.md:99-103`) and §§9/10/13/16 usages, 15_EVENT_BUS §6.1 (`docs/15_EVENT_BUS.md:180`)
**Cites:** ADR-004 (registered `task.created`/`task.updated` as domain, recovery-grade), EB-003 (`15_EVENT_BUS.md:82`), `kernel/bus/event_registry.py::validate_registration`, ADR-028 V1 (which named this and deferred it here)
**Related:** [[028-m7-foundations.md]] — this is its V1, and it blocks every M7 operation registration

---

## Context

ADR-028 named `task` as an ambiguous word M7 would collide with. Measuring the collision to size the fix turned up something worse: **it is not a future risk, it is a present contradiction between the constitution and the code, and it fails closed at runtime.**

`task.updated` is **already registered**, by ADR-004, for TODO-item mutations:

```
name=task.updated  category=domain  recovery_grade=True
```

(`kernel/bus/event_registry.py:180-187`, payload `_TASK_PAYLOAD_FIELDS`.)

15_EVENT_BUS §6.1 (`:180`) simultaneously specifies the *same type name* as something else entirely — the Lifecycle row:

> `**Lifecycle**` | Execution-machinery fact | `invocation.finished`, **`task.updated` (API long-running tasks)**, `held_action.approved`, `plugin.quarantined` | `held_action.approved`: yes; **others no** |

So one event type name carries two categories (`domain` vs `Lifecycle`) and two recovery grades (`True` vs `False`) across doc and code. The parenthetical "(API long-running tasks)" is itself the tell: it exists to disambiguate a name that should not have needed disambiguating.

**This fails hard, not softly.** `validate_registration` rejects any publish whose `recovery_grade` disagrees with the registry:

> `f"{envelope.type}: recovery_grade={envelope.recovery_grade} contradicts the registry ({entry.recovery_grade}) — the redo contract is the registry's, not the publisher's (EB-003)"`

M7 publishing `task.updated` for an agent run — as 15_EVENT_BUS's Lifecycle row instructs, non-recovery-grade — would be refused at publish time by a guard that is working exactly as designed. The failure would surface as a confusing runtime rejection in the middle of building the agent runtime, with the constitution appearing to sanction the publish.

The collision extends past the event name. `task.*` in the operation registry means a TODO item (`task.create`/`get`/`complete`, scoped `task.read`/`task.write`, backed by `TaskStore`). API-007 uses the same prefix for async work handles — `task_id`, `task.cancel`, "task resource" — and `12_API.md:153` lists `task.create` and `task.cancel` side by side in one illustrative family, as though they belonged to the same thing. They do not.

**12_API already concedes the resolution in its own sentence** (`:103`): *"crash-survivability (task state persists as `invocation` rows)."* The async resource is already `invocation` in code — the table, the `InvocationStore` port, `invocation.list`, `explain.invocation`, and 05_AGENTS Appendix B's state machine all use it. Only the API-007 prose calls it `task`.

---

## Decision

**The async-work resource is `invocation`. `task.*` means a TODO item, and only that.**

### D1 — Rename the async-work API vocabulary

| Was (API-007 prose) | Becomes |
|---|---|
| "task resource" | "invocation resource" |
| `task_id` | `invocation_id` |
| `task.updated` (async sense) | `invocation.updated` |
| `task.cancel` | `invocation.cancel` |

Applied at `12_API.md:99, 101, 103, 153, 165, 176, 181, 197, 200`. No operation is renamed, because **none of the async ones exists yet** — `task.cancel`, `agent.invoke`, `pipeline.run`, `knowledge.ask`, `health.doctor`, `export.run` are all illustrative-future. This is why the fix is free today and expensive after M7 registers the first one.

### D2 — Correct 15_EVENT_BUS §6.1's Lifecycle row

Remove `task.updated` (API long-running tasks) from the Lifecycle examples. `invocation.finished` is *already listed in that same row*, so the row loses nothing; it gains `invocation.updated` as the streaming-progress type M7 will register. `task.updated` stays exactly what ADR-004 registered it as — a `domain`, recovery-grade TODO mutation — and the doc stops contradicting that.

### D3 — Lock it with a test

`unit/kang/kernel/bus/test_event_registry.py` gains an assertion that `task.updated` is `domain` + recovery-grade. The contradiction is now impossible to reintroduce silently: any future edit that re-specifies `task.updated` as Lifecycle/non-recovery-grade fails the suite rather than surfacing as a publish rejection during M7.

### D4 — UI labels are deliberately NOT renamed

09_UI §5.2's **"task card"** and 05_AGENTS `:174`'s use of it stay. This is a boundary, not an oversight: a card in the interface is a human-facing label owned by 09_UI, and "task card" is what Kang reads. The API vocabulary and the UI's words are allowed to differ — `job` rows render as something else too. Renaming what Kang sees to match a wire-protocol noun would be the tail wagging the dog, and would widen a tight fix into 09_UI's whole surface.

**Stated explicitly so a future session does not "finish the job."**

---

## Alternatives considered

**Rename the TODO operations instead** (`task.*` → `todo.*`), freeing `task.*` for async work. Rejected on blast radius and on which side has the better claim: `task.*` is three registered operations, two registered event types, a store, a port, a domain service, two scopes, and a migration — all shipped since M1 — versus prose describing operations that do not exist. The unbuilt side moves.

**Keep both, disambiguate by context.** Rejected: that is the status quo, and the status quo is a runtime rejection waiting to happen. The `(API long-running tasks)` parenthetical is what "disambiguate by context" looks like in practice, and it already failed to prevent the contradiction it was written to explain.

**Leave it for M7's own ADR to sort out.** Rejected — the first M7 registration sets the precedent, so the cost only rises, and the person paying it would be mid-way through building an agent runtime rather than looking at the vocabulary directly.

---

## Consequences

- **No code changes** beyond the D3 test. Nothing is renamed in `src/`, because the async side is unbuilt and the TODO side is correct as-is.
- **A live doc/code contradiction is closed** — and one that would have failed closed at publish time, in the middle of M7.
- **ADR-028's V1 is discharged**, unblocking M7 operation registration.
- **`invocation.updated` is named but NOT registered here.** It has no publisher and no consumer yet; registering it now would be the speculative-structure anti-pattern ADR-026 just declined for `held_action.*`. M7 registers it when something publishes it — and per D2's corrected row, it will be Lifecycle-category, with its grade argued on its own merits at that point (EB-003's required list does not name it).
- **What this ADR does not touch:** O1 (ADR-028's open execution-model fork). The naming resolution holds whichever way O1 goes.
