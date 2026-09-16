# ADR-042 — The pipeline registry: named, ordered agent-step sequences

**Status:** accepted (2026-09-16)
**Date:** 2026-09-16
**Supersedes:** none
**Affected documents:** none — AG-002/05_AGENTS §4 already describe the destination; this ADR is the schema and loader
**Cites:** AG-002 (`docs/05_AGENTS.md:133-141`, "Multi-agent behavior exists only as pipelines: named, versioned, bounded DAGs of agent steps, defined in the registry and executed by the Orchestrator"), 05_AGENTS §10 (`:255-257`, pipeline timeout budgeting and partial-failure semantics — named here as NOT this ADR's job), 17_PROJECT_STRUCTURE (`docs/17_PROJECT_STRUCTURE.md:104`, `agents/pipelines/` already the named destination), Appendix A's own pipeline list (`docs/05_AGENTS.md:435`, the four real pipelines this ADR transcribes), ADR-040 (the agent registry this cross-validates against)
**Related:** [[040-agent-registry.md]], [[041-mechanical-agent-executor.md]]

---

## Context

`AgentDefinition.pipelines` (ADR-040) already lets a definition NAME which pipelines it's a step of — `planner.toml` already says `pipelines = ["weekly_close"]`. But `weekly_close` itself is not a real, loadable thing: no `PipelineDefinition` schema exists, `agents/pipelines/` (already named in `17_PROJECT_STRUCTURE.md:104`) is empty, and nothing cross-checks that a definition's own pipeline membership claim corresponds to a pipeline that actually lists it as a step.

**Scope-narrowing finding, made before any code:** AG-002 calls pipelines "bounded DAGs," but 05_AGENTS §10 immediately assigns pipelines real EXECUTION semantics no executor here has: timeout budgeting ("pipelines sum steps + 20% overhead cap"), partial-failure forward-propagation ("a failed step fails the pipeline forward... completed steps' proposals remain... MUST NOT auto-restart from the top"), and a shared pipeline correlation id with per-step correlation ids. **None of that is this ADR's job.** Exactly like the agent registry (ADR-040) shipped inert data before ADR-041 built a (mechanical-only) executor, this ADR ships pipeline *data* — nothing executes a pipeline yet, cognitive or mechanical (the mechanical executor, ADR-041, runs one agent's one tool call; it has no pipeline concept at all).

**A second scope-narrowing finding:** all four of Appendix A's own real pipelines (`docs/05_AGENTS.md:435`) are simple, linear sequences — `scout → strategist(evaluate) → notify`, never branching. Building a genuine DAG schema (parallel branches, join points) for zero real pipelines that need one would be exactly the "pre-build against a hypothetical" this project has repeatedly declined (ADR-036 D1, ADR-038 D4, ADR-039 D4). **Decided here: an ordered, linear sequence of steps** — ADR-002's own "bounded DAGs" language stays accurate (a line is a degenerate DAG) without this ADR inventing branching syntax nothing exercises.

