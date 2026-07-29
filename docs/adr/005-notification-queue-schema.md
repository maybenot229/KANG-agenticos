# ADR-005 — The notification queue schema

**Status:** accepted
**Date:** 2026-07-26
**Affected documents:** 07_DATABASE §5.2 (gains a `notification` table — the schema addition this ADR authorizes), 09_UI §9 (the ladder this table's `priority` enum mirrors), 12_API §13 (`notification.list/ack`)
**Cites:** 15 §6.2 (the accelerant ruling: the queue row is the durable work item), EB-008 (the three-log boundary — why the event log is not the queue), 05_AGENTS §13 (the interruption ladder), 15 §15.2 (the RESERVED cross-device hazard)
**Related:** [[004-m5-event-types.md]] (registers `notification.requested`, the event this row is accelerated by)

---

## Context

15 §6.2 resolved the `notification.requested` naming tension by ruling that
**the durable work item is a notification queue row**, and the event is only
an accelerant: "if the event is lost to a crash, the queue row still exists
and the notifier's catch-up sweep finds it."

That row was never designed. `07_DATABASE.md` documents 33 tables; none is a
notification queue. The ruling depends on a table that does not exist.

Surrounding constraints already fixed elsewhere:

- **09_UI §9 / 05_AGENTS §13** fix the priority ladder: `critical`,
  `attention`, `digest`, `silent`.
- **12 §13** fixes acknowledgement: "`notification.list/ack` — acking is a
  command (it changes beacon state); **acks never delete history**." The
  schema must therefore record acknowledgement additively, never by deleting
  or overwriting away the record.
- **12 §14** fixes the origin: "Notifications originate exclusively from core
  `notification.requested` events; clients render, ack, and deep-link — they
  MUST NOT mint notifications."
- **12 §12** requires `explain.notification {id}` to resolve, so the row must
  thread back to what caused it.

## Options

### Option A — New `notification` table carrying the full sync quartet

`device_id` + `revision` alongside the state columns, matching `task`,
`deadline`, and every other synchronizable entity.

- **For:** consistent with the dominant table shape; D009 warns the quartet
  is "cheap now, impossible to retrofit," which argues for adding it
  pre-emptively.
- **Against:** it silently answers a question the constitution has
  explicitly left open. 15 §15.2 registers "**Event handling across devices /
  double-fire prevention**" as a RESERVED hazard whose trigger is 16_SYNC's
  design — i.e. whether acking a notification on the phone clears it on the
  desktop is *undecided by reservation*. Shipping the quartet now pre-commits
  the answer as a side effect of a schema choice, which is exactly the kind
  of accidental decision the RESERVED registry exists to prevent.

### Option B — New `notification` table, no sync quartet: per-device operational state (recommended)

- **For:** matches the established precedent for operational tables, which is
  explicit and cited rather than inferred. `0002_held_action.sql` states it
  directly: "Held actions are per-device operational confirmations, not
  synchronizable truth — no sync quartet (they do not replicate; a
  confirmation belongs to the device that asked)." `0004_api.sql` says the
  same of `invocation`, `idempotency_key`, and `session`: "these are
  execution/observability infrastructure, not synchronizable domain truth."
  A notification's state — *was this shown on this screen, did Kang ack it
  here* — is the same class of fact. It also leaves 15 §15.2's hazard
  genuinely open for 16_SYNC to decide.
- **Against:** if 16_SYNC later rules that notification state *should*
  replicate, adding the quartet is a migration. Accepted, and bounded: unlike
  a task or memory record, notification rows are short-lived operational
  state, so a retrofit forfeits little history — the D009 "impossible to
  retrofit" concern is about losing a decade of provenance, which this table
  will never hold.

### Option C — Reuse the `event` table as the queue

- **For:** no new table.
- **Against:** conflates a semantic-fact log with a stateful work-item queue,
  which is precisely the coupling EB-008's three-log boundary forbids
  ("eventlog.db … Never for current state"). It would also put mutable
  delivery state inside an append-only log on a 90-day compaction clock,
  making acknowledgement history expire on the log's schedule rather than the
  product's. Rejected.

## Decision

Adopt **Option B**: a new `notification` table in 07_DATABASE §5.2, with no
sync quartet.

```sql
CREATE TABLE notification (
  id             TEXT PRIMARY KEY,     -- UUIDv7
  priority       TEXT NOT NULL CHECK (priority IN
                   ('critical','attention','digest','silent')),
  principal      TEXT NOT NULL,        -- who caused it (SEC-006)
  correlation_id TEXT NOT NULL,        -- threads to explain.notification (12 §12)
  entity_refs    TEXT NOT NULL,        -- JSON [{kind,id}] for deep-linking
  payload        TEXT NOT NULL,        -- JSON: what to render
  state          TEXT NOT NULL DEFAULT 'queued' CHECK (state IN
                   ('queued','delivered','batched','suppressed','acked')),
  created_at     TEXT NOT NULL,
  delivered_at   TEXT,
  acked_at       TEXT
);
```

`delivered_at` and `acked_at` are additive stamps beside a preserved row, not
replacements for it — 12 §13's "acks never delete history," expressed in the
schema rather than trusted to the caller.

## Consequences

- 07_DATABASE §5.2 gains this table; the migration that creates it cites this
  ADR, and its comment states the no-quartet rationale so the omission reads
  as deliberate rather than forgotten (the same way `0002_held_action.sql`
  does).
- The notifier drains this table; `notification.requested` only accelerates
  it. A lost event costs latency, never a lost notification — which is the
  behaviour 15 §6.2 ruled for, now actually implementable.
- **Tension flagged, not hidden:** 12 §4's resource rules say "every resource
  carries `id` (UUIDv7), `revision`, `updated_at`," and `notification` is in
  that section's resource list. This table has no `revision`. The exception
  is not novel — `invocation` is in the same resource list and also carries
  no `revision`, so operational resources already diverge from that rule in
  practice. Recorded here so the next reader finds a decision rather than an
  apparent oversight; if the divergence should instead be fixed in 12 §4's
  wording, that is a documentation delta, not a schema change.
- **Explicitly deferred:** no `notification.ack` **event** type. 12 §13
  defines acking as a *command* mutating this row's `state`; nothing in M5
  reacts to an ack as a bus fact, and [[004-m5-event-types.md]] records the
  same deferral from the event side.
- **What gets harder:** cross-device notification behaviour is now a question
  16_SYNC must answer explicitly rather than one this schema answered by
  accident. That is the intended trade — a visible open question beats an
  invisible commitment.
