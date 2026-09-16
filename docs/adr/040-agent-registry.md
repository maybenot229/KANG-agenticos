# ADR-040 — The agent registry: definitions as data, loaded and validated (AG-004)

**Status:** accepted (2026-09-14)
**Date:** 2026-09-14
**Supersedes:** none
**Affected documents:** none — 05_AGENTS AG-004/§5, 17_PROJECT_STRUCTURE's `agents/definitions/` row already describe the destination; this ADR is the schema and loader, not a correction
**Cites:** 05_AGENTS AG-004 (`docs/05_AGENTS.md:149`, "Agents exist only as registered definitions... KANG MUST NOT synthesize new agents, modify definitions, or grant scopes at runtime"), AG-005 (`:225`, the tool allowlist), §8 (`:203-217`, the scope/pairing model), Appendix A (`:411-436`, the built-in catalog — the authoritative source this ADR transcribes from, not re-derives), 17_PROJECT_STRUCTURE (`docs/17_PROJECT_STRUCTURE.md:103,458`, `agents/definitions/{name}/` — TOML + prompts, already the named destination), `kernel/permissions/pairing.py` (the existing pairing-lint machinery this ADR reuses, not reimplements), ADR-028 (M7 foundations — this is another of that ADR's sequenced-but-unordered slices, Kang's own choice this round)
**Related:** [[028-m7-foundations.md]]

---

## Context

`agents/__init__.py` and `agents/runtime/__init__.py` are both empty stubs. AG-004 is fully specified in prose — versioned declarative documents, loaded at startup, never synthesized at runtime — but nothing implements the loader, the schema, or a single real definition.

**A scope-narrowing finding, made before any code, not after:** Kang's own framing of this slice ("agent registry + manifest assembly") is one bullet in the docs but two constitutionally different pieces of work. `kernel/context/__init__.py` — the Context Assembler, AG-009's own "manifest construction" — states its own constitutional home as *"06_MEMORY §5 (built at Phase 2 — 18 §4)"*, and `domain/memory/__init__.py` (the write gate, scoring, retrieval this needs) carries the identical Phase-2 marker. Manifest assembly is deterministic *given a memory store snapshot to assemble from* (AG-009) — no such store exists yet; Memory is Phase 2, M7 is Phase 1. Building it now would be exactly IM-003's illegal parallelization ("anything with its gate-dependency still red") and would very likely need reworking once the real recipe/scoring machinery lands. **This ADR is the registry only.** Manifest assembly stays a Phase-2 dependency, named here so it is not silently reattempted before its gate is green.

**Two further gaps found while grounding this, both resolved below rather than deferred, because the registry cannot be validated without deciding them:**

