# KANG — Event Bus Constitution

**Document:** 15_EVENT_BUS.md
**Version:** 0.1
**Author:** Kang, with Claude (Founding Architect)
**Status:** Normative — RFC-2119 throughout; changes require an ADR; RESERVED items carry activation triggers
**Last updated:** 2026-07-12
**Upstream (binding):** `01_PRINCIPLES.md` (P5, P8, AR3, AR6, E1, E10), `04_ARCHITECTURE.md` (D001, D004, D006, D014, D015), `05_AGENTS.md` (AG-001, AGP-3/4, §6 trigger modes), `06_MEMORY.md` (Part IV write gate, M-003), `07_DATABASE.md` (DB-001 durability pairing, Part 12, Part 15, §5.6), `08_PLUGIN_SYSTEM.md` (§7, Appendix A, Appendix D), `10_SECURITY.md` (SEC-001..010, §5), `12_API.md` (API-001, §6 event channel), `13_TESTING.md` (§2.5, §2.6)

**Role.** D006 established the Event Bus; fragments of its behavior are already law in six other documents. This document is the bus's constitution: it **consolidates by reference, decides what was undecided, and resolves what was in tension.** It deliberately restates as little as possible.

> **Anti-duplication rule (normative).** Where an upstream document already decides a bus behavior, this document cites it and MUST NOT re-specify it. If a future reader finds this document and an upstream document disagreeing on a cited point, the upstream document wins and the divergence is filed as an ADR. For the decisions original to this document (EB-001..EB-012), this document is the source of truth.

---

## 0. What Is Already Law (cite-only index)

| Behavior | Decided in | One line |
|---|---|---|
| In-process async bus, persistent write-ahead log | D006 | No broker, ever, for one process talking to itself |
| At-least-once delivery; idempotent handlers | D006, AGP-3, 08 §6 | Handlers dedup on event id; duplicates are normal |
| Handler isolation: supervised, retried, dead-lettered | D006, PL-009 | A failing handler never blocks siblings |
| Events are facts, not commands; zero authority | 12_API §6, SEC-002 spirit | Receiving an event demands nothing |
| Orchestrator is the authority; choreography rejected | 05_AGENTS AG-001 | Events are transport, never governance |
| Single event vocabulary system-wide | 12_API §6 | The API adds no second event language |
| Plugin rules: namespacing, no shadowing, lexical order, flood caps, observational-only subscription | 08 §4, §7, Appendix A/D | Subscriptions cannot alter the observed action |
| Retention: 90 days, then compaction; audit is the permanent record | D006 | The event log is operational, not archival |
| Event-log file separation, `synchronous=FULL`, own connection | D004, 07 §1.2, DB-001 | Independent recovery domain |
| Event-sourcing rejected as a state model — twice | 06_MEMORY §alternatives, 12_API API-001 alternatives | State is truth; events are not the database |
| Event envelope on the API event channel; client resume by cursor | 12_API §6 | Extended additively by EB-005 |
| Security-relevant failures produce a typed event | SEC-009 | The bus is the nervous system of fail-visible |

Everything below either fills a gap or resolves a tension. Each decision records **Decision / Why / Alternatives / Trade-offs / Implications**, per the house ADR format.

---

## 1. EB-001 — Philosophy: Command-First; Events Are Immutable Past-Tense Facts

