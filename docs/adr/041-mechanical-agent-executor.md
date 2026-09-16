# ADR-041 — The mechanical-agent executor: a tool call is an operation dispatch

**Status:** accepted (2026-09-16)
**Date:** 2026-09-16
**Supersedes:** none
**Affected documents:** none — 05_AGENTS §3/§9/AG-005 already describe the destination; this ADR is the implementation, and one dated correction to ADR-040's own `deadline_sweep` definition (see below)
**Cites:** 05_AGENTS §3 (`docs/05_AGENTS.md:82-114`, the nine-phase lifecycle), AG-005 (`:225`, the tool allowlist), ADR-028 C4 (already-settled: "M7's tool executor MUST enforce the per-agent allowlist itself, before and independently of the dispatcher's scope check"), ADR-020 (`deadline.sweep` as an automatic job — the real domain logic this slice proves against), `kernel/runtime/scheduler_wiring.py::_make_job_runner` (the exact session-minting precedent this reuses), 03_ROADMAP (Phase 1: "Intentionally postponed: all cognitive agents beyond basic chat" — why this ADR is mechanical-only), ADR-040 (the registry this reads from)
**Related:** [[040-agent-registry.md]], [[028-m7-foundations.md]]

---

## Context

`agents/runtime/__init__.py` says *"The ONE executor: lifecycle phases 1-9... built at M7"* and is empty. ADR-040 built the registry (what agents exist); nothing yet runs one.

**The scope-narrowing finding, made before any code:** 03_ROADMAP's Phase 1 section states plainly — *"Intentionally postponed. All cognitive agents beyond basic chat"* — and Phase 3's own text confirms the cognitive catalog (`Critic`, `Researcher`, `Tutor`, ...) is a Phase-3 deliverable, dependent on Phase 2 Memory (*"the Critic is meaningless without retrospectives to cite"*). **This ADR builds a mechanical-agent executor only.** `critic` and `planner` (registered as data in ADR-040) stay unrun; "basic chat" is a separate, still-unscoped question. Confirmed with Kang before drafting, not assumed.

**A second finding, resolving what "tool" actually means, which AG-005 itself leaves open:** Appendix A's tool-column prose (`deadlines.read`, `deadlines.mark_alerted`, `notify≤critical` for `deadline_sweep`) does not name three real, separately-callable things. `deadline.sweep` (the operation, ADR-020) already performs the *entire* mandate internally — reads active deadlines, marks them alerted, publishes the event the notifier delivers from. There is no separate "read" tool, no separate "mark_alerted" tool, and the agent never calls "notify" itself; the notification is a *consequence* of the one operation it does call, not a second tool invocation. **Decided here: a tool call IS an operation dispatch** — the exact same `Dispatcher.dispatch()` pipeline every UI command and every scheduled job already goes through, reused wholly, not wrapped in a new "Tool" abstraction. AG-005's own framing already pointed here ("domain service tools... verbs with validation, not table access" — precisely what a registered operation already is); this ADR just confirms it rather than inventing a parallel mechanism `kernel/permissions/pairing.py`-style tool grammar would have needed to duplicate.

**Corrects ADR-040's own `deadline_sweep` definition**, found while grounding this ADR: its `tools` list transcribed Appendix A's illustrative prose verbatim (`["deadlines.read", "deadlines.mark_alerted", "notify:critical"]`), none of which is a real operation name except `deadlines.mark_alerted` — which is actually `deadline.sweep`'s own required *scope*, not a tool name at all (the two happen to share a string by coincidence of naming, not by design). Corrected to `tools = ["deadline.sweep"]` — the one real operation this agent may call.

## Decision

### D1 — A tool call is a session-minted operation dispatch, mirroring `_make_job_runner` exactly

```python
def run_mechanical_agent(
    agent: AgentDefinition, operation: str, params: dict,
    *, dispatcher: Dispatcher, sessions: SessionStore, new_id, clock: Clock,
) -> AgentRunResult
```

