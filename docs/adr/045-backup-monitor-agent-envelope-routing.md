# ADR-045 — Routing `backup_monitor`'s three jobs through the mechanical-agent envelope

**Status:** accepted (2026-09-16)
**Date:** 2026-09-16
**Supersedes:** none
**Affected documents:** none — this is ADR-043's own named candidate, extended; no new destination to describe
**Cites:** ADR-043 (the exact precedent: `deadline_sweep` routed through `run_mechanical_agent` instead of a direct `kernel:scheduler` dispatch, `AGENT_ROUTED_JOBS` named `backup_monitor`'s three jobs explicitly as "a real, same-shaped future candidate, deliberately NOT added here"), ADR-034 D2 (`backups.read` as its own scope, distinct from `backups.write`, because `backup.offsite_check` writes no file)
**Related:** [[043-deadline-sweep-agent-envelope-routing.md]]

---

## Context

ADR-043 named this exact extension and deliberately did not build it: "`backup_snapshot`/`backup_verify`/`backup_offsite_check` each name one of `backup_monitor`'s own allowed tools — a real, same-shaped future candidate... widening this set is its own future decision, not defaulted here." Asked directly this session (not defaulted): route all three now.

**One real difference from `deadline_sweep`, found while grounding this, not assumed from the precedent:** ADR-043's routing worked because `job.name == agent.id` for `deadline_sweep` (both literally `"deadline_sweep"`), so `AGENT_ROUTED_JOBS: frozenset[str]` plus `agent_registry.get(job.name)` was sufficient — one string did double duty by coincidence, named explicitly as coincidence, not relied on as a mechanism. That coincidence does **not** hold here: `backup_monitor`'s three job names (`backup_snapshot`, `backup_verify`, `backup_offsite_check`) never equal its own agent id (`backup_monitor`). A frozenset can no longer answer "which agent runs this job" — it needs to become a real `job name → agent id` mapping.

## Decision

### D1 — `AGENT_ROUTED_JOBS` becomes `dict[str, str]` (job name → agent id), not a frozenset

```python
AGENT_ROUTED_JOBS: dict[str, str] = {
    DEADLINE_SWEEP_JOB: "deadline_sweep",
    BACKUP_SNAPSHOT_JOB: "backup_monitor",
    BACKUP_VERIFY_JOB: "backup_monitor",
    BACKUP_OFFSITE_CHECK_JOB: "backup_monitor",
}
```

`_run_via_agent_envelope` looks up `AGENT_ROUTED_JOBS[job.name]` to get the agent id, then `agent_registry.get(agent_id)` — the same two-step lookup ADR-043 already used, just no longer conflating "job name" and "agent id" as one string. `morning_plan` (real cognitive counterpart is `planner`, out of scope for the mechanical-only executor) and `held_action_expire` (names no agent in Appendix A's catalog at all) stay off this map, unchanged from ADR-043's own reasoning.

### D2 — Both `backups.write` and `backups.read` move from `kernel:scheduler` to `agent:backup_monitor`

`backup_snapshot`/`backup_verify` need `backups.write`; `backup_offsite_check` needs `backups.read` (ADR-034 D2's own split — it writes no file). All three now dispatch under `agent:backup_monitor`, so both scopes move together — `kernel:scheduler` no longer calls any backup operation directly, so it keeps neither. `kernel:scheduler`'s remaining grants (`tasks.write`, `held_actions.expire`) are untouched — this ADR moves exactly the two lines it stopped needing.

No pairing-lint conflict: `backups.write`/`backups.read` together trigger none of `kernel/permissions/pairing.py`'s forbidden-pair, ungrantable, or wildcard rules, checked against both the `permissions.toml` grant (`build_checked_engine`) and `backup_monitor.toml`'s own (empty) `scopes` field (`build_checked_registry`) — the same two independent, already-clean lints ADR-043 confirmed for `deadline_sweep`.

## Consequences

- **One agent runs three jobs' worth of dispatch**, the first time `AGENT_ROUTED_JOBS` has needed a real mapping rather than a coincidence — the mechanism ADR-043 built generalizes past its first, accidentally-simple case, proving it was a real mechanism and not a one-off.
- **A real, audited behavior change to already-working production code**, same shape as ADR-043: every `backup_snapshot`/`backup_verify`/`backup_offsite_check` invocation's own audit/invocation row now records principal `agent:backup_monitor`, not `kernel:scheduler`.
- **No further same-shaped candidate remains.** `health_monitor` also has `tools` resolved to a real operation (`system.health`) — but checked here, not assumed: no `health_check`-style job exists in `scheduler_wiring.py` at all; Appendix A's own "sched (5m tick)" trigger for it has never been built. `system.health` today is reachable only as a query Kang/the UI calls directly, nothing scheduled to migrate. `AGENT_ROUTED_JOBS` now covers every real, already-scheduled, tools-resolved mechanical agent this codebase has.

## Verification

**Implemented and verified (2026-09-16), same day as acceptance.** What landed: `AGENT_ROUTED_JOBS` (`scheduler_wiring.py`) changed from `frozenset[str]` to `dict[str, str]` (job name → agent id), now mapping all four routed jobs; `_run_via_agent_envelope` updated to look up the agent id through that map rather than treating the job name as the agent id; `config/defaults/permissions.toml`'s `backups.write`/`backups.read` moved from `kernel:scheduler` to a new `agent:backup_monitor` entry.

Proven, not assumed: the three existing real-subprocess boot-catchup tests for `backup_snapshot`/`backup_verify`/`backup_offsite_check` (`tests/suites/replay/test_boot_catchup.py`) still pass against the real, edited `permissions.toml`, each extended with a new assertion that the real `invocation.principal` is `agent:backup_monitor`, not `kernel:scheduler`. Adjacent scheduler/job unit tests re-run clean.

Live-verified beyond pytest, as a real throwaway `%KANG_HOME%` with the real shipped `permissions.toml`/`kang.toml`, a real `build_core()`: a real `backup.snapshot` (via `run_mechanical_agent`) produces a real, openable snapshot and the real `invocation` row records `agent:backup_monitor`; a real `backup.verify` against that real snapshot succeeds the same way; `kernel:scheduler` attempting either operation is now genuinely refused (`permission_denied`, `missing scope backups.write`) — proving the grant actually moved, not merely duplicated. Throwaway home deleted after.

**A claim caught and corrected before it went into this ADR's own record:** an early draft named `health_monitor` as "the next, same-shaped candidate." Checked, not assumed — `health_monitor`'s own `tools` are resolved to a real operation (`system.health`), but no scheduled job for it exists anywhere in `scheduler_wiring.py` at all (Appendix A's own "sched (5m tick)" trigger was never built); there is nothing to migrate. Corrected in Consequences above.

Full suite: **1050 passed** (unchanged — assertions added to existing tests, no new test functions needed). Full lint suite: 0 hard violations. Import contracts: 8/8 kept (no new exemption needed — this slice only touched an already-composition-root file's own logic, not its import surface). Zero network, zero model calls (13_TESTING §1).
