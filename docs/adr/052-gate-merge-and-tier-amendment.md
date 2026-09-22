# ADR-052 — Two gate holes closed: a non-Kang duplicate never touches an active row, and no agent may claim Tier 2

**Status:** accepted (2026-09-22) — Kang's own "accept it", same session as drafting; Options 1B / 2B / 3B as recommended, D1–D4 accepted as written. Drafted after ADR-051's implementing session escalated two findings instead of deciding them. **Not yet implemented** — implementation is delegated to a separate coding session; its build brief is `docs/guides/session-2026-09-22-adr052-build-brief.md`.
**Date:** 2026-09-22
**Supersedes:** none — this amends ADR-051 D5 and extends its D6; ADR-051 stands, with a dated "Amended by ADR-052" note on each.
**Affected documents (if accepted):** `06_MEMORY.md` §4.2 (a dated amendment: the gate pipeline's flowchart puts the exact-duplicate merge *before* the writer-authorization branch, which lets a non-Kang writer mutate an active record — the node order is corrected, D1); `06_MEMORY.md` §1.4 (a dated note: "Only Kang can create Tier 2" is now enforced at the gate, not merely stated, D2); `docs/adr/051-memory-write-gate.md` D5 and D6 (dated "Amended by ADR-052" notes; no other text touched); `12_API.md` §10 (a dated note: `memory.edit_approve` may set `trust_tier`, D3)
**Cites:** 06_MEMORY §4.2 (the pipeline and its flowchart — `docs/06_MEMORY.md`'s `D -- exact --> MRG` edge, which precedes the `A{"Writer = Kang or registered rule?"}` branch), §1.4 ("Tier 2 — SANCTIONED : Kang said so, confirmed so, or wrote so (vault). Highest trust. **Only Kang can create Tier 2.**"), §1.5 covenant 2 (explainability: provenance answers where a record came from), §2.1 (the type table's own per-type trust-tier column, whose tension with §1.4 is named but not resolved here, D3), §4.1 (the writers table), §12.3 (every gate decision audited, rejections included), **M-003**; 09_UI_DESIGN §6 ("Record view: ... full provenance (source, reason, creator, dates) ... MUST be visible without extra clicks" — why agent-supplied text in `source_detail` is a display surface, D1); 07_DATABASE Part X §5 (merge policy orders by `(revision, device_id)` — why an agent advancing `revision` matters, D1); 10_SECURITY SEC-001 (untrusted content stays untrusted, transitively), SEC-002 (models possess zero authority), §12.4's injection defense-in-depth layers; ADR-051 D4/D5/D6/D10 (the decisions this amends and the pure-function shape that makes the fix small), ADR-048 D1 (the candidate's identity contract, untouched)
**Related:** [[051-memory-write-gate.md]], [[048-memory-truth-schema.md]]

---

## Context

ADR-051 shipped the write gate and its implementing session escalated two findings rather than deciding them — correctly, because both amend an accepted decision. Both were verified independently against the real code on 2026-09-22 before this ADR was drafted, not taken from the report.

**Finding 1 — the exact-duplicate merge lets a non-Kang writer mutate an active record.** `domain/memory/write_gate.py::decide` evaluates `probes.exact_duplicate_id` **before** the `writer.is_kang` branch. A non-Kang proposal whose normalized content exactly matches an `active` record therefore returns `merge`, and `SqliteMemoryStore.merge_provenance` issues `UPDATE memory_record SET source_detail = ?, revision = ?, updated_at = ?, device_id = ?` against that live row. `content`, `created_by` and `status` are untouched; `source_detail`, `revision`, `updated_at` and `device_id` are not.

**This is faithful to ADR-051 D5 and to 06 §4.2 — the hole is in the specification.** 06 §4.2's flowchart genuinely routes `D -- exact --> MRG["merge: bump revision, append provenance, done"]` before reaching `A{"Writer = Kang or registered rule?"}`. Nothing in the document says the merge is Kang-only, and nothing in ADR-051 noticed. The implementer hit it because the schema has no provenance-*list* column, forcing the "append provenance" step to write agent-supplied text into the single `source_detail` TEXT column — which is the moment the problem becomes visible.

Why it matters, stated concretely rather than abstractly. An agent holding `web.fetch` reads a hostile page (SEC-001: untrusted, transitively). The page induces it to propose content it can predict already exists — a record's exact text, which a prior context manifest showed it. The gate merges, and attacker-chosen text lands in the `source_detail` of a record **Kang sanctioned**, which 09 §6 requires the memory browser to display as provenance without extra clicks. The record now reads as Kang-authored and carries text Kang never saw. It also advances `revision`, the field 07 Part X §5 makes the ordering key for future sync merges. No permission was exceeded and no confirmation was skipped — the gate did exactly what it was told.