- Refuses immediately, without ever calling `dispatcher.dispatch()`, if `operation not in agent.tools` (ADR-028 C4: the allowlist is checked *before and independently of* the dispatcher's own scope check — the dispatcher's `permission_denied` and the executor's own allowlist refusal are different facts, and only the second is checked here).
- Mints a session for principal `f"agent:{agent.id}"`, `first_party=False` — identical reasoning to `_make_job_runner`'s own already-accepted comment: *"a job is not Kang's hand"* applies verbatim to an agent (SEC-003 enforced by construction: no agent principal can ever approve a held action, because none can hold a first-party session).
- Dispatches through the **same** `Dispatcher.dispatch()` every other caller uses — full pipeline, unchanged: schema validation, idempotency, the dispatcher's own scope check (this is the *second*, independent gate ADR-028 C4 names — `permissions.toml` still needs its own real grant for `agent:{id}`, a separate and deliberately un-taken step this slice, see D3), execution, audit.
- `AgentRunResult` wraps the dispatch response plus which agent/operation ran — enough for a caller to log or assert against, not a new persistence concept.

### D2 — Lifecycle phases that are genuinely trivial for THIS agent shape stay real, empty steps — never silently skipped

05_AGENTS §3: *"Phases MUST execute in order; skipping is forbidden (mechanical agents pass trivially through model-related phases)."* For a mechanical, single-tool, zero-memory-proposal agent: context manifest (phase 3), planning (phase 4), output validation beyond the dispatcher's own schema check (phase 6), and memory proposal (phase 7) are **structurally present, substantively no-ops** — `run_mechanical_agent` does not fabricate content for any of them, and does not pretend they ran with something to show. This is the honest reading of "pass trivially through," not an excuse to omit the phase from the function's own shape.

### D3 — Deliberately NOT this slice, each named with its own reason

- **No `permissions.toml` grant for any `agent:*` principal.** Activating `deadline_sweep` with real authority is a separate, deliberate step — this ADR proves the *mechanism*, live-verified against a throwaway config, never the shipped one. Mirrors the Router/Registry's own "dormant, callable by nothing yet" precedent.
- **Not wired into `composition.py`/`scheduler_wiring.py`.** The scheduler's own job-runner already dispatches `deadline.sweep` correctly today (ADR-020); this executor is a second, parallel, unwired path proving the *agent envelope* shape, not a replacement. Whether/when to route the scheduled trigger through the agent envelope instead (AG-004's own unification goal — "everything KANG does autonomously is inspectable the same way") is its own future decision, not defaulted here.
- **No new outer `kind="agent"` invocation row.** `domain/ports/invocation.py` already anticipates this (`INVOCATION_KINDS = ("command", "query")  # 'agent' joins at M7`), and the DB's own CHECK constraint (migration 0004) would need widening to accept it. For a single-tool-call mechanical agent, the underlying operation's own `kind="command"` invocation record — created by the normal dispatch this ADR reuses unchanged — is a complete, honest audit trail already; a wrapping agent-level record earns its cost once an agent makes multiple tool calls or has real planning to explain, neither of which exists yet. Named, not silently dropped.
- **No admission-phase concurrency cap or budget precheck (AG-006/AG-008).** Nothing tracks concurrent invocations or real spend yet (ADR-038 D4's own already-named deferred gap) — enforcing a cap against state that doesn't exist would be checking nothing, the same reasoning ADR-036 D1 used against pre-building for a hypothetical.

## Consequences

- **05_AGENTS §3's lifecycle is real code for the mechanical case**, proven against `deadline.sweep` — the same domain logic already running in production via the scheduler, now provably reachable through the agent envelope too.
- **"Tool" stops being an undefined word in this codebase.** A tool call is an operation dispatch, full stop — no second registry, no second permission model, no new ADR-028-C4-shaped gap for the cognitive executor to rediscover later.
- **A real, dated correction lands in ADR-040** (`deadline_sweep`'s `tools` field) rather than compounding a transcription error silently.
- **Four things stay explicitly unbuilt, each with its own trigger named, not open-ended:** the real `permissions.toml` grant, wiring into the scheduler, the outer agent-kind invocation row, and admission's own concurrency/budget checks.

## Verification

Deferred to the implementation slice this ADR authorizes. Expected proof, named now: the executor refuses an operation not in the agent's `tools` list *without* ever calling `dispatcher.dispatch()` (a fake dispatcher records zero calls); a real dispatch for `deadline_sweep`/`deadline.sweep` against a fake `Dispatcher`+`SessionStore` mints a session for `agent:deadline_sweep`, `first_party=False`, and returns the dispatch response verbatim; live-verified against a real throwaway `%KANG_HOME%` with a throwaway `permissions.toml` granting `agent:deadline_sweep = ["deadlines.mark_alerted"]` (never the shipped default) — a real `deadline.sweep` dispatch through the executor produces the identical effect (deadlines transitioned, event published) the scheduler's own existing path already produces, then the throwaway home is deleted. Zero network, zero model calls (13_TESTING §1) — this is a deterministic, zero-model agent shape by construction.
