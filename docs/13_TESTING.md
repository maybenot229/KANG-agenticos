# KANG — Testing Constitution

**Document:** 13_TESTING.md
**Version:** 0.1
**Author:** Kang, with Claude (Founding Architect)
**Status:** Normative — defines what must be proven before software is trusted; changes require an ADR
**Last updated:** 2026-07-11
**Upstream (binding):** all prior documents. This document unifies the suites already mandated by `07_DATABASE.md` Part 16, `05_AGENTS.md` §16, `08_PLUGIN_SYSTEM.md` §10, `12_API.md` §16, and `11_CODING_STANDARDS.md` §7 — and adds the classes they don't cover.
**Role:** the constitutional documents make claims. **This document exists to keep those claims true for ten years.** Every MUST in docs 00–12 either has a test class here or is explicitly noted as untestable-by-tooling (and therefore review-guarded).

> RFC-2119 throughout.

---

## 1. Testing Philosophy

1. **Tests are the constitution's enforcement arm.** A specification without a test decays into a suggestion within one refactor. The question for every rule in docs 00–12 is: *which suite would catch its violation?* If the answer is "none," that gap is itself a defect in this document.
2. **Prove properties, not lines.** Coverage percentages measure motion, not truth. KANG tests *invariants*: dependency direction holds; the gate cannot be bypassed; deletion recovers; the plan exists model-less; injection cannot act. A green invariant suite means the architecture is still the architecture.
3. **The trusted parts get the paranoid tests.** Test investment follows the trust hierarchy: memory gate > permission engine > store layer > orchestrator > everything else. A bug in a dashboard card wastes a minute; a bug in the gate poisons a decade (R4, R9).
4. **Determinism is a prerequisite, not a virtue.** A test that can fail without a defect teaches Kang to ignore red. Flaky = quarantined in 24h, fixed or deleted in a week (11_CODING §7).
5. **Reality is simulated honestly.** The synthetic corpus (5- and 10-year profiles, 07_DATABASE Part 16) is a first-class artifact: tests run against *plausible decade-scale data*, because most rot only appears at scale and age.
6. **One maintainer means automation or nothing.** Any verification that relies on Kang remembering to do it will eventually not be done. Everything here runs on a schedule or a gate; human judgment is spent on *reading results*, not producing them.

---

## 2. The Test Taxonomy

### 2.1 Architectural tests (the entropy guards)

Prove the shape of the system, on every commit:

- **Dependency direction:** import-linter contracts (11_CODING §2) — domain imports nothing outer; adapters implement ports; api is thin.
- **Boundary bans:** SQL outside the store layer; `os.environ` outside config; `datetime.now()`/randomness outside ports; bare `create_task` outside kernel; `print` in src; token literals in UI (the full 11_CODING §25 list, as lint tests).
- **Schema linter:** sync quartet present; enums CHECKed; config/setting disjointness; index citations (07_DATABASE Part 16).
- **Vocabulary check:** registry names ↔ schema names ↔ doc glossary (one concept, one name — drift reported).
- **Deletability audit:** each feature's declared file list still corresponds to reality (AR8; sampled per release).

### 2.2 Unit tests

Domain logic against port fakes: pure, fast (< 2 min total), parallel. Every public function's failure modes exercised, not just happy paths. Property-based testing REQUIRED for: the write gate (arbitrary proposals), constraint surfaces (arbitrary invalid rows), scoring math (weight/boundary properties), cursor pagination (no skips/dups under arbitrary mutation).

### 2.3 Integration tests

Adapters against real technology: SQLite in temp dirs; vault operations on fixture vaults; recorded/replayed HTTP for providers (never live network in CI); Tauri-shell smoke on the release pipeline. Each adapter's port-contract compliance is verified by running the *same* test suite against the fake and the real implementation — divergence between fake and real is itself a red build (fakes that lie invalidate every unit test above them).

### 2.4 Contract tests

- **API conformance** (12_API §16): every registered operation vs. its schema, idempotency class, scope requirements, error surfaces; registry diffed against last release — removals/mutations without deprecation records fail.
- **Plugin conformance** (08_PLUGIN §10): the fixture plugin exercising every extension point, SDK door, and containment path; this suite *is* the SDK compatibility promise.
- **Client contract:** UI and CLI built against the generated registry client; unknown-field tolerance tested by injecting future-shaped responses.

### 2.5 Replay tests

New class, formalized here: **the event log and audit trail must support faithful reconstruction.**