**A third finding:** Appendix A's pipeline list annotates some steps with a parenthetical — `strategist(evaluate)`, `strategist(ideas)`, `strategist(revise)`, `planner(review)`. This is not a second agent or a new mechanism — it is which facet of that agent's own single mandate this step exercises (the Strategist's one mandate already covers evaluation, ideation, and revision — Appendix A's own row). Modeled as an optional `mode` string per step, structural only (no validation against anything — a future executor's own concern, the same restraint ADR-040 D2 already used for `tools`).

## Decision

### D1 — Layout: `agents/pipelines/{id}.toml`

One file per pipeline, flat (matching `agents/definitions/`'s own precedent, no per-pipeline subfolder — pipelines have no prompt files of their own, only steps naming agents that have theirs).

### D2 — The `PipelineDefinition` schema

```
PipelineDefinition:
  id:    str
  steps: tuple[PipelineStep, ...]   # ORDERED, linear — D1's own scope cut; non-empty

PipelineStep:
  agent_id: str          # MUST exist in the AgentRegistry (cross-validated, D3)
  mode:     str | None   # which facet of that agent's mandate — structural only, unvalidated
```

### D3 — Validation: structural, plus one real cross-check against the agent registry

- `id` non-empty, matches its own filename (mirrors ADR-040 D3's folder/id rule, adapted to `agents/pipelines/`'s flat-file layout: `{id}.toml`'s own `id` field must equal the filename stem).
- `steps` non-empty (a zero-step pipeline is not a pipeline).
- **Every step's `agent_id` must resolve in the `AgentRegistry`** (ADR-040) — the one genuine cross-registry check this ADR adds, catching a typo'd or renamed agent id at *pipeline* load time rather than only when some future executor tries to run the step and fails. This is why the pipeline loader takes an already-built `AgentRegistry` as an argument, not just a bare directory path.
- Fails closed, same posture as every other registry in this codebase (ADR-040 D3, `permissions.toml`/`providers.toml`): one malformed pipeline refuses the whole pipeline load.
- **NOT validated here:** whether a step's own `mode` corresponds to anything the named agent actually implements (D2's own restraint); whether a definition's own `AgentDefinition.pipelines` claim is reciprocally listed as a step in that pipeline (a real, useful bidirectional check — but the *first* real pipeline data this ADR ships is what would prove whether that check is even worth its own complexity; named as a candidate follow-up, not built blind).

### D4 — Ships all four of Appendix A's own real pipelines

`competition_intake` (`competition_scout → competition_strategist(evaluate) → notifier`), `competition_prep` (`competition_strategist(ideas) → critic → competition_strategist(revise)`), `deep_research` (`researcher → critic → researcher(revise)`), `weekly_close` (`planner(review) → memory_steward(weekly) → notifier`) — the exact four `docs/05_AGENTS.md:435` already names, every referenced agent already registered (ADR-040 D4's now-completed 15-agent catalog).

## Consequences

- **AG-002 goes from prose to loadable, cross-validated data** — a typo'd agent id in a pipeline step is now a load-time refusal, not a future executor's silent failure.
- **Two things stay explicitly unbuilt, both named:** pipeline *execution* (timeout budgeting, partial-failure forward-propagation, resume-from-failed-step — 05_AGENTS §10's own list) and DAG branching (no real pipeline needs it yet).
- **`AgentDefinition.pipelines`'s own membership claims remain unvalidated against real pipeline step lists this slice** — named as a candidate follow-up, not silently assumed correct.

## Verification

**Implemented and verified (2026-09-16), same day as acceptance.** What landed, mirroring ADR-040's own parse-in-adapters/cross-check-in-kernel split exactly: `domain/ports/pipeline_definition.py` (`PipelineDefinition`, `PipelineStep`, `PipelineDefinitionInvalid`); `adapters/config/pipelines_loader.py` (`parse_pipeline_definition`, `discover_pipeline_definitions` — structural parse only: `id` non-empty and matching its filename stem, `steps` non-empty, each step's `agent_id` non-empty and `mode` a string-or-absent, never validated further); `kernel/orchestrator/pipeline_registry.py` (`PipelineRegistry`, `build_checked_pipeline_registry` — the one genuine cross-check, every step's `agent_id` resolved against an already-built `AgentRegistry`); `src/kang/agents/pipelines/{competition_intake,competition_prep,deep_research,weekly_close}.toml` (all four of Appendix A's own real pipelines, D4).

**A gap found in ADR-040 while implementing this, fixed at the source, not routed around:** building the real pipeline data and reading each agent's own `pipelines` claim against it (an eyeball check, not the reciprocal-validation code D3 deliberately left unbuilt) surfaced that `notifier.toml` and `memory_steward.toml` both shipped `pipelines = []` — wrong: `notifier` closes both `competition_intake` and `weekly_close`; `memory_steward` performs `weekly_close`'s own weekly-consolidation step. This was undiscoverable at ADR-040 D4's own implementation time — no real pipeline data existed yet to check a `pipelines` claim against. Corrected in `notifier.toml`/`memory_steward.toml` directly, each with an inline dated comment, and in ADR-040's own Verification section with a dated correction note (this file only records the fact; ADR-040 is the one that owns the correction, per this handbook's own rule: fix accepted-ADR gaps at the source, document them in the ADR that owns them). Every other shipped agent's `pipelines` field (`competition_scout`, `competition_strategist`, `critic`, `planner`, `researcher`) already matched its real pipeline memberships exactly — no other gap found.

Proven, not assumed: 18 new tests. `test_pipelines_loader.py` (14): a minimal pipeline parses with `mode` both present and absent; step order is preserved, not resorted; malformed TOML; missing/empty `id`; `id`/filename-stem mismatch; missing `steps` key; empty `steps` list; a step missing or with an empty `agent_id`; a non-string `mode`; a nonsense `mode` string still loading (D3's own restraint, provably); `discover`'s own multi-file walk; all four real shipped pipelines loading with their exact expected step sequences and modes. `test_pipeline_registry.py` (4): a clean pipeline over known agents builds a registry indexed by id; a step naming an unregistered agent id refuses the whole load; one bad pipeline among several refuses the WHOLE registry, not just itself; the four real shipped pipelines cross-validate cleanly against the real, full 15-agent registry (ADR-040 D4). One existing assertion added to `test_agent_definitions_loader.py`'s shipped-catalog test, proving the `notifier`/`memory_steward` correction live against the real files.

Live-verified beyond pytest, as a real subprocess against the real shipped directories (no `%KANG_HOME%` involved — like ADR-040's own `AgentRegistry`, `PipelineRegistry` is not yet wired into `composition.py`/`build_core()`, so there is nothing home-scoped to stand up for this data-only slice): all four real pipelines load and cross-validate against the real 15-agent registry, printed step-by-step; the `notifier`/`memory_steward` correction confirmed live; a step naming an unregistered agent refused the whole load; an `id`/filename mismatch refused; an empty `steps` list refused; a nonsense `mode` string loaded successfully, unvalidated. Full test suite: **1034 passed** (up from 1017 — 18 new, no silent coverage loss). Full lint suite: 0 hard violations (one line-length fix in a test file only), `ruff check`/`lint-imports` (8/8 contracts kept, no new contract needed — pipeline TOML data has no Python package to gate)/banned-patterns/tree-hygiene all clean. Zero network, zero model calls anywhere in the suite (13_TESTING §1) — pure data, same as ADR-040.
