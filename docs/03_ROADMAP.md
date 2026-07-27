# KANG — Architectural Roadmap

**Document:** 03_ROADMAP.md
**Version:** 0.1
**Author:** Kang, with Claude (Founding Architect)
**Status:** Living — the only Phase-0 document *expected* to be revised at every version boundary; revisions follow the review ritual in §9
**Last updated:** 2026-07-11
**Upstream (binding):** the entire constitution (00–18, per docs/INDEX.md). This document sequences it; it never overrides it.

> This is not a feature checklist. It is the plan for how KANG grows from zero lines to potentially several hundred thousand lines over a decade **without becoming a system nobody understands** — including the person who wrote all of it.

---

## 1. Roadmap Principles

1. **The heartbeat ships first.** A daily plan that exists every morning beats any architecture that doesn't run (Vision §9.3). Phase 1 is deliberately humble.
2. **Never build stage N+1 on an unreliable stage N** (PRD §9). Each phase has *exit criteria*, not just deliverables — the phase isn't done when the code merges; it's done when the criteria hold in daily life.
3. **Infrastructure precedes the features that need it — by exactly one phase, never more.** Building infrastructure two phases early is speculation (R6); building it in the same phase as its first consumer creates rushed foundations. One phase of lead is the deliberate rhythm.
4. **Complexity is admitted only through triggers.** Every deferred capability in the constitution carries an activation trigger; §8 is the consolidated registry. Between triggers, the answer to "shouldn't we add…" is a lookup, not a debate.
5. **Every phase pays its own testing bill.** The suites of 13_TESTING arrive *with* the components they guard, never after. Untested phases don't exit.
6. **The codebase stays understandable through registries, not memory.** At 300k lines, no one holds the system in their head. They hold the *constitution* in their head and trust the registries (operations, agents, plugins, ADRs, CLAIMS.md) to be the truthful map. Keeping those registries truthful is a standing objective of every phase.

**Build-resolution sequencing (which code to write in what order) lives in `18_IMPLEMENTATION_MASTER_PLAN.md`, not here.**

## 2. Phase 1 — The Spine (v0.1)

*The deterministic secretary. Almost no AI. That is the point.*

**Objectives.** A KANG that runs every day and can be trusted with deadlines: kernel skeleton (event bus + persistent log, scheduler with catch-up, permission engine, audit), store layer (kang.db with the full sync quartet from day one), the deterministic Planner path, tasks/projects/deadlines/competitions (tracking only), the API layer + registry + minimal dashboard (four zones, palette-navigate, quick capture), chat with basic context, model router with one provider + fallback-to-deterministic.

**Required infrastructure.** Migration harness, backup snapshots + integrity checks, structured logging + correlation ids, CI tiers (commit + merge), architectural lints active from the *first* commit — lints adopted late are lints fighting history.

**Dependencies.** None — this is the root.

**Architectural milestones.** First event replayed after a kill; first catch-up after simulated downtime; first `kang explain` reconstruction; first restore drill passes; import-linter green on a real codebase.

**Success criteria (exit).** Used every morning for **two consecutive weeks** (PRD §20); zero missed tracked deadlines in that window; capture < 5 s measured; plan renders with network and models disabled; Kang answers "what can KANG touch?" from the permission screen.

**Risks.** The seduction of skipping kernel discipline "because it's just v0.1" — the sync quartet, audit, and lints are precisely the things that cannot be retrofitted (D009, §1.3 above). Mitigation: they are in the Phase-1 definition of done, not the backlog.

**Intentionally postponed.** All cognitive agents beyond basic chat; semantic memory; Obsidian writes; every integration except calendar-read stub.

**Debt avoided.** No ORM, no framework gravity, no "temporary" direct DB access from the UI, no unversioned API operations — the expensive habits are cheapest to never start.

---

## 3. Phase 2 — The Memory (v0.2)

*The trust store, built to the paranoid standard.*

**Objectives.** The full 06_MEMORY machine: write gate + approval queue, lifecycle, provenance, semantic layer (embeddings + FTS + hybrid scoring), Context Assembler with manifests, memory browser UI, Obsidian read + indexing + capture-inbox writes, calendar integration proper, evening review, product states driving notifications.

