# ADR-027 — `scope=None` is a decision, not a default: scoping the system-metadata reads before agent principals exist

**Status:** accepted
**Date:** 2026-08-17
**Supersedes:** none
**Affected documents:** 12_API §16 (the registry's `scope` field semantics), `config/defaults/permissions.toml` (no grant change — `kang`'s `*` already covers every scope added here), `src/kang/api/registry/__init__.py`
**Cites:** 10_SECURITY SEC-004 (`docs/10_SECURITY.md:118` — "no code path exempt from scopes except Kang acting through the UI as `kang`"), 05_AGENTS §8 (`docs/05_AGENTS.md:210` — principals include `agent:{id}`), AG-005 (`:224` — enumerated tool allowlists), 05_AGENTS §D (`:475` — why `held_action.approve`/`.cancel` are deliberately scope-less)
**Related:** the 2026-08-17 M7 read-only investigation (Q4); ADR-006 ruling 4 (jobs dispatch through the normal pipeline — the precedent M7 must **not** blindly copy for agents)

---

## Context

`Dispatcher._authorize` returns early when an operation declares no scope (`api/dispatch.py:180-182`):

```python
scope = entry["scope"]
if scope is None:
    return
```

**This is a skip, not a default-deny.** For an operation with `scope=None`, the permission engine is never consulted at all — so "default-deny for an unknown principal" (`kernel/permissions/engine.py:56-62`, correct and verified) simply never runs.

**13 of 39 registered operations declare `scope=None`.** Three are additionally `first_party_only`; ten are not:

`registry.get` · `permission.list` · `explain.invocation` · `explain.plan_item` · `explain.notification` · `explain.suggestion` · `explain.memory` · `audit.list` · `system.health` · `invocation.list`

**This was deliberate, not an oversight — and the rationale is written down.** `invocation.list`'s registry comment: *"scope=None, matching audit.list/system.health's own precedent — the execution ledger is system metadata about the Core itself, not a domain resource a domain-verb scope would fit."* `permission.list` and `audit.list` cite `registry.get` the same way.

**The rationale was sound under an assumption that M7 removes.** It holds while every session principal is fully trusted — and today exactly two exist: `kang` (holding `*`) and `kernel:scheduler` (`composition.py:142`, `scheduler_wiring.py:113`). Under that population, "any authenticated principal" and "a trusted principal" are the same set, so an unscoped read exposes nothing to anyone not already entitled to everything.

M7 introduces a third class. 05_AGENTS §8 (`:210`) names the principal vocabulary: **`kang`, `agent:{id}`, `plugin:{id}`, `rule:{id}`** — and agents are explicitly *not* trusted the way kernel components are: they get narrow enumerated grants, wildcards are forbidden to them, temporary elevation "does not exist," and a denial spike quarantines them (`:212-216`). The moment an `agent:{id}` principal can reach the dispatcher, it inherits — with no grant, and with no mechanism to refuse it — the entire audit log, the entire invocation ledger, every `explain` reconstruction, the full grant snapshot, and system health.

### The tension with SEC-004, stated plainly

`docs/10_SECURITY.md:118` is normative:

> "All authority is expressed as capability scopes granted to principals, default-deny, checked at the executor. There is no role system, no admin flag, no ambient authority, **no code path exempt from scopes except Kang acting through the UI as `kang`**."

Ten operations are today exempt from scopes **for every principal**, not only for `kang`. For `registry.get` that is defensible on its own terms (below). For `audit.list` — which serves the security-audit trail that SEC-006 and SEC-013 exist to protect — it is not comfortably defensible, and it is better fixed now, while the only caller is `kang`, than after an agent principal exists.