**Decision.**
- KANG is **command-first**. State changes are caused by commands (Kang's operations via 12_API, Orchestrator invocations, scheduler jobs, kernel services). Events are published *after* the fact, as facts.
- An **event** is: an immutable, past-tense, schema-validated statement that a state change or observation has already occurred. Named `noun.verb_past_tense` (`task.completed`, `vault.note_changed`). It carries zero authority and creates zero obligation.
- The **litmus test (normative):** *"If no subscriber existed, would this fact still be true?"* Yes → it is an event. No → it is a command wearing an event costume, and it MUST NOT be published as an event.
- **Not events:** requests, intents, commands, queries, UI gestures, model output tokens, log lines, function-call minutiae, raw filesystem-watcher ticks (§11.2), and anything whose truth depends on someone reacting to it.

**Why.** The alternative — event-first / choreography, where components react to each other and behavior emerges — was already rejected in 05_AGENTS ("emergent chains are unexplainable and unbudgetable"). Command-first keeps authority, budgets, and explanation in one place (the Orchestrator and the tool executor), and lets the bus be what a decade-scale system needs it to be: a boring, inspectable fan-out of truths.

**Alternatives.** Event-first architecture (rejected upstream, cited above); "everything is an event" including commands-as-events (CQRS/ES style — rejected: it makes the log the database, which 06 and 12 both rejected; it also makes SEC-002 harder to enforce, because command-events *do* demand action).

**Trade-offs.** Some elegance lost: a purist ES design has one write path. Accepted — KANG optimizes for a human explaining his system at 11 p.m., not for architectural purity.

**Implications.** The litmus test becomes a code-review checklist item (11_CODING DoD) and an event-registry admission rule (§6.3).

---

## 2. EB-002 — There Is No Internal Command Bus

**Decision.** KANG has exactly one dispatch abstraction for causing things: the existing command path (API registry dispatch → kernel → Orchestrator/services → tool executor). Internal components MUST invoke each other through ports and the Orchestrator, never by publishing "do this" messages. A generic internal command bus MUST NOT be built.

**Why.** 12_API already rejected a full command bus ("ceremony beyond one-user scale"). Two dispatch systems means two permission surfaces, two audit paths, and a permanent "which one do I use?" tax. The event bus stays single-purpose: facts out, never instructions in.

**Alternatives.** Mediator/command-bus pattern internally (rejected above); allowing "request events" as a lightweight command channel (rejected: it is exactly how event systems rot — see the `notification.requested` post-mortem in §6.2).

**Trade-offs.** Cross-module workflows must be expressed as pipelines or explicit service calls. That friction is the point (05_AGENTS: "composition is a design act, not a runtime accident").

**Implications.** Year-3 Kang, tempted to add a command bus for a new feature, finds this section and files an ADR instead.

---

## 3. EB-003 — The Dual-Duty Doctrine: Delivery Log AND Tier-1 Redo Log

This is the load-bearing decision of this document. It names something the constitution already relies on but never wrote down.

**Decision.** The persistent event log serves exactly two duties, and both are first-class:

1. **Delivery:** crash-safe at-least-once fan-out to subscribers (D006).
2. **Redo:** the crash-recovery net for Tier-1 truth. `kang.db` runs `synchronous=NORMAL` and may lose its final transactions on power loss (DB-001, accepted). The event log runs `synchronous=FULL` and is appended **before** the state commit. After a crash, recovery-grade events in the unconfirmed window are **re-applied** to bring state back (07 Part 15 F2/F3, 10_SECURITY §recovery table).

Consequences, normative:

- Every event type is classified **`recovery_grade: true | false`** in the event registry (§6.3).
- A recovery-grade event's payload MUST be **self-sufficient for re-application**: the full record or full field-set of the change, not merely an id. An id-only payload cannot replay a lost write.
- Recovery-grade classification is REQUIRED for: memory-record commits (the 07 DB-001 pairing, already normative there), task/deadline/competition truth mutations, held-action approvals, and schedule-truth mutations. Informational events (`provider.circuit_open`, `plugin.{id}.*`, product-state transitions) are non-recovery-grade and MAY carry ids + refs only.
- Re-application MUST be idempotent (natural: the state write itself is keyed by entity id + revision; re-applying a committed change is a no-op).

**Why.** Without naming the dual duty, two failure modes are inevitable: (a) someone "optimizes" an event payload down to an id and silently breaks crash recovery; (b) someone treats every event as a redo record and bloats the log with full payloads nothing will ever replay. One boolean in the registry prevents both.

**Alternatives.**
- *All events full-payload, no flag* (considered seriously — simpler, one less concept; rejected because it removes the **contract**: nothing would state which payloads recovery depends on, and payload-thinning regressions would be invisible until a power loss. The flag is documentation that CI can enforce, not just fat in the log).
- *A separate redo log* (rejected: a fourth log; the write-ahead event log already is one — D006's design, 07's normative pairing).
- *`synchronous=FULL` on `kang.db` instead* (rejected in 07: 2–5× write latency for risk the event log already covers; remains available via `database.toml` on battery-less machines).

**Trade-offs.** Recovery-grade payloads are heavier and duplicate data that also lands in `kang.db` and `change_log`. Accepted: this is *transient operational redundancy inside a 90-day window*, not duplicated truth — the log is never the authority for current state (§8).

**Implications.** 13_TESTING gains an obligation (§16): a payload-sufficiency test per recovery-grade type — apply the event to an empty fixture, assert the resulting row equals the recorded row.

---

## 4. EB-004 — Publication Ordering and the Ghost-Event Reconciliation Pass

**Decision.** The write order for any state-changing operation that publishes events is fixed:

```
1. build event(s), validate envelope + payload (schema, namespace,
   publish authority — §10)
2. append to eventlog.db  (synchronous=FULL; seq assigned; state=pending)
3. commit state transaction in kang.db  (change_log rows via triggers,
   07 §5.6, same transaction)
4. mark event(s) confirmed in eventlog.db
5. bus fans out to subscribers (per-subscriber cursors, §7)
```

Crash outcomes, exhaustively:

| Crash between | Result | Recovery |
|---|---|---|
| 1–2 | Nothing persisted | Command fails visibly (API-006); caller retries with same idempotency key. Correct by construction |
| 2–3 | **Ghost event**: event pending, state possibly lost | Startup reconciliation (below) |
| 3–4 | Event pending, state committed | Reconciliation confirms and delivers — indistinguishable from 2–3 by design; idempotent re-application makes the distinction irrelevant |
| 4–5 | Confirmed, undelivered | Normal at-least-once redelivery from cursors (D006) |

**Startup reconciliation pass (normative).** On every start:

1. Read all `pending` events (oldest first, by `seq`).
2. For each **recovery-grade** pending event: re-apply its payload to `kang.db` idempotently (insert-or-verify by entity id + revision), then mark confirmed.
3. For each **non-recovery-grade** pending event: verify the referenced entity state exists; if consistent, confirm; if the state is demonstrably absent (the transaction was lost and the event is informational, so nothing can be re-applied), mark the event `orphaned` — never delivered, never deleted, counted on the health panel, audited.
4. Resume normal per-subscriber delivery from cursors.
5. Report the reconciliation window (event count, re-applied count, orphan count) in the startup health summary and audit — the crash is *explained*, per SEC-009 and 07 F2/F3 ("re-applied from event log or visibly reported as lost — never half-applied").

**Why event-first, not state-first.** State-first + crash = committed truth with no event = a missed `deadline.approaching` = exactly the fire-and-forget failure D006 rejected ("missed deadline alerts → R9 trust collapse"). Event-first + reconciliation converts "lost event" (silent, catastrophic) into "ghost event" (loud, mechanically resolvable). 07 DB-001 already committed the system to this ordering for memory writes; EB-004 generalizes it.

**Alternatives.** Transactional outbox inside `kang.db` (perfect atomicity; rejected: it places the durability net inside the `synchronous=NORMAL` file it exists to protect, defeating DB-001's pairing — and it duplicates `change_log`'s shape); two-phase commit across the two SQLite files (machinery without a coordinator to justify it; E1 violation); accepting rare silent loss with a report (rejected: 07 already promised replay; weakening it now is a constitution edit, not a design choice).

**Trade-offs.** Reconciliation is the most intricate mechanism in the bus (~a page of careful code plus tests). Accepted, with a containment rule: **reconciliation logic MUST live in one module, MUST be exercised by the crash-replay CI class (13 §2.5), and MUST NOT grow features.** It re-applies and reports; it never decides.

**Implications.** The `pending → confirmed | orphaned` state column exists in the DDL (§5.2). Crash-replay fault injection (13 §2.5) MUST kill the process between every pair of steps 1–5 and assert convergence.

---

## 5. EB-005 — The Event Envelope and the Event Log Schema

### 5.1 Envelope (normative, closed; additive evolution only per API-005/D006)

| Field | Type | Semantics |
|---|---|---|
| `seq` | integer | Monotonic append order from the single writer. **The ordering truth** (§7). Never exposed outside the machine |
| `event_id` | UUIDv7 | Global identity; dedup key for every consumer; time-sortable |
| `type` | text | Registry-closed enum (§6.3), namespaced (`kang` core unprefixed; `plugin.{id}.*` per 08 §4) |
| `type_version` | integer | Payload schema version. Schemas are append-only: add optional fields, never repurpose (D006) |
| `occurred_at` | ISO-8601 | When the fact became true (injected clock — 11_CODING) |
| `recorded_at` | ISO-8601 | When appended. Differs from `occurred_at` during catch-up and backfill; consumers MUST NOT assume equality |
| `principal` | text | Publisher identity: `kang`, `kernel:{component}`, `agent:{name}`, `plugin.{id}` (SEC-006: attributable) |
| `correlation_id` | UUIDv7 | The one thread: click → invocation → tools → audit → event (SEC-006, D015, 12_API §5) |
| `causation_id` | UUIDv7, nullable | **`event_id` of the direct parent event**, if this event exists because a handler/job reacted to another event. Null for root causes (Kang, schedule, external observation) |
| `entity_refs` | array | Typed refs `{kind, id}` for subscription filtering and client resume (12_API §6) |
| `payload` | JSON | Schema-validated per `type`+`type_version`. Recovery-grade types: self-sufficient (§3) |
| `provenance` | enum | `kang` \| `derived` \| `external_untrusted`. UNTRUSTED propagates transitively into event payloads carrying external content (SEC-001) — the label survives the bus |
| `recovery_grade` | boolean | §3. Denormalized from the registry into each row so the log is self-describing during recovery (recovery cannot depend on `kang.db` being readable) |
| `device_id` | text | Sync-quartet discipline (D009): cheap now, impossible to retrofit |

**On `causation_id` (the one new concept).** `correlation_id` threads a whole causal episode; it cannot express *depth* or *parenthood* within it. `causation_id` buys, for one nullable column: (a) `kang explain` renders event *chains* — "this notification ← deadline.approaching ← plan.generated ← job:morning_plan"; (b) the runtime cycle guard (§11.1) has a substrate; (c) replay tooling can reconstruct exact fan-out trees. Rejected alternative: a full `causation_chain` array (unbounded growth in the hot path; the chain is recoverable by walking parents).

**Deliberately absent:** per-event hash chaining or signatures (tamper evidence is the audit log's single responsibility — SEC-013; duplicating it here is duplicated truth and false comfort, since eventlog.db is honest-limits tamper-*evident* at best); per-event TTL (retention is a log policy, not an envelope field); priority (priority systems are conflict systems — 08 §7's reasoning, adopted).

### 5.2 `eventlog.db` schema (fills the DDL gap in 07_DATABASE Part V)

DDL: 07_DATABASE §5.0 (cite-only per this document's anti-duplication rule). EB-005 retains authority over envelope semantics; 07 owns the physical schema.

Index doctrine per 07 Part VI: every index cites its consumer; speculative indexes forbidden. Compaction (90 days, D006) deletes `confirmed` events below every subscriber's cursor; `orphaned` rows and unresolved `dead_letter` rows are **never compacted away silently** — they are surfaced until Kang resolves them.

---

## 6. EB-006 — Event Categories: A Closed Taxonomy

### 6.1 The taxonomy (closed; additions require an ADR, like Memory's type list)

| Category | Definition | Examples | Recovery-grade? |
|---|---|---|---|
| **Domain** | Tier-1 truth changed | `task.completed`, `deadline.approaching`, `competition.found`, `memory.saved`, `plan.generated` | Mostly yes |
| **System** | Health/ops fact | `provider.circuit_open`, `integrity.frozen`, `backup.verified`, `budget.threshold_crossed` | No |
| **Lifecycle** | Execution-machinery fact | `invocation.finished`, `task.updated` (API long-running tasks), `held_action.approved`, `plugin.quarantined` | `held_action.approved`: yes; others no |
| **Integration** | External-world observation crossed the boundary | `vault.note_changed`, `calendar.synced`, `capture.created` | No (truth lives at the source — AR6) |
| **Plugin** | `plugin.{id}.*`, manifest-declared schemas | per 08 §7 | No (plugins cannot write Tier-1 truth directly — PL rules) |
| **Notification** | A notification became due per policy | `notification.requested` | No |

Integrity incidents (10_SECURITY §6: "a first-class event class") are **System** events with a fixed subtype set mirroring 07 Part 15's F-codes.

### 6.2 The `notification.requested` ruling (tension resolved, not renamed)

The name is a command smell — it appears to demand that the notifier act, violating EB-001. It is, however, already shipped constitutional vocabulary (12_API §7 boundary rule, 09_UI §9). Ruling:

- **Semantics are fixed, name is kept:** the *fact* is "a notification became due under the ladder policy." The durable work item is the notification queue row (state, in `kang.db`), written in the same flow. The notifier consumes the fact idempotently and drains the queue; if the event is lost to a crash, the queue row still exists and the notifier's catch-up sweep (D014 semantics) finds it. The event is an accelerant, not the work item.
- **Naming rule, forward-binding:** no new `*.requested` event types, ever. New work items get a state row plus a past-tense `*.queued` fact. This section exists so the exception cannot become a pattern.

### 6.3 The Event Type Registry

**Decision.** All event types live in one machine-readable registry (name, category, `type_version`, payload schema, `recovery_grade`, plugin-visible flag, version-introduced, deprecation status), served alongside the Operation Registry (12_API §16 — same mechanism, same source-of-truth doctrine: *the registry is the contract; this document is its constitution*). Publishing an unregistered type is a bug-level failure (rejected at validation, alerted). CI verifies: every registered type has a schema, a test fixture, and — if recovery-grade — a payload-sufficiency test (§3).

---

## 7. EB-007 — Delivery: Per-Subscriber Cursors, FIFO Per Subscriber, Dead Letters

**Decision.**

1. **Publication order is total and deterministic:** `seq`, assigned by the single writer (free consequence of D001). This is the only ordering the system relies on.
2. **Per-subscriber independent cursors.** Each subscriber owns a durable cursor (`subscription_cursor`). Delivery to one subscriber is strictly FIFO by `seq`. A slow or failing subscriber falls behind on *its own cursor*; it never blocks any other subscriber (D006's isolation, made mechanical). Cursor advance is the delivery acknowledgment.
3. **Across subscribers: concurrent and unordered, by design.** The determinism claim, stated honestly: publication order and per-subscriber delivery order are deterministic; cross-subscriber *completion interleaving* is not. **Correctness MUST NOT depend on cross-subscriber timing** — a testable rule (§16), the bus-level twin of 13 §2.6.
4. **Retries:** failed handler → retry with exponential backoff, **maximum 5 attempts**, then dead-letter. The subscriber's cursor advances past a dead-lettered event (one poison event MUST NOT starve a subscriber's entire stream).
5. **Dead letters:** a `dead_letter` row (§5.2); health-panel count (already specced — 05 §14, D015 §3); notification per the ladder at first occurrence. Actions are **Kang-only**: `redeliver` or `discard`, both audited with reason. Dead letters are never auto-discarded and never auto-redelivered — an event that failed five times will fail a sixth without a human looking at why (fail visibly, DB-P7/SEC-009).
6. **Idempotency:** consumers dedup on `event_id` (cite: D006, AGP-3, 08 §6 — no new rule).
7. **Plugin subscriber order:** lexical by `plugin_id` (08 §7 — cite only). Core subscribers within one event: registration order, which is deterministic module-load order; documented, not configurable (same anti-priority reasoning).

**Alternatives.** Single shared cursor with slowest-subscriber backpressure (rejected: one hung plugin handler stalls deadline alerts — unacceptable coupling); unordered delivery with client reordering (rejected: pushes complexity into every handler for zero gain in one process); configurable subscriber priorities (rejected per 08 §7: priority systems are conflict systems).

**Trade-offs.** N cursors instead of one dispatch loop; a dead-lettered event means one subscriber permanently missed one fact unless Kang redelivers. Both accepted — visibility over lockstep.

**Implications.** The sidecar future (§15.1) is already paid for: a sidecar is just a cursor whose delivery hop is a socket.

---

## 8. EB-008 — The Three-Log Boundary (no duplicated truth)

KANG persists three "what happened" records. They coexist legitimately **only** because each answers a different question at a different granularity, and the boundary is now law:

| Log | Question it answers | Granularity | Consumer | Retention | Authority |
|---|---|---|---|---|---|
| `change_log` (kang.db §5.6) | *What bytes changed?* | Row/field mutation | Sync engine (v0.5), point-in-time tooling | 90d rotation until sync | Never — pure capture |
| `eventlog.db` | *What happened, machine-consumable?* | Semantic fact | Subscribers, crash redo, client resume | 90d compaction | Never for current state; transiently authoritative only during §4 reconciliation |
| `audit/*.jsonl` | *Who did what and why?* | Accountability narrative | Kang, `kang explain`, evidence | Permanent, hash-chained (SEC-013) | The permanent record |

**Normative rules:**

1. **No log may be reconstructed as authority from another.** Deriving audit entries from events, or events from change rows, creates a second authority and is forbidden. (The audit subscriber in D006's diagram *observes* events to enrich audit context; audit entries for actions are written by the acting components themselves, per SEC-006 — the subscriber adds, never substitutes.)
2. **One semantic event ≠ one row change.** `deadline.approaching` changes no row; one `plan.generated` changes many. This granularity mismatch is *why* collapsing eventlog into change_log was rejected — that, plus coupling sync retention to delivery retention, plus making the sync outbox load-bearing for crash recovery.
3. **Dependency direction for explanation:** `explain.invocation` (12_API §12, ≥180-day guarantee) reconstructs from `invocation` rows, manifests, and audit in permanent storage — **it MUST NOT read the event log**, whose 90-day retention would silently break the 180-day promise at day 91. Event-chain rendering (§13) is an *enrichment* available within retention, degrading gracefully to the audit-based reconstruction outside it.

---

## 9. EB-009 — Replay: Three Sanctioned Forms, Nothing Else

**Decision.** KANG is **not event-sourced** (rejected in 06_MEMORY and 12_API; reaffirmed here as the bus's own law). State is the truth; the event log is exhaust plus a bounded redo net. Replay exists in exactly three forms:

1. **Crash redo** — the §4 reconciliation pass over the pending window.
2. **Snapshot gap-fill** — restore verified snapshot, replay post-snapshot recovery-grade events (07 Part 15 F1; DB-001 pairing).
3. **Test-harness replay** — scripted-scenario convergence (13 §2.5), deliberately the foundation of the future sync harness.

**Replay CANNOT and MUST NOT attempt to rebuild:**
- `kang.db` from empty — the log is 90 days deep and was never the state model.
- The audit log — a regenerated audit log is a forged audit log (SEC-013's evidence stance).
- External side effects. **`replay_mode` is a kernel flag honored by the tool executor: while set, all world-touching tools (notify, calendar, email-draft, vault-write, web) are denied outright, denials audited as replay-suppressed.** Replay converges state; it never re-sends a notification or re-writes a calendar.

**Derived stores rebuild from truth, not from events.** `link_index`, vault index, embeddings, caches rebuild from their sources of truth (AR6, D008) via their indexers. "Replay events to rebuild the index" is architecturally wrong twice over (wrong source, insufficient depth) and is hereby pre-rejected.

**Alternatives.** Full event sourcing with projections (rejected upstream, twice); no replay at all (rejected: 07's recovery tables already promise it); user-facing time-travel ("show me my system as of March") — RESERVED, trigger: a real need after sync ships; episodic memory (06) already answers most "what was true then" questions at the human level.

---

## 10. EB-010 — Publication and Subscription Authority

**Decision.** The bus is inside the trust-boundary chain (10_SECURITY §3); authority is capability-based (SEC-004), checked at two moments and only two:

1. **At publish** (every event): the envelope validator checks (a) schema validity, (b) namespace ownership — core principals publish core types; `plugin.{id}` publishes only `plugin.{id}.*` (08 §4/§5, install-time collision rules cited); (c) the publish capability itself (`events.publish:{namespace}` in `permissions.toml`, default-deny like everything). Agents do not publish directly — domain services and the kernel publish on the truth they own; an agent's output becomes an event only after the owning service commits it. (Consequence of SEC-002: model-influenced text acquires facthood only by passing a gate.)
2. **At subscribe** (grant time, not delivery time): subscriptions are declared (agent definitions, plugin manifests, kernel registrations) and scoped. Plugins receive only the Appendix-D visible subset (08 — cite). Delivering a fact a principal is scoped for is not an action and is not re-checked per delivery — per-delivery permission checks would be theater with a latency bill.

**Scope-filtered payload projection (small new mechanism).** One event, per-subscriber projection at delivery: a subscriber lacking the relevant read scope receives the envelope + entity refs with the sensitive payload fields elided. This is the mechanism behind 08 Appendix D's existing rule ("`memory.saved` — id + type only; content requires read scope") — stated here once so it is one mechanism, not per-type improvisation. Projection rules live in the event registry beside the schema. Sensitive-context events (private-anything, `memory.contested` details) remain entirely unpublished to plugin subscribers (Appendix D — cite).

**Events grant nothing.** Receiving an event confers no authority, no confirmation, no elevation (12_API §6, SEC-003/-008). An event payload containing the text "approved" approves nothing — approval is `held_action.approve` from a first-party UI session, out-of-band, forever.

---

## 11. EB-011 — Cycle Defense and Flood Control

### 11.1 The feedback-loop hole, closed

Jobs publish events (D014); jobs can be event-triggered (`schedule = 'event:{type}'`, 07 §5.5 DDL). Therefore event → job → event → job cycles are *constructible today*, and pipelines' bounded-DAG guarantee (AG-001) does not cover them. Two cheap layers, both REQUIRED:

1. **Static lint (install/startup/CI):** build the declared graph — event types → triggered jobs → event types those jobs' agents/services can publish. A cycle in the declared graph rejects the definition set, naming the cycle. Catches every declared loop before it runs.
2. **Runtime causation-depth guard:** walking `causation_id` parents, a chain deeper than **16** MUST NOT publish further — the event is appended, marked, dead-lettered for its would-be triggers, and raises a `system.causation_depth_exceeded` health alert. Catches data-dependent loops the static lint cannot see. The cap is admittedly arbitrary; any small bound works — legitimate KANG chains observed in the pipeline catalog are ≤ 5 deep. Changing the cap is a config value with an audit entry, not an ADR.

**Alternatives.** Forbid event-triggered jobs entirely (rejected: kills a legitimate D014 feature — monitors and workflow automation compose on it); rate-limiting as the only guard (rejected: a slow infinite loop is still infinite; depth is the correct dimension).

### 11.2 The filesystem-watcher rule (flood control at the source)

**Raw watcher ticks are not events.** The vault adapter debounces and batches filesystem notifications internally; only *semantic* facts reach the bus (`vault.note_changed` with a note ref, or a single `vault.sweep_completed {changed: n}` for bulk operations). A git pull or sync touching 3,000 files MUST NOT publish 3,000 events — the indexer processes the batch and publishes sweep-level facts. Threshold (batch if > 20 file changes within the debounce window) lives in config, not code. Generalized rule: **any adapter observing a high-frequency external source owns its own debouncing; the bus is never the shock absorber** (that is what made the litmus test in §1 exclude raw ticks).

Plugin flood caps: 100 events/min, breach = failure event toward quarantine (08 Appendix A — cite). Core publishers have no hard cap; a core publisher exceeding ~50 events/s sustained trips a health warning (§14) — a diagnostic, not a limiter, because throttling truth is worse than reporting a bug.

---

## 12. Interactions With the Rest of the System (mostly cite-only)

| Subsystem | Contract | Source | This doc adds |
|---|---|---|---|
| **Agents** | Event-triggered mode: bus → **Orchestrator** (never agent directly); admission, idempotency key derived from `event_id`, budget + concurrency caps apply; headless-safe | 05 §6, AGP-3 | An event storm degrades to a queue behind the caps — never a stampede. Stated as a test obligation (§16) |
| **Memory** | Write gate + event pairing (durability); `memory.saved` projection; events never bypass the gate — an event *about* a memory is not a memory (M-003 untouched) | 07 DB-001, 06 Part IV, 08 App D | The projection mechanism (§10) as the single implementation of App D's rule |
| **Plugins** | Observational subscriptions only; three lifecycle hooks; namespacing; lexical order; flood caps; quarantine at 3 consecutive failures | 08 §7, PL-008/-009 | Dead-lettered plugin deliveries count as failures toward quarantine accounting |
| **Scheduler** | Jobs publish; jobs subscribe via `event:{type}` schedules; catch-up policies unchanged | D014, 07 §5.5 | The §11.1 cycle defense; clarification that event-triggered jobs obey their own catch-up policy for events missed while down (the cursor makes "missed" well-defined) |
| **API event channel** | The bus vocabulary IS the API event vocabulary; client resume by cursor within retention; clients are subscribers with sessions as principals | 12_API §6 | Envelope extensions (§5.1) flow to the channel additively (API-005-compliant) |
| **UI** | "What changed?" dashboard zone = cursor resume; notifications originate exclusively from `notification.requested` | 09_UI, 12_API §11 | §6.2's semantics ruling |
| **Explainability** | correlation_id threads everything; `explain.invocation` from permanent storage | SEC-006/-010, 12 §12, 05 §14 | Causation-chain rendering as enrichment within retention; hard rule that explain never *depends* on the event log (§8.3) |
| **Security** | Events carry zero authority; UNTRUSTED provenance propagates; security failures emit typed events; incidents are System events | SEC-001/-002/-009, 10 §6 | Nothing — by design. If this document had needed to add security mechanism, that would itself have been a finding |

---

## 13. Failure Handling (consolidated matrix)

| Failure | Behavior | Grounded in |
|---|---|---|
| Handler exception | Supervised capture → retry ×5 backoff → dead-letter; siblings unaffected; cursor advances | D006, §7 |
| Handler timeout | Per-class timeout (plugin handlers: 30 s, 08 App A; core handlers: 30 s default in registry) → counts as failure attempt | 08 App A, §6.3 |
| Publish validation failure | Bug-level: rejected, alerted, audited. Unregistered type / schema violation / namespace violation never enters the log | §6.3, §10 |
| Crash pre-append | Command fails visibly; idempotent retry | §4 |
| Ghost event (crash mid-sequence) | Startup reconciliation: re-apply / confirm / orphan; window reported | §4 |
| Crash post-confirm, pre-delivery | Redelivery from cursors; handler idempotency absorbs duplicates | D006 |
| `eventlog.db` corruption | SQLite integrity discipline: daily check, own `VACUUM INTO` backup (07 Part 12); worst-case total loss = loss of *delivery state and ≤90 days of operational history*, **never truth** — the payoff of not being event-sourced, and the reason the two files have separate recovery domains | 07 §1.2, §9 |
| Dead-letter accumulation | Health-panel count; notification ladder; Kang-only redeliver/discard, audited | §7.5, D015 |
| Causation depth exceeded | Publication halted at 16; alert; dead-letter of would-be triggers | §11.1 |
| Event storm from adapter | Prevented at source (debounce/batch); core-rate health warning as backstop | §11.2, §14 |

---

## 14. Performance Expectations (design targets, not measurements)

Honesty flag: the numbers below are engineering targets from known SQLite behavior at personal scale; they MUST be validated in the 13_TESTING §5 performance-budget suite on the 10-year corpus before v0.2, and the suite's measured numbers supersede these on divergence.

| Metric | Target | Rationale |
|---|---|---|
| Publish → durable append, p95 | < 10 ms | One `synchronous=FULL` insert on NVMe; the hot-path cost of the redo duty, paid knowingly |
| Append → all local cursor deliveries dispatched, p95 | < 50 ms | In-process fan-out; no serialization boundary |
| Sustained throughput without backlog | 50 events/s | ~100× expected personal-scale load (realistic: hundreds to low thousands of events/day) |
| Event log size at 10 years | ≪ 1 GB effective | 90-day retention makes this a rolling window, not an accumulation; included in 07's ≤15 GB table by construction |
| Reconciliation pass at startup | < 2 s typical (empty pending set: < 50 ms) | Pending window is normally zero; after a crash it is the final seconds of activity |

There is no performance problem to engineer around at this scale. The only real risk was adapter floods, and §11.2 solved it at the source rather than with throughput.

---

## 15. Future Compatibility

### 15.1 Sidecars (D001's escape hatch) — already paid for
A sidecar subscriber is a `subscription_cursor` row whose delivery hop is a local socket instead of an in-process call. The durable log + per-subscriber cursors were designed as exactly this handoff (D006 scaling note). No envelope, schema, or semantics change. The socket transport is RESERVED; trigger: first out-of-process component (Phase-2 plugin isolation or a GPU model host, per D012/§19 of 04).

### 15.2 Multi-device sync — events do NOT sync (RESERVED hazard registered)
Sync replicates *state* via `change_log` (D009); each device derives its own events from its own activity and from applied change-sets. The event log is a per-device operational artifact (`device_id` marks it honestly). **Registered hazard for 16_SYNC:** two devices independently deriving `deadline.approaching` from replicated state will double-fire notifications. Likely resolution: device affinity on notification-producing jobs — the `runs_on` field already reserved in agent definitions (05 §17). Trigger: 16_SYNC design at v0.5. Deliberately not solved now (P9; solving sync semantics before sync exists is how phantom requirements calcify).

### 15.3 External integrations — the bus has no network listener, ever, in v0.x
Inbound external signals (webhooks, provider callbacks, watched sources) arrive as **adapter observations** → Integration events with `provenance=external_untrusted`. Remote publication into the bus does not exist; there is no port, no endpoint, no auth story to get wrong (12_API: local-only forever; SEC-001 at ingress). If a future need appears, it is an adapter that *observes* and publishes under its own principal — the bus's trust model never changes.

### 15.4 Remote workers
Same answer as sidecars: a cursor over a transport, with the Orchestrator remaining the sole execution authority (AG-001 is transport-independent).

---

## 16. Testing Obligations (bindings into 13_TESTING's classes)

1. **Crash-replay class (13 §2.5):** fault-inject a kill between every adjacent pair of §4's steps 1–5; assert reconciliation convergence, no partial truth, correct orphan accounting.
2. **Payload sufficiency (new, per §3):** for every recovery-grade type: apply the fixture event to an empty store; assert the resulting record equals the recorded record. A recovery-grade type without this test fails CI.
3. **Determinism (13 §2.6):** same scenario ⇒ identical `seq` ordering and identical per-subscriber delivery order; a test that asserts cross-subscriber completion order is itself a defect.
4. **Poison event:** a permanently failing handler dead-letters at attempt 5 and its subscriber's stream continues past it; siblings never observe the failure.
5. **Cycle guard:** a fixture definition set containing a declared cycle is rejected by the lint with the cycle named; a runtime synthetic loop halts at depth 16 with the alert raised.
6. **Storm degradation:** publish a burst of event-trigger events; assert Orchestrator admission queues within concurrency caps — queue depth grows, invocation concurrency does not.
7. **Projection:** a subscriber without the relevant read scope receives the elided projection; with the scope, the full payload; sensitive-context types never reach plugin subscribers (property-based over the registry, in the spirit of the 05 §17 permission property suite).
8. **Retention boundary:** `explain.invocation` at day 179 for an invocation whose events were compacted at day 91 still reconstructs fully (proves §8.3's dependency direction).
9. **Replay suppression:** under `replay_mode`, every world-touching tool call is denied and audited as replay-suppressed.

---

## 17. Deltas to Upstream Documents (recorded here; to be applied by ADR, not silently)

Per Kang's instruction, no upstream file is edited in this pass. The following additive changes are owed and tracked:

| Doc | Delta | Status |
|---|---|---|
| 07_DATABASE Part V | Adopt §5.2's `eventlog.db` DDL | **Resolved** |
| 12_API §6 | Envelope gains `causation_id`, `type_version`, `provenance` | **Resolved** |
| 12_API §12 | `explain.invocation` MUST NOT depend on the event log | **Resolved** (apply per Problem 3 Step A first) |
| 05_AGENTS §6 | Event-trigger idempotency key derived from `event_id` | **Resolved** |
| 08_PLUGIN §7 / App A | Dead-lettered deliveries count toward quarantine | **Resolved** |
| 03_ROADMAP §8 | Register RESERVED triggers | **Resolved** (apply per #6 above first) |

Until applied, this table is the authoritative record of the divergence — filed openly, per the house rule below.

---

## 18. RESERVED Registry (this document's dormant items)

| Item | Status | Activation trigger |
|---|---|---|
| Socket transport for out-of-process subscribers | Designed-for, unbuilt | First sidecar component (D012 Phase 2 or GPU host) |
| Event handling across devices / double-fire prevention | Hazard registered | 16_SYNC design (v0.5) |
| User-facing time-travel over events | Rejected-for-now | Real need after sync; episodic memory answers the human-level question today |
| Inter-plugin event coupling | Dormant (owned by 08 §7) | ADR with real cases — cited, not duplicated |
| Configurable core-subscriber ordering | Pre-rejected | Never, probably — priority systems are conflict systems |

---

## 19. Closing

One log per question. One vocabulary system-wide. Facts flow out; authority never flows in. The bus delivers at-least-once, recovers loudly, dead-letters visibly, and can explain every chain it caused. It is deliberately the most boring interesting component in KANG — which is exactly what a nervous system should be.

*When code and this document disagree, one of them is wrong on purpose — file the ADR.*