**Finding 2 — `trust_tier` is proposer-supplied and unconstrained.** The gate validates only `proposal.trust_tier in (0, 1, 2)`. A non-Kang writer may therefore propose `trust_tier=2`, and 06 §4.3's own UX contract is single-keystroke approval. 06 §1.4 states the rule outright — *"Only Kang can create Tier 2"* — and nothing enforced it. ADR-051 D6 enumerated the refusals and omitted this one; that is a gap in the ADR, not in the implementation.

**What is settled and not re-opened:** M-003 and ADR-051 D4 (no non-Kang path to `admit`); the single insert path; ADR-048 D1's candidate identity contract; the absence of the semantic probes (ADR-051 D5's other half, unaffected); every refusal ADR-051 D6 already lists.

---

## Options

### Option 1 — What a non-Kang exact duplicate does (Finding 1)

**1A — Merge, but write the appended provenance only to the audit log, never to the row.** *For:* keeps 06 §4.2's "merge" outcome and still records the second observation. *Against:* the row's `revision` must still bump for the merge to mean anything, so the sync-ordering half of the problem survives; and a "merge" that changes nothing in the merged record is a misleading name for an audit entry.

**1B — A non-Kang exact duplicate is rejected; only Kang's own exact duplicate merges. (Recommended.)** *For:* no agent-supplied byte reaches an active row by any path, which restores the property ADR-051's sweep test asserts for *content* to provenance as well; the second observation still survives in the append-only, Kang-visible audit log (06 §12.3 already requires every gate decision including rejections to be audited, and the implementation already emits `memory.gate.rejected`); the fix is a branch reorder inside a pure function with existing tests, not a new mechanism. Kang's own duplicate still merges, because Kang's text is Kang's. *Against:* an agent that genuinely re-observes a known fact gets a rejection rather than a recorded corroboration on the record itself; the corroboration lives in the audit log, which no retrieval path reads. Named, and acceptable: corroboration-as-signal is a consolidation concern (06 Part VI), not a gate concern, and the consolidator reads episodes and observations, not `source_detail` strings.

**1C — Queue the duplicate like any other proposal.** *For:* Kang decides, so nothing is lost. *Against:* it spends the scarcest resource in the system — Kang's approval attention (06 §4.3's bounded queue is the reason M-003's cost is acceptable) — on a proposal whose content he has already approved once, and approving it would create a second identical record unless approval *also* merges, which reintroduces the mutation this ADR exists to remove.

