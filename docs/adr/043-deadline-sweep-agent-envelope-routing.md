# ADR-043 — Routing `deadline_sweep` through the mechanical-agent envelope

**Status:** accepted (2026-09-16)
**Date:** 2026-09-16
**Supersedes:** none
**Affected documents:** none — AG-004's own unification goal already names the destination; this ADR is the implementation of a question ADR-041 deliberately left open
**Cites:** ADR-041 (`run_mechanical_agent`, built as "a second, parallel, unwired path proving the agent envelope shape... whether/when to route the scheduled trigger through the agent envelope instead is its own future decision, not defaulted here"), ADR-020 (`deadline.sweep` as an automatic job — the production path this ADR changes), ADR-006 Part B (the job→operation seam `_make_job_runner` already established), ADR-040 D4 (the real `AgentRegistry` this ADR wires into `Core` for the first time), 05_AGENTS AG-004 ("everything KANG does autonomously is inspectable the same way" — the unification goal this ADR partially realizes), 05_AGENTS §3 (the nine-phase agent lifecycle — this ADR is what makes phase 1's admission actually run for a real scheduled trigger)
**Related:** [[040-agent-registry.md]], [[041-mechanical-agent-executor.md]]

---

## Context

ADR-041 built the mechanical-agent executor (`run_mechanical_agent`) and proved it live against a throwaway config — but explicitly did not wire it into the real, running system. The real `deadline_sweep` job still runs exactly as ADR-020 built it: `kernel/runtime/scheduler_wiring.py::_make_job_runner` mints a session for principal `kernel:scheduler` and calls `Dispatcher.dispatch()` directly. ADR-041 named the unwired question explicitly and declined to decide it: "whether/when to route the scheduled trigger through the agent envelope instead (AG-004's own unification goal) is its own future decision, not defaulted here."

Kang decided this fork directly (2026-09-16, asked as a structured question rather than defaulted): route it now, accepting that this touches already-working production behavior.

**A precondition this decision surfaces, not previously true of anything in the running system:** nothing in `composition.py` has ever built a real `AgentRegistry`. ADR-040/041's own registry and executor exist, are tested, and are live-verified against throwaway configs — but `Core` itself has never held one. Routing `deadline_sweep` for real requires looking up its `AgentDefinition` (kind, tools) from somewhere, and the only correct "somewhere" is the real, fail-closed `AgentRegistry` (ADR-040 D3) — not a narrow, single-file bypass that would quietly drop that ADR's own "one bad definition refuses the whole load" guarantee for production wiring specifically. **This ADR is therefore also the first time `AgentRegistry` is wired into a real, running `Core`.**

**A second precondition, found while grounding this:** `run_mechanical_agent` checks `operation in agent.tools` (AG-005's allowlist) — that gate is independent of and prior to whatever scope check `Dispatcher.dispatch()` itself performs (ADR-028 C4). But the dispatcher's *own* scope check still runs, against `permissions.toml`, under whichever principal actually calls it. Today that grant (`deadlines.mark_alerted`) sits on `kernel:scheduler`. Routing through `agent:deadline_sweep` without moving the grant would make every real run fail with a permission denial — not a subtle bug, a total outage of the one job whose own docs call its failure "itself a critical-priority alert, never a silent skip." The grant move is therefore load-bearing, not cosmetic.

## Decision

### D1 — `Core` builds a real, checked `AgentRegistry` at boot; a bad registry refuses to boot

New `AGENT_DEFINITIONS_DIR` (composition.py), computed package-relative exactly as the existing `MIGRATIONS_DIR` precedent does (`Path(__file__).resolve().parents[2] / "agents" / "definitions"` — `parents[2]` from `kernel/runtime/composition.py` is `src/kang`). `_build_core_locked` calls `build_checked_registry(discover_agent_definitions(AGENT_DEFINITIONS_DIR))` once, unconditionally, and does **not** catch `AgentDefinitionInvalid`.

**Why this differs from `_load_grants`'s own fail-open-to-`KANG_ONLY_GRANTS` posture (07 F8):** `permissions.toml` is a live, hand-editable, %KANG_HOME%-scoped file (D003) — Kang can type a typo into it, and bricking his own manual use of the system over his own edit would be a worse failure than degrading to Kang-only authority and saying so (`_wire_scheduler`'s own documented reasoning, reused for that file, not reinvented). `agents/definitions/` is neither: it ships inside the package, is never user-edited (AG-004: "KANG MUST NOT synthesize new agents, modify definitions... at runtime"), and this session's own full test suite already proves the shipped catalog loads and pairing-lints cleanly. A malformed shipped agent definition in production would mean the shipped code itself is broken — the same class of problem a Python syntax error already is, and Core already doesn't attempt to boot around those. Refusing to boot is the honest signal; a degraded, dormant registry would hide a real defect behind a normal-looking start-up.

`AgentRegistry` is exposed as `Core.agent_registry` (mirroring `Core.clock`'s own "exposed for introspection/tests" precedent) — not consumed anywhere but the scheduler yet, but not hidden either.

### D2 — `_make_job_runner` routes named jobs through `run_mechanical_agent`; everything else keeps the direct path

A new, explicit `AGENT_ROUTED_JOBS: frozenset[str] = frozenset({DEADLINE_SWEEP_JOB})` in `scheduler_wiring.py` — deliberately a named, reviewable set (matching `JOB_OPERATIONS`'s own "reviewable in one place" shape), **not** an implicit "route any job whose name happens to match a real agent id." The other four jobs do not name real agents 1:1 today: `morning_plan`'s real cognitive counterpart is `planner`, out of scope for the mechanical-only executor (03_ROADMAP Phase 1); `held_action_expire` has no agent definition in Appendix A's catalog at all — it is kernel plumbing, not agent work. (`backup_snapshot`/`backup_verify`/`backup_offsite_check` *do* each name one of `backup_monitor`'s own allowed tools — a real, same-shaped future candidate, named here and left there: extending `AGENT_ROUTED_JOBS` is Kang's call each time, not this ADR's to widen unasked.)

For a job in `AGENT_ROUTED_JOBS`, `_make_job_runner`'s closure now:
1. Looks up `agent_registry.get(job.name)` (the job name and the agent id are identical strings for `deadline_sweep` — named explicitly in `AGENT_ROUTED_JOBS`, not inferred from the coincidence).
2. Wraps `Dispatcher.dispatch` in the plain `Dispatch` callable shape `run_mechanical_agent` expects (`agents/runtime` may not import `kang.api` — 17 §4.2 — so the executor's own port stays a generic callable; only the composition root, which may import both, bridges them).
3. Calls `run_mechanical_agent(agent, operation, {}, executor_deps, idempotency_key=...)` — the **same** idempotency key format (`f"job:{job.id}:{slot.isoformat()}"`) as before, so API-004 dedup behavior is unchanged; only the principal minting the session changes, from `kernel:scheduler` to `agent:{agent.id}`.
4. Checks `response.get("ok")` and raises on failure exactly as the direct path already does — the Scheduler's own retry/quarantine logic (05 §11) does not need to know which path ran.

Every job outside `AGENT_ROUTED_JOBS` keeps the exact, unchanged direct-dispatch path under `kernel:scheduler`.

### D3 — The `deadlines.mark_alerted` grant moves from `kernel:scheduler` to `agent:deadline_sweep`

`config/defaults/permissions.toml`: removed from `kernel:scheduler`'s list (it no longer dispatches `deadline.sweep` itself), added as `"agent:deadline_sweep" = ["deadlines.mark_alerted"]` — least privilege following the actual caller, not a second copy of the same grant held by two principals for one operation. `kernel:scheduler` keeps every other grant (`tasks.write`, `held_actions.expire`, `backups.write`, `backups.read`) — this ADR moves exactly one line, the one job it actually stopped calling directly.

No pairing-lint conflict: `deadlines.mark_alerted` alone triggers none of `kernel/permissions/pairing.py`'s forbidden-pair, ungrantable, or wildcard rules, checked against both the `permissions.toml` grant (via `build_checked_engine`) and `deadline_sweep.toml`'s own (empty) `scopes` field (via `build_checked_registry`) — two independent lints, both already run, both still clean.

## Consequences

- **`AgentRegistry` is now load-bearing in the real running system**, not only in tests and throwaway live-checks — the first of AG-004's registries to leave the "correct but inert" state ADR-040/041 both left it in.
- **A real, audited behavior change to already-working production code:** every `deadline_sweep` invocation's own audit/invocation row now records principal `agent:deadline_sweep`, not `kernel:scheduler`. `kang explain` reconstructions for this job change accordingly — an intended consequence of "inspectable the same way," not a side effect to hide.
- **A precedent, not a generalization:** `backup_monitor`'s own three jobs are a same-shaped future candidate, named and explicitly left undecided — widening `AGENT_ROUTED_JOBS` is its own future ask, not defaulted by this ADR just because the mechanism now exists.
- **A bad shipped agent definition now bricks boot.** Argued deliberately above (D1) as the honest failure mode for code-shipped, non-user-edited data — reviewed here as a real trade-off, not an oversight.

## Verification

**Implemented and verified (2026-09-16), same day as acceptance.** What landed: `AGENT_DEFINITIONS_DIR` + `_build_agent_registry()` (`composition.py`) — the first real `AgentRegistry` build inside `_build_core_locked`, exposed as `Core.agent_registry`; `AGENT_ROUTED_JOBS`, `_run_via_agent_envelope`/`_run_via_direct_dispatch` (`scheduler_wiring.py`) — `_make_job_runner` now branches on job name, routing `deadline_sweep` through `run_mechanical_agent` and leaving every other job's original direct-dispatch path untouched; `config/defaults/permissions.toml`'s `deadlines.mark_alerted` grant moved from `kernel:scheduler` to a new `agent:deadline_sweep` entry; a new `tools/importlinter.toml` ignore-imports entry (`kernel.runtime.scheduler_wiring -> kang.agents.**`) extending the composition root's existing exemption to the one file that now needs it; module-header updates to `agents/__init__.py` and `agents/runtime/__init__.py` correcting their now-stale "nothing wired to call this yet" claims.

A hard-limit size violation each in `_build_core_locked` (92 lines) and `_make_job_runner` (84 lines) turned up mid-implementation from the added wiring — both split (a new `_build_agent_registry()` helper; `_make_job_runner`'s agent-envelope and direct-dispatch branches extracted to their own module-level functions) rather than the limit bumped, per 11 §4/CLAUDE.md §11's own named-forbidden-shortcut list ("bumping a limit instead of splitting a function").

Proven, not assumed: the existing real-subprocess boot-catchup test for `deadline_sweep` (`tests/suites/replay/test_boot_catchup.py::test_deadline_sweep_is_registered_and_boot_catches_up_a_missed_hour`) still passes against the real, edited `config/defaults/permissions.toml` — a real boot, backdated job, real catch-up, real outcome `"ok"` — proving the grant move didn't strand the job, extended with a new assertion (via a new `_invocation_principal` helper querying the real `invocation` table) that the recorded principal for `deadline.sweep` is now `agent:deadline_sweep`, not `kernel:scheduler`. All 62 tests in the immediately-adjacent unit/suite files (`test_job_operations.py`, `test_scheduler_tick.py`, `test_executor.py`, `test_deadline_operations.py`, the determinism/explainability/replay suites) re-run clean.

Live-verified beyond pytest, as a real throwaway `%KANG_HOME%` with the real shipped `permissions.toml`/`kang.toml`, a real `build_core()`, never the real home: `Core.agent_registry` holds all 15 real agents; a real `deadline.create` followed by a real `run_mechanical_agent("deadline_sweep", "deadline.sweep", ...)` call genuinely alerts the deadline it created (`{"alerted": [...], "count": 1}`, not a no-op); the real `invocation` row for that call records principal `agent:deadline_sweep`; a session minted for `kernel:scheduler` attempting the same operation is now genuinely refused (`permission_denied`, `missing scope deadlines.mark_alerted`) — proving the grant actually moved, not merely duplicated. Throwaway home deleted after.

Full suite: **1038 passed** (same count as before this ADR — one assertion added to an existing test function, no new test function needed). Full lint suite: 0 hard violations (both violations named above fixed, not bumped). Import contracts: 8/8 kept, one new ignore-imports entry added and justified inline. Zero network, zero model calls (13_TESTING §1).
