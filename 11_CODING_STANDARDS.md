# KANG — Coding Standards

**Document:** 11_CODING_STANDARDS.md
**Version:** 0.1
**Author:** Kang, with Claude (Founding Architect)
**Status:** Normative — binding on every line of code, human- or AI-written; changes require an ADR
**Last updated:** 2026-07-11
**Upstream (binding):** `01_PRINCIPLES.md` (E1–E10), `04_ARCHITECTURE.md` (D001–D016), `05_AGENTS.md`, `06_MEMORY.md`, `07_DATABASE.md`, `08_PLUGIN_SYSTEM.md`, `09_UI_DESIGN.md`, `10_SECURITY.md`, `12_API.md`
**Purpose:** prevent architectural entropy. Every rule here exists because its absence produces a specific, known form of rot. Rules are enforced by tooling wherever tooling can enforce them; taste is reserved for what tooling cannot see.

> RFC-2119 throughout. Languages are fixed by D002: **Python 3.12+** (core), **TypeScript + React** (UI). This document assumes them.

---

## 1. Repository Organization

One repository. Monorepo, because the system is a modular monolith (D001) and its parts version together.

```
kang/
├── docs/                    # the constitution (00–12) + adr/ + guides/
│   └── adr/NNN-title.md
├── src/kang/                # the core (Python) — layout per D005, frozen:
│   ├── kernel/              #   bus, scheduler, permissions, audit, router, plugin host, orchestrator
│   ├── domain/              #   entities + capability services
│   │   └── ports/           #   ALL interfaces (the dependency firewall)
│   ├── agents/              #   definitions (toml + prompts) + runtime
│   ├── adapters/            #   sqlite/, obsidian/, anthropic/, ollama/, github/, gcal/, web/
│   ├── api/                 #   operation registry, sessions, dispatch (thin — 12_API §2)
│   └── plugins_sdk/         #   the versioned public SDK
├── ui/                      # TypeScript/React client (pure client, UI-P1)
├── cli/                     # thin client of the same API
├── migrations/              # NNNN_description.sql (07_DATABASE Part 13)
├── tests/                   # mirrors src/ structure + suites/ (conformance, synthetic-corpus, injection)
├── config/                  # example/default TOML (real config lives in %KANG_HOME%)
└── tools/                   # dev scripts, linters, corpus generator
```

- Top-level directories are constitutional: adding one requires an ADR; nothing lives at root that isn't listed.
- `src/kang/` subpackage names map 1:1 to the D005 layer diagram. A file that doesn't obviously belong to one layer is a design smell, not a filing problem.

## 2. Dependency Direction (the one rule that outranks all others)

- **Imports point inward only:** `adapters → domain/ports`, `api → kernel/domain`, `kernel → domain/ports`, `domain → nothing but domain + stdlib`. `domain/` MUST NOT import kernel, adapters, api, or any third-party I/O library. Agents import domain services + SDK-visible surfaces only.
- Enforced by an **import-linter contract in CI** (not convention). A dependency-direction violation is a red build, no exceptions, no `# noqa`.
- Cross-layer communication happens through ports (interfaces in `domain/ports/`) and events — never through reach-around imports, globals, or "just this once" direct calls (E4).
- The UI depends on the generated API client only (12_API §16 registry). UI code importing anything about the database, memory internals, or agent internals cannot happen by construction (separate language) — and UI code *reimplementing* them is a review rejection (UI-P1).

## 3. Naming