**Nothing is exploitable today.** A session token is required, and the only tokens minted belong to `kang` and `kernel:scheduler` (`session_store.py:1-8`; the token is a secret in the Core's session file). This ADR is a pre-emptive close of a gap whose cost is near-zero now and materially higher after M7 — not an incident.

---

## Decision

### D1 — Assign scopes to the nine system-metadata operations that expose Core state

| Operation | New scope |
|---|---|
| `audit.list` | `audit.read` |
| `invocation.list` | `invocations.read` |
| `explain.invocation`, `explain.plan_item`, `explain.notification`, `explain.suggestion`, `explain.memory` | `explain.read` |
| `permission.list` | `permissions.read` |
| `system.health` | `system.read` |
| `notification.ack` | `notifications.ack` |

Names follow the registry's existing convention — domain-plural noun plus the verb the operation performs (`deadlines.read`, `goals.read`, `held_actions.expire`). All five `explain.*` operations share one scope: they are one capability ("reconstruct why KANG did something"), not five, and splitting them would invent authority vocabulary no consumer distinguishes.

**No grant changes.** `kang` holds `*` (`config/defaults/permissions.toml`), which covers every scope above by `Scope.covers`'s wildcard rule (`kernel/permissions/scope.py:37-43`). `kernel:scheduler` calls none of these. So this ADR adds authority vocabulary without granting or revoking anything — the behaviour change is exactly and only that a *future* principal must be granted these explicitly.

### D2 — Three operations stay unscoped, each for a written reason

`scope=None` remains legitimate. What this ADR ends is its use as an unexamined default.

- **`registry.get`** — serves the operation registry itself: the contract a client must read before it can call anything, including to learn what scopes exist. Gating the contract behind a capability is circular, and the registry is public by design (12_API §16: *"the registry is the contract"*). It leaks no state, only shape.
- **`held_action.approve` and `held_action.cancel`** — **deliberately scope-less per 05_AGENTS `:475`**, quoted because a future session will otherwise "fix" this: *"for these two items specifically, the approval step itself is the consequential action, so the first-party channel check (**not a permission scope — §8**) is what stands in for that second layer. A plugin session cannot approve, decline, or drain Kang's approval queue regardless of its grants."* Adding a scope here would contradict a normative sentence and weaken the model by implying a grant could substitute for the channel. `first_party_only` already refuses every non-first-party principal, agents included (`dispatch.py:192-203`).

### D3 — The M7 constraint this surfaces, recorded before M7 design hardens

`SEC-004` places enforcement "at the executor." **ADR-006 ruling 4 made scheduled jobs dispatch through the ordinary operation pipeline under a minted session** — deliberately, so jobs are permission-checked, idempotency-keyed and audited by one path. That precedent is sound for jobs, whose operation set is a fixed three-entry composition-root table (`JOB_OPERATIONS`).

**It must not be copied wholesale for agents.** AG-005 (`05_AGENTS.md:224`) is normative and stricter:

> "Every agent definition MUST enumerate its allowed tools. There is no 'all tools' grant, no default toolset, and no runtime tool discovery for agents."

A design that mints an `agent:{id}` session and lets the agent post arbitrary operations to `/op` satisfies neither AG-005's allowlist nor SEC-004's executor locus — and, absent D1, would hand every agent the unscoped ten regardless of its grants. **M7's tool executor MUST enforce the per-agent allowlist itself**, before and independently of the dispatcher's scope check. D1 makes the dispatcher a correct second layer rather than the only one; it does not remove the executor's obligation.

---

## Alternatives considered

**Do nothing until M7 needs it.** Rejected on cost asymmetry, not on urgency: adding a scope to an operation nobody but `kang` calls is a one-line registry change today. After an agent principal exists, the same change requires reasoning about which agents legitimately read the audit log, and any mistake is a live authority bug rather than a no-op.

**Default-deny on `scope=None` (treat absence as "requires a scope nobody has").** Rejected: it would break `registry.get`, which must be reachable to bootstrap any client, and would convert a design distinction into an error state. `None` should mean "no capability is required, and here is why," which D2 makes explicit for the three survivors.

**Introduce a `system.*` grant family and give agents nothing from it.** Rejected as insufficient alone — it is D1 by another name, but stated as a family it invites a future "grant the agent `system:*`" shortcut. Per-operation scopes make each exposure an individually granted decision, which is what SEC-004's default-deny is for.

**Add scopes to `held_action.approve`/`.cancel` too, for uniformity.** Rejected — see D2. Uniformity is not worth contradicting a normative sentence, and the channel check is the stronger guarantee here (no grant can satisfy it).

---

## Consequences

- **Authority vocabulary grows by six scopes**, all read-shaped except `notifications.ack`. `kang` is unaffected (`*`); `kernel:scheduler` calls none of them; no grant file changes.
- **`scope=None` becomes a documented decision per operation** rather than a default. The three survivors each carry their reason in the registry comment.
- **`permission.list` is now itself scoped** — the operation that answers "what can KANG touch?" requires a capability to read. Deliberate: the grant snapshot is a map of the authority surface, exactly the thing an injected agent would want first.
- **What gets harder:** any future non-`kang` principal that legitimately needs one of these reads must be granted it explicitly in `permissions.toml`. That is the intended cost, and grants are boot-time only (the engine snapshot is immutable — `engine.py:45-52`), so it is a deliberate, reviewable file edit rather than a runtime decision.
- **Explicitly not decided here:** whether M7's executor reuses `Dispatcher` internally at all. D3 records only that the allowlist obligation cannot be delegated to it. That design is M7's own ADR.
- **Not addressed:** `grant.modify` — 10_SECURITY §6 (`:197`) specifies grant mutation as a "Kang-only consequential action, visible in the System permission screen." No such operation is registered and no runtime grant path exists. Pre-existing, unchanged by this ADR, and correctly so: it is a consequential-operation design in its own right.