**A side channel this decision creates, named rather than discovered later.** Any outcome that differs for a duplicate is a membership oracle: a principal with no read scope can learn whether a record with exactly this content exists, by observing `duplicate` versus `queued`. It cannot be closed while the outcomes differ at all (1C closes it only by spending Kang's attention). It is bounded in a way worth stating: the probe requires the attacker to already hold the exact normalized content, so it **confirms a fully-formed guess and cannot enumerate**. Accepted on that basis, and narrowed by not returning the incumbent's id in the error — the caller learns "duplicate", never *which* record.

### Option 2 — A non-Kang proposal claiming Tier 2 (Finding 2)

**2A — Silently clamp to tier 1.** *For:* the proposal still reaches the queue, so a genuine observation is not lost to a metadata mistake. *Against:* it rewrites a writer's own claim without telling it, which is the opposite of this system's posture everywhere else (E9, fail visibly); and the queue would then show Kang a tier the writer never asserted, corrupting the very context he approves against.

**2B — Refuse the proposal with a typed error. (Recommended.)** *For:* enforces 06 §1.4's existing MUST mechanically instead of by hope; matches every other refusal ADR-051 D6 already makes; the writer learns exactly what was wrong and can re-propose honestly. *Against:* an agent with a metadata bug loses a proposal it could have had. Correct trade: the gate refusing a false sanction claim is the gate working.

### Option 3 — How a record legitimately becomes Tier 2 (the question Option 2 opens)

**3A — Approval automatically promotes the landed record to Tier 2.** *For:* §1.4's own words — Tier 2 is what Kang "said so, confirmed so, or wrote so", and approval is confirmation. *Against:* it collides with 06 §2.1's type table, which assigns tiers per *type* (`observation` is flatly "1"), and resolving that collision properly means deciding what an approved `observation` is — a question with no consumer until retrieval weighting exists (§5.2's scoring reads tier). Deciding it here, blind, is how the first hole got made.

**3B — Approval lands the proposed tier unchanged; `memory.edit_approve` gains the ability to set `trust_tier`, so promotion is an explicit Kang act. The §1.4-versus-§2.1 tension is named and left open. (Recommended.)** *For:* closes Option 2's question with a real mechanism that is unambiguously Kang's own hand; adds one optional field to an operation that already exists to mean "approve, with changes"; decides nothing about automatic promotion that a later slice with a real consumer would have to undo. *Against:* until Kang uses it, non-Kang-originated records sit at tier ≤1, so anything that later weights by tier will under-weight them. Acceptable: nothing reads `trust_tier` yet.

---

## Decision

### D1 — A non-Kang exact duplicate is rejected and never touches an active row (Option 1B)

`decide()`'s duplicate branch moves below the writer branch: an exact duplicate yields `merge` **only** when `writer.is_kang`; for every other writer it yields a rejection with code `duplicate`. The rejection is audited as any gate rejection is (06 §12.3), which is where the second observation is preserved. The error message names neither the incumbent's id nor its content.

`merge_provenance` keeps its current behavior and remains reachable — by Kang's own duplicate proposal only. No store, adapter, or schema change.

06 §4.2 receives a dated amendment correcting the flowchart's node order: the writer-authorization branch precedes the merge, and the merge edge is reachable only on the Kang path. ADR-051 D5 receives a dated "Amended by ADR-052" note.

### D2 — A non-Kang proposal carrying `trust_tier=2` is refused (Option 2B)

The gate adds one refusal to ADR-051 D6's list, with its own code (`tier_restricted`), enforcing 06 §1.4's existing "Only Kang can create Tier 2" at the point where it can actually be enforced. Placed with the other writer-class refusals, before the duplicate probe, so a false sanction claim is refused whether or not the content happens to duplicate something.

06 §1.4 receives a dated note recording that the rule is now mechanical rather than stated. ADR-051 D6 receives a dated "Extended by ADR-052" note.

### D3 — `memory.edit_approve` may set `trust_tier`; automatic promotion stays open (Option 3B)

`memory.edit_approve`'s request schema gains an optional `trust_tier`. When present, the landed record carries it; when absent, the proposal's tier lands unchanged, exactly as today. This is the one path by which a non-Kang-originated record reaches Tier 2, and it is an explicit, audited Kang action on a first-party session — §1.4's "confirmed so", made specific.

**Explicitly not decided:** whether plain `memory.approve` should promote automatically, and how 06 §1.4's actor-based tier definition reconciles with 06 §2.1's per-type tier column. Both are named here as open, with the trigger that forces them: the first consumer that actually reads `trust_tier`, which is the hybrid scorer's tier term (06 §5.2) in the retrieval slice.

### D4 — What this ADR does not do

No schema change, no migration, no new port or store method, no new operation, no change to the queue, the event, the config, or the job. No change to ADR-051 D4's admission rule, which was never in question. The semantic probes remain absent (ADR-051 D5's other half stands).

---

## Consequences

**What becomes true.** No byte supplied by a non-Kang principal reaches an active `memory_record` row by any path — the property ADR-051's registry sweep already asserts for `content`, now true of provenance and of `revision` as well, and assertable by the same sweep. 06 §1.4's Tier-2 rule stops being a sentence and starts being a refusal. A prompt-injection chain that reaches an agent can no longer write attacker-chosen text into a record Kang sanctioned, nor advance that record's sync-ordering key.

**What becomes harder, or costs something.** An agent that genuinely re-observes a known fact now gets a rejection, and the corroboration lives only in the audit log, which no retrieval path reads — so "this was independently observed three times" is not, and for now will not be, visible as record state. The duplicate outcome remains a bounded membership oracle (confirm-a-guess, never enumerate), documented in Option 1 rather than left for someone to find. And until Kang uses `edit_approve`'s new field, non-Kang-originated records sit at tier ≤1, which will matter the day the scorer reads tier and not before.

**Named, not decided:** automatic tier promotion on approval and the §1.4/§2.1 reconciliation (trigger: the retrieval slice's scorer); whether corroboration count deserves to be record state rather than audit state (trigger: a consolidation pass that wants it); the semantic probes (trigger: embeddings).

## Verification

**Not yet implemented.** What would prove this ADR: a pure-gate unit test that a non-Kang writer proposing an exact duplicate is rejected with `duplicate` while Kang proposing the same duplicate still merges; a test that the rejection's message contains neither the incumbent id nor its content; a test that a non-Kang proposal with `trust_tier=2` is refused *before* the duplicate probe, so it is refused whether or not it duplicates; a store-level assertion that `merge_provenance` is unreachable from any non-Kang path; an extension of ADR-051's registry sweep closing **two independent gaps that each hid this, verified in the test's own source on 2026-09-22**: its `_records()` helper selects `id, type, status, content, trust_tier, sensitivity, reason, created_by, source_kind` and therefore omits all four columns the merge writes (`source_detail`, `revision`, `updated_at`, `device_id`), and its adversarial content never equals a seeded record's, so the duplicate probe never fires during the sweep at all. Both need closing — select every column, and include an exact-duplicate-of-Kang's-record proposal among the adversarial params — or the sweep will keep passing over this class of defect. (A third thing the same source shows, and worth knowing: the sweep already proposes `trust_tier=2` from an agent principal and passes, because the proposal is queued rather than admitted — the tier claim lands in the *queue*, which is precisely the laundering surface D2 closes and which no record-table assertion could ever have caught.) Plus: an `edit_approve` test landing an explicitly-set tier and one landing the proposal's tier when the field is absent; and the existing 1051/357/15 counts moving only by the new items.