- Python: `snake_case` functions/modules, `PascalCase` classes, `UPPER_SNAKE` constants; TypeScript: idiomatic (`camelCase`/`PascalCase`).
- Names say **what, in domain language** — the vocabulary of the constitution: `write_gate`, `context_assembler`, `held_action`, `idempotency_key`. Inventing a second name for a concept the docs already named is forbidden (one concept, one name, everywhere: docs, code, DB, API, UI).
- Ports are named for the capability (`MemoryStore`, `VaultPort`, `ModelProvider`); adapters for tech+port (`SqliteMemoryStore`, `AnthropicModelProvider`).
- No abbreviations except the blessed set: `id`, `db`, `api`, `ui`, `cfg` is NOT blessed. No `utils`, `helpers`, `common`, `misc` modules — a name that says nothing hides anything (they are where boundaries go to die).
- Booleans read as predicates (`is_`, `has_`, `requires_`); functions are verbs; queries `get_/list_/search_`, commands `create_/complete_/propose_` (mirroring API-001's split *inside* the code too).

## 4. Size Limits (enforced by lint)

| Unit | Soft limit | Hard limit (CI fail) |
|---|---|---|
| Function | 40 lines | 80 |
| File/module | 400 lines | 800 |
| Class | 200 lines | 400 |
| Function parameters | 4 | 6 (then it's a dataclass) |
| Cyclomatic complexity | 8 | 12 |
| Nesting depth | 3 | 4 |

Hard-limit exceptions require an inline justification comment naming the ADR or reason, and are reported in CI output (visible debt, §27). These numbers exist because unreadable units are where bugs hide from one part-time maintainer (R7).

## 5. Module Boundaries

- One responsibility per module (E7); a module's public surface is its `__all__` — everything else is private and MUST NOT be imported across packages (lint-enforced).
- Ports before implementations (E3): a new capability lands as interface + fake + tests, then the real adapter.
- Design for deletion (AR8): every feature's code lists its files in the feature's doc header; `git rm` of that list plus its registry entries MUST leave a green build. Reviewed at feature completion.

## 6. Logging

- Structured JSON lines only; every log call carries `correlation_id` when inside an invocation (D015). `print()` is banned in `src/` (lint).
- Levels: `debug` (dev diagnosis) / `info` (state transitions worth one line) / `warning` (degradation taken) / `error` (failure surfaced). Nothing logs at `info` inside loops.
- **Log ≠ audit:** audit entries go through the audit service exclusively; writing "audit-ish" lines to the debug log is a defect (S5 separation).
- Secrets: the scrubber runs on all sinks, but code MUST NOT rely on it — constructing a log message containing a credential is the defect, the scrubber catching it is the incident (SEC-011).

## 7. Testing Expectations

- Every port has an in-memory fake; domain logic is tested against fakes, adapters against real tech (SQLite in-temp, recorded HTTP), boundaries against the conformance suites (12_API §16, 08_PLUGIN §10).
- Coverage: line coverage is a smell detector, not a goal; the binding requirements are the **normative suites** already specified — 07_DATABASE Part 16, 05_AGENTS §16, plugin conformance, API conformance, injection red-team, performance budgets on the synthetic corpus. These run in CI at their specified cadences; a red suite blocks release, full stop.
- Every bug fix lands with the test that would have caught it. No exceptions — this is how ten years of fixes stay fixed.
- Tests are deterministic: no sleeps-as-synchronization, no real network, no wall-clock dependence (injectable clock, §14). A flaky test is quarantined within 24h and fixed or deleted within a week — a test nobody trusts is worse than none.

## 8. Documentation & Comments

- Every module: a header docstring stating purpose, layer, and its constitutional home (`Implements 06_MEMORY §4 write gate`). Every public function: docstring with behavior, failure modes, and idempotency class where applicable.
- Comments explain **why**, never what (the code says what). A comment restating the line below it is deleted in review. `TODO` is banned; the allowed markers are `DEBT(#issue)` (§27) and `RESERVED(trigger)` (constitutional reservations).
- Docs-and-code drift is a bug with an owner: the PR that changes behavior updates the doc in the same PR (P10) — "docs later" does not merge.

## 9. Error Handling

- Typed errors, one hierarchy per layer, mapped to the single API error model (API-006) at the boundary. Raising strings, catching bare `Exception` outside supervision points, and swallowing exceptions are lint/review rejections.
- **Fail visibly (DB-P7):** no silent fallbacks, no default-on-error values that masquerade as data, no retry loops hiding a broken invariant. Degradation is a *declared path* (05_AGENTS AGP-8) with a marker in the output, never an accident of exception flow.
- Every `except` block either: re-raises enriched, translates to a typed error, or is a documented supervision point (orchestrator, plugin host, job runner — the closed list).

## 10. Configuration

- All config through the typed config loader (TOML → validated dataclasses at startup; fail-fast on invalid). Reading environment variables or files ad hoc anywhere else is banned (lint: `os.environ` allowed only in the config module and test fixtures).
- Constants that are really policy (thresholds, weights, retention) live in config files per 06_MEMORY App. A / 07_DATABASE Part 18 — a magic number in code that the docs list as tunable is a defect.
- Config keys appear in exactly one of: files or `setting` table (07_DATABASE §3.4 disjointness, linted).

## 11. Dependency Injection

- Constructor injection of ports only. No service locators, no global singletons, no import-time side effects (lint: module import MUST be side-effect-free — enforced by an import-under-test harness).
- The composition root (one module, `kang/app.py`) is the only place concrete adapters meet interfaces. If wiring appears anywhere else, the architecture is leaking.
- No DI frameworks (E10): the composition root is plain constructor calls, readable top to bottom.

## 12. Concurrency

- `asyncio` single-loop in the core; **no threads except** inside adapters that must wrap blocking libraries (and then: `to_thread`, bounded, documented). No multiprocessing in-core (sidecars are the process story, D001).
- All concurrency passes through the kernel's supervised-task primitives (timeout, cancellation, naming) — bare `create_task` outside the kernel is lint-banned. Orphan tasks are how "why is KANG doing that?" becomes unanswerable (SEC-005's spirit at micro-scale).
- Shared mutable state between tasks MUST NOT exist outside the store layer; coordination is by queue/event, not by lock (locks in domain code are a design-review flag).

## 13. Transactions & Database Access

- All DB access via the store layer (repositories implementing ports); SQL lives in the store layer only, per DB-002 (SQL-first, no ORM). A query string outside `adapters/sqlite/` is a red build (lint scans for SQL patterns).
- Transaction rules are 07_DATABASE Part 6 verbatim: short (< 50 ms budget), `BEGIN IMMEDIATE`, optimistic revision checks, computation outside transactions. The store layer exposes *units of work*, not connections — no component can hold a transaction open across an await into foreign code.
- `SELECT *` is banned in code (forward-compat, 07_DATABASE Part 13).

## 14. Determinism & Time

- The clock is injected (`Clock` port). `datetime.now()` outside the clock adapter is lint-banned. Randomness likewise (`Rng` port) — needed for jitter, seeded in tests.
- Same inputs ⇒ same outputs everywhere models aren't involved; where models are involved, everything *around* the call is deterministic (manifest, validation, budgets), which is what makes model behavior diagnosable (AG-009).

## 15. Performance Expectations

- The budgets are already law (07_DATABASE Part 14, 05_AGENTS caps, NFR-001/011); code-level rules: no N+1 store calls (batch interfaces exist — use them); no unbounded reads (every list is limited/paginated internally too); no synchronous I/O on the event loop; hot paths (P0 queries, capture, gate) carry benchmark tests pinned to budgets.
- Optimization beyond budgets requires a measured justification in the PR — cleverness without a number is complexity without a cause (E1, E8).

## 16. Plugin & Agent Development Standards

- Plugins: conform to 08_PLUGIN entirely; additionally — plugin code follows this document's rules (limits, naming, errors) as a `kang plugin lint` check; a plugin without tests does not get past `kang plugin test` in Kang's own workflow, even though the system can't force it (honesty: self-discipline, stated).
- Agent definitions: prompts are versioned files beside the definition; prompt changes are PRs with before/after eval notes (a prompt is behavior; behavior changes get reviewed — 05_AGENTS §17); every cognitive agent's degradation path has a test (§16 of 05_AGENTS, release-blocking for the Planner).
- New agents/pipelines/tools land with: definition, grants diff, recipe, tests, and one paragraph in the agent catalog. Missing any ⇒ not done (§25).

## 17. Frontend Standards

- Pure client (UI-P1): state = server state (fetched/streamed) + view state (ephemeral); no client-side persistence beyond view preferences; no derived truth (computing "overdue" client-side when the API provides it is a defect — two computations drift).
- Tokens only (UI-003) — a hex literal in a component is a lint failure; reserved colors reserved.
- Components follow the size limits (§4, adjusted: component file hard limit 400 lines); one component, one responsibility; screens declare domain + depth (UI-001) in a route manifest that the palette and deep-linking are generated from.
- Accessibility rules of 09_UI §15 are lint/CI-checked where tools exist (contrast tokens, focus order tests, reduced-motion).

## 18. API Implementation Rules

- Operations are registered declaratively (schema, scopes, idempotency class) — handlers contain dispatch-to-domain only; an `if` about domain semantics in `api/` is a defect (12_API §2).
- New operations: registry entry + schemas + conformance tests + docs, in one PR. Response-shape changes follow API-005 additive rules — the conformance suite diffs the registry against the last release and fails on removals/mutations without a deprecation record.

## 19–24. Review Checklist, CI, Definition of Done

**Review checklist (every PR; reviewer is Kang or AI-assisted-Kang — the checklist is the reviewer's spine):**
1. Dependency direction clean? (CI proves; reviewer sanity-checks intent)
2. Right layer? Right name (existing vocabulary)? Right size?
3. Failure paths: typed, visible, degradation declared?
4. Idempotency where the contract requires it?
5. Security posture: principal threaded, scopes checked at the right point, no new authority paths, secrets nowhere?
6. Tests: the specified suites touched? Bug-fix test present? Deterministic?
7. Docs updated in-PR? ADR needed (does this change a Decision)? Filed?
8. Deletable? (Feature file list current)
9. Would 2036-Kang understand this in one read?

**CI (blocking, in order of cost):** format (black/ruff, prettier — zero config debates, ever) → lint contracts (imports, sizes, banned patterns, SQL placement, token literals) → unit → adapter/integration → normative suites per cadence (conformance, migration, injection weekly, performance nightly on synthetic corpus) → docs build + link check. Red = no merge. CI config changes are reviewed like code.

**Definition of Done (a feature):** designed (doc/ADR) → implemented within boundaries → tested per suites → documented (module headers + user-facing doc if applicable) → observable (logs/metrics where it acts) → explainable (its actions reconstruct via `explain`) → deletable (file list) → reviewed against the checklist → merged green. Eight gates; "it works" is gate zero of nine.

## 25. Forbidden Practices (lint-enforced where possible; review-fatal always)

Monkey-patching · global mutable state · import-time side effects · `eval`/`exec`/dynamic code loading outside the plugin host (SEC-005) · bare `except:` · silent fallbacks · `print` in src · direct `os.environ`/file config reads · SQL outside the store layer · ORM introduction · threads outside adapter wrappers · unsupervised tasks · wall-clock/randomness outside ports · secrets in code/config/logs/tests · `TODO` · dead code kept "just in case" (delete it; git remembers) · commented-out code · new dependencies without the E10 justification paragraph in the PR · framework adoption without an ADR · copying logic between core and UI · second names for existing concepts · "temporary" anything without a `DEBT(#)` marker and an issue.

## 26. Technical Debt Policy

- Debt is taken **knowingly or not at all** (anti-principle: never sacrifice architecture for speed *silently*). Knowing = a `DEBT(#issue)` marker at the site + an issue stating cost, interest (what it slows/risks), and the payoff trigger.
- The debt register is reviewed at every version boundary (with the risk review, PRD §18); debt older than two versions without action is either paid or explicitly re-accepted with a written reason — debt that nobody re-decides is rot.
- Hard-limit exceptions (§4) and quarantined flaky tests auto-register as debt.

## 27. Deprecation Policy

One policy, three surfaces, already specified — restated as the coder's rule: anything public (SDK per PL-004, API per API-005, config keys, event types) deprecates with: registry/doc marking + runtime warning + ≥ 2 minor versions of dual operation + ADR for removal. Internal code deprecates by deletion (that's what boundaries are for).

## 28. ADR Workflow

- Trigger: any change to a numbered Decision in docs 00–12, any new dependency/framework, any new top-level structure, any authority-model change, anything the review checklist item 7 flags.
- Format: `docs/adr/NNN-title.md` — Context · Options (≥ 2, honestly weighed) · Decision · Consequences (including what becomes harder). Status: proposed → accepted → (superseded-by-NNN). ADRs are immutable once accepted; changes are new ADRs.
- The ADR index is the project's institutional memory (per the Tier-S recommendation): each entry lists affected documents; each affected document links back. Six months from now, the reasoning is worth more than the decision.

---

## Constitutional summary

Code in KANG is boring on purpose: one direction of dependency, one name per concept, one place for SQL, one error shape, one composition root, small units, visible failures, injected time, supervised tasks, and a paper trail from every decision to its reasons. Entropy enters codebases through exceptions; this document's job is to make exceptions expensive, visible, and rare.

*When code and this document disagree, one of them is wrong on purpose — file the ADR.*