**Required infrastructure.** sqlite-vec + embedding versioning (dual-index protocol tested before first real embedding); the synthetic corpus generator (13_TESTING's substrate — built *now*, at the start of the phase, because every later suite stands on it); nightly CI tier.

**Dependencies.** Phase 1 kernel (gate rides permissions + audit; assembler rides the store layer).

**Architectural milestones.** First AI-proposed memory travels proposal → queue → approval → retrieval → citation, end to end; first byte-identical manifest determinism proof; first "what do I know about X?" answer with citations; memory integrity suite (13_TESTING §2.8) green on the corpus.

**Success criteria.** Kang stops double-checking KANG's recall (the trust test, PRD §10.5); vault remains fully usable without KANG (open-format proof); approval queue median latency < 7 days in real use.

**Risks.** Retrieval quality disappoints early (small real corpus) → temptation to loosen the gate for volume. **Refuse:** quality compounds, volume doesn't (P4). Also: embedding-model churn mid-phase — the versioning protocol exists precisely for this; use it rather than freezing on a mediocre model.

**Postponed.** Consolidation intelligence beyond the janitor + dedup (pattern extraction needs data that doesn't exist yet — Phase 5's food); link suggestions.

**Debt avoided.** No second store for vectors; no LLM-managed memory shortcut; no gate bypass "for bootstrapping" (seeding memory happens through Kang-principal explicit saves — the legitimate fast path that already exists).

---

## 4. Phase 3 — The Specialists (v0.3)

*Intelligence arrives — into an envelope that was already waiting for it.*

**Objectives.** The cognitive roster on the shared runtime: Competition Strategist + Scout, Researcher, Tutor, Critic, vault organizer; pipelines (`competition_intake`, `competition_prep`, `deep_research`, `weekly_close`); recipes per agent; spaced repetition; GitHub read integration; literature notes; weekly review with the memory steward's weekly pass.

**Required infrastructure.** Multi-provider routing + budgets + the emergency reserve (AG-008) — money controls arrive *with* the first components that can spend meaningfully; injection red-team suite joins weekly CI (Tier-0-input agents now exist); golden shape tests for briefs/critiques/plans.

**Dependencies.** Phase 2 memory (recipes are meaningless without the assembler; the Critic is meaningless without retrospectives to cite).

**Architectural milestones.** First pipeline with a Critic step visibly rejecting a draft; first quarantine from a denial spike (deliberately provoked in staging — prove the tripwire before trusting it); first month under budget with the ledger reconciling to the cent.

**Success criteria.** One competition run end-to-end through the lifecycle (W4) with zero missed deadlines; discovery surfaces ≥ 1 genuinely new relevant opportunity/month; Kang voluntarily routes work through the Critic (the honest-value test — if he avoids it, it's noise, fix it).

**Risks.** Agent sprawl — every idea wants its own agent. Discipline: specialists are configurations first (D011); a new agent needs a mandate no existing agent's recipe can absorb. Cost surprise — mitigated by the reserve rule and the 80/95% ladders being *tested* before the phase exits.

**Postponed.** Judge simulation (needs a real competition's material to be worth building against); email; Notion.

**Debt avoided.** No per-agent bespoke code where config suffices; no free agent-to-agent chatter "just to experiment" (AG-002 has no experimental exemption).

---

## 5. Phase 4 — The Platform (v0.4)

*The core stops growing. Everything new becomes a plugin.*

**Objectives.** Plugin system Phase 1 complete (08_PLUGIN entirely: lifecycle, SDK, conformance suite, install flow); permission manager UI; the first 2–3 real plugins *extracted from ideas that were queued during Phases 2–3* (the honest way to validate an SDK: build the things you actually wanted); relevance filtering v2; link suggestions; judge simulation; Notion read.

**Required infrastructure.** SDK versioning discipline goes live (PL-004 — from here, SDK changes carry deprecation duties); zero-hard-dependency release gate joins the gate list.

**Dependencies.** Phase 3 (the SDK exposes agents/pipelines/recipes — they must be stable enough to freeze an interface over).

**Architectural milestones.** A capability ships as a plugin that would previously have been a core PR — and the core diff is zero lines; first plugin quarantine + recovery; first upgrade with a scope diff re-consent.

**Success criteria.** PRD §10.16: new integration without touching core; every permission visible in one place; the plugin conformance suite catches a deliberately-introduced SDK break before humans do.

**Risks.** The SDK freezes the wrong abstractions (most likely place in the whole roadmap for a costly mistake). Mitigation: the SDK's first consumers are Kang's own real plugins built *in this phase* — interface pain surfaces while the interface is still cheap to change, before v0.4 tags and PL-004 duties begin.

**Postponed.** Sidecar transport (trigger-gated); credentialed integrations; any thought of distribution.

**Debt avoided.** No filter/override hooks under pressure ("just one hook" is how PL-008 dies); no plugin special cases in the kernel.

---

## 6. Phase 5 — The Expansion (v0.5 → v1.0)

*Multi-surface, multi-model, multi-device — on seams built in Phase 1.*

**Objectives** (each its own release, sequenced by trigger-readiness, not calendar): **Sync** (16_SYNC: the change-log finally earns its keep; mobile companion read+capture follows it); **local models** (the `private`/`routine` classes migrate local as quality permits — config drift, measured by the routing benchmarks); **voice** (a palette-register client of the same API); **email + Chrome** integrations (read/draft under the pairing constraints); **consolidation intelligence** (pattern extraction now has 1–2 years of episodes to mine — proposals only, gate eternal); Workflow automation (composing existing primitives, D014's promise).

**Required infrastructure.** 16_SYNC document *first* (the one remaining constitutional document, written when its phase arrives — with real single-device experience informing it); sync convergence suites built on the replay harness; second-device audit witnessing (SEC-013's reservation).

**Dependencies.** Everything. That is why it is Phase 5.

**Success criteria.** The Vision Year-3 tests (00_VISION §8): patterns cited in critiques; one outcome traceable to KANG's work; learning measurably faster. A week on two devices without a silent conflict.

**Risks.** Sync is the highest-risk subsystem in the decade (D009's warning). It gets the full ceremony: its own constitutional doc, its own suites, a long beta against a *copy* of real data before touching truth.

**Postponed.** Vision/wearables/robotics — Ten-Year-Dream items awaiting both need and a trigger.

---

## 7. Phase 6 — The Long Decade (v1.0 → 2036)

*Maintenance is the product now. Growth is curation.*

**Objectives.** The learned reranker (year-2+ retrieval logs as training data, 06_MEMORY Part XV); prompt/model generational upgrades as reviewed migrations; the debt register and risk table as standing agenda; ADR index as institutional memory; periodic constitution review (a *deliberate* ritual — the documents may change, but only awake).

**How 300k lines stays understandable — the actual mechanism, stated once:**

1. **The constitution fits in an evening.** The constitutional set (see INDEX) answers why/what/how-decided. Anyone (Future Kang, an AI assistant, a hypothetical contributor) reads docs, not code, first — and the docs are true because drift is a CI failure (CLAIMS.md) and a review gate (in-PR doc updates).
2. **The registries are the map:** operations, agents, pipelines, plugins, grants, jobs, ADRs — machine-readable, exhaustively enumerating what the system can do. Understanding scales because *enumeration* scales where memorization doesn't.
3. **Boundaries make locality:** dependency direction + ports mean any question lives in one layer; design-for-deletion means any feature is a bounded file list. 300k lines is fine when every question touches 3k of them.
4. **The kernel stays small forever:** growth goes to adapters, agents-as-config, and plugins — the parts that are individually disposable. The trusted core that must be *understood deeply* stays within one person's grasp by constitutional force (AR1), not by hope.

**Success criteria.** The Vision Year-5 tests: a new contributor (or Future Kang after a year away) productive from the docs alone; memory accurate across years; Kang more capable because of the building. The Ten-Year Dream checklist (Vision §7) consulted annually as the compass.

---

## 8. The RESERVED Registry (consolidated activation triggers)

The single lookup table this roadmap promised. Sources cited; between triggers, these are settled.

| Reserved capability | Trigger | Source |
|---|---|---|
| Sidecar process extraction | Component with conflicting runtime needs (GPU local-model host likeliest first) | D001 |
| Sidecar plugin transport / isolation | First non-Kang plugin OR first non-blessed dependency need | PL-001, PL-005 |
| Vector DB server | sqlite-vec measurably failing at Kang-scale | 04_ARCH §19 |
| Graph database | Queries provably exceeding recursive-CTE ergonomics | D008 |
| CRDT fields | Real multi-writer pain after sync v1 | D009, 07_DB Part 10 |
| Sync itself (16_SYNC) | Phase 5 entry; single-device product proven | D009 |
| Mobile companion | 16_SYNC shipped | 09_UI §16 |
| Voice surface | Voice ADR, Phase 5 | 09_UI §18 |
| Local-model migration per task class | Routing benchmarks showing parity per class | D010 |
| Credentialed plugin integrations (`credential:{name}`) | First credentialed integration | 08_PLUGIN §9 |
| Integration-adapter extension point | First real need + ADR | 08_PLUGIN §6 |
| Inter-plugin events/deps | ADR with real cases | 08_PLUGIN §7 |
| Plugin custom rendering | Phase-2 sandbox ADR | 09_UI §8 |
| User-defined themes | Token schema stability post-v1 | UI-003 |
| Focus mode / custom dashboard layouts | Post-v0.2 demand / v0.4+ | 09_UI §18 |
| External credential managers / hardware keys | Real need | 10_SEC §7 |
| External audit anchoring | Sync era (second-device witness) | SEC-013 |
| Encrypted vault-at-rest beyond BitLocker | Kang requests, eyes open, Obsidian-usability preserved | 10_SEC §13 |
| Learned retrieval reranker | Year 2+, retrieval logs as dataset | 06_MEMORY XV |
| Model-quality eval harness | First prompt-change dispute | 13_TESTING §7 |
| Relaxing the AI-proposal gate for a narrow class | ADR, after years of near-zero rejection data | M-003 |
| CPU/memory plugin quotas | Sidecar transport exists | PL-009 |
| Shell tool / engineering-agent executor | Concrete feature + sandboxed-executor ADR | 05_AGENTS §9 |
| Judge simulation | First real competition material (Phase 4) | this doc §5 |
| DuckDB analytics layer | Real analytical need over exports | 04_ARCH D004 |
| Turso/LiteFS reconsideration | Sync design review, v0.5 | D009 |
| Multi-user anything | **Vision-level amendment first** | Vision, PRD §8 |
| Remote execution | **Deliberately unreserved** — Vision amendment before any seam is built | 10_SEC §13 |
| Auto-updater | Never, probably — deliberate updates are a feature | D016 |
| Event bus socket transport | First sidecar process | 15_EVENT_BUS §15.1 |
| Event-sync hazard (cross-device event ordering) | 16_SYNC design | 15_EVENT_BUS §17 |
| Time-travel replay (user-facing "system as of date X") | Real need post-sync | 15_EVENT_BUS §9 |
| Cursor tombstoning for permanently-removed subscribers | First agent definition deletion or plugin uninstall | 15_EVENT_BUS §18 |
| WhatsApp ingestion connector | Kang requests it after manual gig-entry proves burdensome at nightly review | docs/guides/user-profile-intake-2026-07.md D14 |
| Product-state-aware notification ladder (M5 assumes state == Idle) | M6's product-state machine exists | 09_UI §9 / FR-074; `RESERVED(M6 product-state machine)` in `domain/notifications/notification_service.py` |
| Definition of "unchanged item" for the 24h no-re-notification rule (M5 uses same-entity-refs + same-priority) | Real notification volume to design against, then an ADR | 09_UI §9; `RESERVED(...)` on `is_duplicate` in `domain/notifications/notification_service.py` |
| Definition of "deadline in danger **today**" — the `critical` escalation threshold. M5 surfaces every approaching deadline at `attention` and does not let deadline urgency reorder plan quests | Kang's ruling (a product decision, not a code one); needed when the Planner or notifier must rank by urgency | 05_AGENTS §13's `critical` row names the concept but never defines it; noted in `domain/planner/plan_service.py::build_plan` and the notifier's `DEADLINE_APPROACHING_PRIORITY` |

---

## 9. The Version-Boundary Ritual

At every version tag, in order (one sitting, written outputs):

1. Release gates verified (13_TESTING §4).
2. Risk table walked (PRD §18) — any risk trending real pauses the next phase's features.
3. Debt register decided (11_CODING §26) — pay, or re-accept in writing.
4. RESERVED registry scanned — any triggers fired? (Fired triggers become next-phase objectives, by ADR.)
5. This roadmap revised: reality vs. plan, exit criteria honesty, next phase re-scoped *smaller* if the last one slipped (slippage means the estimate was wrong, not the calendar).
6. The Vision tests glanced at (§8 of 00_VISION) — is the product still pointed at the north star, and is building it still serving the life it's for (R10)?

---

## Constitutional summary

The roadmap's job is to make the next right thing obvious and the next wrong thing expensive: heartbeat before intelligence, memory before specialists, specialists before platform, platform before expansion, and curation forever after. Complexity enters through triggers, debt through registers, change through ADRs — and at every boundary, the same question that started everything: *does this free Kang to create things that matter?*

*When the plan and reality disagree, reality wins — revise the plan, in writing, awake.*
