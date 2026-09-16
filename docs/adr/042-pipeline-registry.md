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

Deferred to the implementation slice this ADR authorizes. Expected proof, named now: a pipeline step naming an agent id absent from the registry refuses the whole load; a pipeline whose own `id` doesn't match its filename refuses; an empty `steps` list refuses; all four real shipped pipelines load cleanly against the real, full 15-agent registry (ADR-040 D4); `mode` is captured but never validated, provably (a nonsense `mode` string still loads successfully). Zero network, zero model calls (13_TESTING §1) — pure data, same as ADR-040.