- Record a scripted week of activity (fixture scenario) → snapshot → replay the event log against the snapshot → assert convergence with the recorded end-state (validates D006's at-least-once + idempotency claims end-to-end).
- Crash-replay: kill the core at randomized points mid-scenario (fault injection) → restart → assert: no partial truth (DB-003), acknowledged events redelivered, idempotent handlers deduplicate, outcome converges.
- `kang explain` replay: for every invocation in the scenario, the reconstruction renders from persisted data alone (05_AGENTS §14's test, run against the API operation per 12_API §12).

### 2.6 Determinism tests

- Same store snapshot + same recipe ⇒ **byte-identical context manifest** (AG-009).
- Same inputs ⇒ identical plan from the deterministic planner path; identical scoring, ordering, pagination.
- Clock/Rng injection verified: freeze time, assert schedules, decay math, staleness probes compute exactly.
- UI: same API fixtures ⇒ same render tree (snapshot tests on the zone structure — UI-P5's mechanical check). Tooling: Vitest + React Testing Library (ADR-012) — component-level DOM/keyboard-interaction tests, mocking `callOperation` per its own client boundary; not a substitute for live verification against a real Core (ADR-012 §"Consequences").

### 2.7 Permission tests

Property-based, per 05_AGENTS §16: every registered principal × every tool/scope outside its grants ⇒ typed denial + audit entry, zero side effects. Plus: pairing-constraint lints on all definitions and plugin principal-unions; grant-snapshot immutability mid-invocation; denial-spike ⇒ quarantine; plugin sessions attempting `held_action.approve` ⇒ denied at contract (12_API §7); `kang` wildcard uniqueness.

### 2.8 Memory integrity tests

The paranoid tier (§1.3):

- Gate: provenance-absent proposals rejected at schema; AI proposals NEVER reach `active` without an approval command (searched exhaustively: no code path — verified by fuzzing the gate's API surface); `rule`/`profile` writes by non-Kang principals rejected; silence-expiry at 14 days; tombstone-veto on re-insert.
- Lifecycle: every transition in the 06_MEMORY Part III machine reachable only via its declared triggers; illegal transitions raise.
- No-fabrication: retrieval returns store-verbatim content + ids; attribution spot-check harness on fixture outputs.
- Deletion covenant: delete → content gone from record, embedding, FTS, index; tombstone present; 30-day snapshot recovery works; after-window deletion final.
- Conflict protocol: tier-ordered resolution cases; same-tier ⇒ under_review + surfaced.

### 2.9 Security tests

- **Injection red-team suite** (05_AGENTS §16, weekly): hostile corpus (instruction-bearing web pages, emails, vault clippings, model outputs) through every Tier-0-input agent — **zero consequential-action attempts may succeed**; influenced-text cases documented as expected-and-contained. The corpus grows: every new real-world injection pattern published anywhere gets a fixture (a living suite, reviewed quarterly).
- Scrubber: planted secrets in every sink path ⇒ redacted + incident event raised.
- Audit chain: bit-flip a record ⇒ chain verification fails loudly (SEC-013).
- Session: requests without valid sessions refused; plugin sessions correctly principal-bound.
- UNTRUSTED propagation: taint-tracking fixtures — derived summaries of untrusted content carry the tag through to citations.

### 2.10 Plugin tests

Per 08_PLUGIN §10, consolidated: conformance suite; `kang plugin test` envelope; the **zero-hard-dependency release gate** (core green with no plugins / all enabled / all quarantined); lifecycle drills (upgrade rollback, removal export, namespace tombstone); blessed-import AST lint + import-guard trips.

### 2.11 Migration tests

Per 07_DATABASE Part 16: full chain on empty; N-1→N on the 5-year corpus; checksum immutability; provenance-preservation adversarial fixtures; failure-leaves-copy-only proof; old-binary read-only tolerance of newer schema (forward-compat clause).

### 2.12 Performance tests

Budgets are law (07_DATABASE Part 14, 05_AGENTS caps, NFR-001/011): nightly assertion of every budget on the 10-year corpus; trend tracking (a budget passed at 80% last month and 95% this month is a *warning* even while green — regressions are caught by slope, not just threshold); capture-to-saved end-to-end < 5 s measured through the real API path.

### 2.13 Stress tests

Beyond budgets — behavior at the edges, monthly:

- Event storm (10× normal publish rate) ⇒ bus backpressure sane, no loss, dead-letter behavior correct.
- Scheduler pile-up (simulate 3-week downtime, NFR-008) ⇒ catch-up policies execute exactly; no thundering herd; morning plan first (recovery priority order, 10_SECURITY §12).
- Approval-queue overload (500 pending) ⇒ UI/API paginate, expiry works, nothing auto-commits.
- Vault churn (10k file changes) ⇒ indexer converges, watcher doesn't leak.
- Disk-nearly-full ⇒ watchdog halts writes gracefully before SQLite errors (07_DATABASE F4).

### 2.14 Failure recovery tests

Corruption drills per 07_DATABASE Part 15 (weekly): bit-flip fixtures through F1/F6/F7/F8 detection→response→recovery; integrity freeze ⇒ read-only mode ⇒ deterministic plan still renders (SEC-007's availability floor); provider outage mid-plan ⇒ degraded plan with marker (the 04_ARCHITECTURE §18.2 walkthrough, automated).

### 2.15 Backup & restore verification

- CI (synthetic): snapshot → corrupt live → restore → field-level sample equality → event-log replay of the gap (07_DATABASE Part 12).
- **Live** (the real machine): monthly restore-verification job — its result is a health metric with an alert on failure or staleness > 40 days. An unverified backup is treated as no backup — this clause is *executed*, not aspirational.

### 2.16 Explainability verification

- The reconstruction test (SEC-010): sampled invocations across 180 days ⇒ `explain.invocation` renders complete chains; any gap = incident-class failure.
- Every 09_UI §11 why-class has a fixture proving its two-level resolution from persisted data.
- Manifest completeness: every context assembly logs a manifest; assemblies without manifests are impossible (asserted at the assembler's seam).

### 2.17 Golden tests

For outputs whose *shape* is the contract: morning plan structure, evaluation brief structure, critique structure, export format, audit line format, error envelopes. Golden files are versioned; diffs are reviewed like code (a changed golden is a changed promise). Cognitive content inside the shapes is NOT golden-tested (models vary); the schema-validated skeleton is.

---

## 3. CI Requirements & Cadence

| Tier | Runs | Contents | Budget |
|---|---|---|---|
| Commit | every push | format · architectural lints · unit · fast contract | < 5 min |
| Merge | every PR merge | + integration · API/plugin conformance · determinism · permission property suite | < 20 min |
| Nightly | daily | + performance budgets on 10-yr corpus · replay scenario · memory integrity full | < 2 h |
| Weekly | weekly | + injection red-team · corruption drills · migration chain on corpus | — |
| Monthly | monthly | + stress suite · live restore-verification (on the real machine, via the backup_monitor) | — |

Red at any tier blocks its scope (commit-tier blocks merge; nightly red blocks release and pages the health panel). CI definitions are code, reviewed like code (11_CODING §24).

---

## 4. Release Gates (all MUST be green to tag a version)

1. All tiers green, including the most recent weekly.
2. Zero-hard-dependency plugin gate (2.10).
3. The Planner's zero-model deterministic path (release-blocking per 05_AGENTS §16).
4. Migration chain from the previous release's schema, on the corpus.
5. Registry diff clean (no undeprecated removals) — API-005.
6. Performance trend review: no budget above 90% utilization without a filed issue.
7. Golden diffs reviewed and accepted.
8. Debt register reviewed (11_CODING §26); risk table reviewed (PRD §18).
9. Docs build; ADR index consistent; version notes state data-loss windows if any (07_DATABASE Part 13).

A release that skips a gate is not a release; it is a branch someone is running.

---

## 5. Metrics & Coverage Philosophy

- Tracked: suite pass rates and durations (slope-watched), flaky-quarantine count (target: 0), budget utilization trends, injection-corpus size and pass rate, mean-time-to-red-diagnosis (are failures explainable fast?), live restore-verification age.
- **Line coverage is reported, never gated.** It finds *untested regions* (useful smell); it proves nothing about invariants. The gate is: every normative MUST in docs 00–12 maps to a suite in §2 — that mapping table lives beside this document (`tests/suites/CLAIMS.md`) and is reviewed whenever a constitutional doc changes. *That* is 100%-coverage, defined honestly.

---

## 6. Anti-Patterns (review-fatal)

Testing the mock (asserting the fake did what the fake does) · sleeps as synchronization · live network in CI · tests that share mutable state or order-depend · asserting on log strings instead of typed outcomes · golden-testing model prose · snapshotting entire objects "to be safe" (asserts nothing, breaks on everything) · coverage-chasing tests with no failure mode in mind · disabling a red test to ship (the honest forms are: fix, quarantine-with-issue, or delete-with-reason) · testing private internals through reach-ins (test the surface; if the surface can't reach the behavior, the design is wrong, not the test) · one giant end-to-end that "covers everything" and diagnoses nothing.

---

## 7. Future Extension Points (RESERVED)

| Reservation | Trigger |
|---|---|
| Sync convergence suites (two-device divergence/merge/conflict-surfacing scenarios) | 16_SYNC design (v0.5) — the replay harness of 2.5 is deliberately its foundation |
| Sidecar/IPC contract tests (plugin protocol over the process boundary) | PL-001 Phase 2 |
| Model-quality evals (prompt regression harness: are critiques still sharp, plans still sensible) | First prompt-change dispute; the golden *shapes* of 2.17 are the scaffold |
| Learned-reranker evaluation (retrieval quality vs. manifest-logged history) | 06_MEMORY Part XV, year 2+ |
| Voice/mobile client conformance | Their ADRs; both are registry clients, so 2.4 extends rather than multiplies |

---

## Constitutional summary

KANG is trusted exactly as far as it is proven. The architecture is proven by lints that never sleep; the gates and permissions by properties, not examples; the memory by paranoia proportional to its sanctity; recovery by drills, not hope; and every claim in the constitution by a named suite that fails when the claim stops being true. A green build means the promises still hold — and that is the only thing a green build means.

*When a test and the constitution disagree, one of them is wrong on purpose — file the ADR.*