1. **AG-005's tool allowlist and §8's capability scopes are two different fields with two different grammars**, not one list read two ways. §8's scopes already have a parser and a pairing lint (`kernel/permissions/scope.py::parse_scope`, `kernel/permissions/pairing.py::lint_grants`) — reused here verbatim, not reimplemented. AG-005's tools do not: Appendix A's own tool-column entries (`tasks.*`, `web.fetch:{sources}`, `notify≤attention`) are not one consistent grammar (`notify≤attention` isn't `family:qualifier` at all) and AG-005 itself defers exactly this — "Tools are kernel- or plugin-provided implementations behind ports (D005)" is a future executor's job to resolve into real, callable things, not this registry's. **Decided here:** the tool allowlist is validated *structurally* only (non-empty, no duplicates, each entry a non-empty family-shaped string) — deliberately not given a resolved grammar or a resolved meaning yet, the same "don't pre-build against a hypothetical" restraint ADR-036 D1 and ADR-038 D4 already used.
2. **§1.2's "mechanical agent MAY escalate to a cognitive step... a declared capability in its definition"** names a real, distinct third shape Appendix A's own "Kind" column shows as `M→C` (`competition_scout`, `web_monitor`, `memory_steward`) — not a third `kind` value (§1.2's own table names exactly two kinds), but an *optional* structured field on a `mechanical` definition. Modeled here as `escalation: {task_class, prompt_file} | None`.

## Decision

### D1 — Layout: `agents/definitions/{id}/{id}.toml` + `agents/definitions/{id}/prompts/`

Matches `17_PROJECT_STRUCTURE.md`'s own file-tree comment literally ("`definitions/` — one folder per agent: `{name}.toml` + `prompts/`"), not a new convention. A `prompts/` subfolder rather than one bare prompt file: a cognitive agent's prompt is realistically more than one file over time (system prompt, per-mode variants) even though this slice's own real definitions need only one each.

### D2 — The `AgentDefinition` schema (structural, not behavioral — this ADR does not decide how any field is *used*, only what a definition truthfully states)

```
AgentDefinition:
  id:            str                       # matches the folder name, matches Appendix A's id
  kind:          "cognitive" | "mechanical" # §1.2's own two kinds, exactly
  mandate:       str                        # AGP-1: one sentence, the single responsibility
  triggers:      tuple[str, ...]            # e.g. "sched:morning", "kang", "event:competition.found"
  tools:         tuple[str, ...]            # AG-005's allowlist — structural validation only (D1 above)
  scopes:        tuple[str, ...]            # §8's capability scopes — parsed + pairing-linted for real
  timeout_s:     int                        # AGP-3/lifecycle phase timeout (> 0)
  retry:         int                        # invocation-level retry count (>= 0)
  degradation:   str                        # AGP-8: what it produces with no model/network/budget — never empty
  recipe:        str | None                 # Phase-2 concept (06_MEMORY Part XI) — captured, NOT resolved;
                                             #   None is valid and expected for every definition this slice ships
  pipelines:     tuple[str, ...]             # named pipelines this agent is a step of, if any
  prompt_file:   str | None                  # required (and must exist) iff kind == "cognitive"; forbidden iff "mechanical"
  escalation:    EscalationCapability | None # ONLY for kind == "mechanical" (§1.2's M→C shape); forbidden for "cognitive"

EscalationCapability:
  task_class:    str    # the TaskSpec.task_class this escalation may request (ADR-038 D2's own vocabulary — reused, not reinvented)
  prompt_file:   str    # must exist, same rule as a cognitive agent's own prompt_file
```

`tools`/`scopes` are `AgentDefinition`'s own responsibility to carry; whether a given tool string names something the executor can actually call is that future slice's problem, named and left open, not guessed at here.

### D3 — Validation at load: structural + the existing pairing lint reused, not reinvented

- Every required field present and correctly typed; `kind` ∈ `{cognitive, mechanical}`; `timeout_s > 0`; `retry >= 0`; `degradation` non-empty (AGP-8: "'Nothing, silently' is never a valid degradation" — an empty string is exactly that, refused at load, not merely discouraged).
- `tools`: the key MUST be present (AG-005: "no default toolset" — an agent with no declaration at all is a load error, not an implicit empty allowlist); the tuple itself MAY be empty (`critic`'s own catalog row holds no allowed tools at all beyond `notify`) — what's refused is a duplicate entry or an empty-string entry *within* a non-empty tuple, not emptiness itself.
- `scopes`: each entry parsed with the existing `parse_scope`; the existing `lint_grants` pairing rules (`kernel/permissions/pairing.py`) run against the definition's own declared scope set, exactly as they already run against a `permissions.toml` grant set — a bad agent *design* is caught here, before anyone ever adds it to `permissions.toml` for real. This is the one piece of genuine reuse this ADR leans on: no new pairing logic, the same function, a new caller.
- `kind == "cognitive"` ⟺ `prompt_file` is set and the file exists; `escalation` MUST be absent (structurally forbidden, not merely unused).
- `kind == "mechanical"` ⟺ `prompt_file` MUST be absent; `escalation`, if present, must itself validate (`prompt_file` exists, `task_class` ∈ `TaskSpec`'s own `TASK_CLASSES`, ADR-038 D2 — reused, not a second enum invented for the same concept).
- Duplicate `id` across the definitions directory, or a folder name that doesn't match its own `id` field, refuses the whole load (AG-004: the registry is the security perimeter — an inconsistency here is not a warning).
- **Fails closed, same posture as `permissions.toml`/`providers.toml`** (07 F8, ADR-038 D5): any single malformed or invalid definition refuses the ENTIRE registry load, never "skip the bad one and continue" — a partially-loaded agent registry is a silently-smaller security perimeter than the one on disk, which is precisely the failure mode AG-004 exists to prevent.

### D4 — This slice ships three real definitions, not the full catalog

Deliberately narrower than transcribing all 15 of Appendix A's agents in one pass — the same "smallest correct slice" discipline ADR-036 D1/ADR-038 D1/ADR-039 D1 already used, for the same reason: proving the schema against a small, genuinely representative real subset is lower-risk than a large mechanical transcription with nowhere left to catch a schema mistake before it's copied fourteen more times. Chosen for coverage, not convenience:

- **`deadline_sweep`** (mechanical, zero escalation, zero prompt) — the simplest real shape, and its own domain logic (`deadline.sweep`, ADR-020) already exists in this codebase, so its `mandate`/`degradation` text is grounded in real, already-built behavior, not invented.
- **`critic`** (cognitive, the *zero-tools* edge case — Appendix A's own "ALL world-touching tools" forbidden row) — proves the schema tolerates `tools = ()` correctly.
- **`planner`** (cognitive, the most load-bearing agent in the catalog, and the one whose deterministic degradation path — M5's Planner — is the most already-built in this codebase) — proves a definition with a real pipeline membership (`weekly_close`) and a non-trivial scope set together.

**The remaining twelve agents and the four pipelines are this ADR's own named next step**, not silently dropped: mechanical transcription work once this schema is accepted and proven, not a design decision needing its own ADR.

Prompt files shipped with `critic`/`planner` this slice are **first drafts, not tuned prompts** — nothing executes them yet (no executor exists — a separate ADR-028 item), so there is nothing to tune against. Marked as such in their own header comment.

## Consequences

- **AG-004 goes from fully-specified-in-prose to a real, loadable, validated registry.** "What can KANG do?" is answerable by reading a directory, literally, for the first time.
- **A genuine reuse, not a new mechanism:** the pairing lint that already guards `permissions.toml` now also guards agent definitions themselves, at the point a bad design is authored rather than only at the point it's granted.
- **Two things stay explicitly unbuilt, both already named elsewhere, restated here for this slice's own boundary:** manifest assembly (Phase 2, blocked on Memory) and the tool executor/port (a separate M7 item — ADR-028's own list).
- **Twelve agents and four pipelines remain to transcribe**, precisely scoped as this ADR's own next step rather than an open-ended "finish the catalog someday."

## Verification

**Implemented and verified (2026-09-14), same day as acceptance.** What landed: `domain/ports/agent_definition.py` (`AgentDefinition`, `EscalationCapability`, `AgentDefinitionInvalid`); `adapters/config/agent_definitions_loader.py` (structural parse + validation); `kernel/orchestrator/registry.py` (`AgentRegistry`, `build_checked_registry` — the pairing-lint reuse); `src/kang/agents/definitions/{deadline_sweep,critic,planner}/` (the three real definitions, with first-draft prompts for the two cognitive ones).

**A design correction found while implementing, not pre-specified in D3:** the ADR's own Verification draft named "a duplicate `id` across two folders" as an expected proof point. Building the loader surfaced that this is structurally impossible under D1's flat layout — a folder's declared `id` must equal its own folder name (D3's own rule), and two folders cannot share a name within one parent directory, so no two loaded definitions can ever collide on `id`. The dead check (and its untestable-as-designed test) were removed rather than kept for appearances; `discover_agent_definitions`'s own docstring now states this explicitly, including the trigger for revisiting it (the `>20` agents nested-grouping option 17_PROJECT_STRUCTURE already names).

**Corrected by ADR-041** (2026-09-16): `deadline_sweep`'s `tools` field originally transcribed Appendix A's illustrative prose verbatim (`["deadlines.read", "deadlines.mark_alerted", "notify:critical"]`). ADR-041 D1 decided what "tool" actually means (a tool call IS an operation dispatch) and found none of those three names a real, separately-callable thing — `deadline.sweep` already performs the whole mandate internally, and `"deadlines.mark_alerted"` was that operation's own required *scope*, not a tool name, sharing a string by coincidence. Corrected to `tools = ["deadline.sweep"]`. No other shipped definition was affected (`critic`'s and `planner`'s own `tools` — `notify:digest`/`notify:attention` plus `planner`'s `tasks.*` — remain as drafted; `tasks.*`'s own resolution is deferred to whenever a cognitive executor is built, out of ADR-041's mechanical-only scope).

Proven, not assumed: 35 new tests. `test_agent_definitions_loader.py` (27): every required field's absence, the `kind` enum, non-positive/non-integer `timeout_s`, negative `retry`, `tools`' own three rules (key-must-be-present, no empty-string entries, no duplicates — while an empty tuple is explicitly valid, `critic`'s own case), a cognitive definition missing or pointing at a nonexistent `prompt_file`, a mechanical definition that sets one anyway, an `escalation` on a cognitive definition, a mechanical definition's *valid* escalation, an `escalation.task_class` outside `TaskSpec.TASK_CLASSES` (ADR-038 D2, reused), a missing `escalation.prompt_file`, a folder/`id` mismatch, `discover`'s own folder-walk and missing-manifest cases, and the three real shipped definitions loading with their exact expected shapes. `test_registry.py` (8): a clean multi-agent registry builds and indexes correctly; each of the pairing lint's real rules (`web.fetch`+`memory.read:sensitive`, `web.fetch`+`vault.write`, `memory.propose:rule`/`profile` ungrantable, wildcard-forbidden-for-agents) refuses when violated by an agent's own declared scopes — proving the reuse is real, not cosmetic; one bad agent among several refuses the WHOLE registry, not just itself; the real shipped catalog passes the lint end to end. Full suite: 1012 passed (up from 977, no silent coverage loss). Full lint suite: 0 hard violations (one function needed a size-lint split, `parse_agent_definition` → `+_parse_bounds`/`_check_prompt_and_escalation_shape`), `ruff check .`/`lint-imports`/banned-patterns/tree-hygiene all clean. Zero network, zero model calls anywhere in the suite (13_TESTING §1) — a pure data/validation slice.

**D4 completed (2026-09-16):** the remaining twelve agents landed — `competition_strategist`, `competition_scout` (+ its own classification escalation), `researcher`, `tutor`, `memory_steward` (+ its own routine-task-class escalation), `vault_indexer`, `vault_organizer`, `web_monitor` (+ escalation), `notifier`, `backup_monitor`, `health_monitor`, `faith_companion` — the full 15-agent Appendix A catalog now loads and pairing-lints cleanly (confirmed live: `discover_agent_definitions` + `build_checked_registry` against the real shipped directory, 15/15, zero violations). `sync_agent` (reserved, its own definition explicitly deferred to 16_SYNC, which doesn't exist) and `plugin_runner` (a per-plugin execution template, not a static catalog entry — its own allowlist comes from "the plugin's granted allowlist ONLY," per-installation, not a fixed definition file) stay excluded, as ADR-040's own original 15-agent count already implied.

Two of the twelve (`backup_monitor`, `health_monitor`) got `tools` resolved to real registered operations (`backup.snapshot`/`backup.verify`/`backup.offsite_check`; `system.health`) rather than left illustrative — their underlying operations already exist and already perform the whole mandate, the same shape ADR-041 found for `deadline_sweep`. The rest stay illustrative, matching `critic`/`planner`'s own already-accepted precedent: no cognitive executor exists yet to make resolving their tool names urgent, and forcing a premature resolution risks a second correction later rather than a real one. `notifier` is named explicitly as a case that may never fit the operation-dispatch model at all — its real mechanism is a bus subscriber (`notifier.drain`), not an invocable, admission-checked thing.

Existing tests extended (not a new file) to assert the full 15-agent set, the two resolved-tools cases, both escalations' task classes, and `researcher`'s own scope set correctly excluding `memory.read:sensitive`. Test count unchanged (1017 — no new test functions were needed; existing shipped-catalog assertions grew richer). Full lint suite and full test suite re-confirmed green.
