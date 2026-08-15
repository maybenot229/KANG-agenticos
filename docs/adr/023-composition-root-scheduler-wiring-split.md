# ADR-023 — Splitting scheduler wiring out of `composition.py`, extending the composition-root import exemption to a second file

**Status:** accepted
**Date:** 2026-08-13
**Affected documents:** `17_PROJECT_STRUCTURE.md` §4.3 (the composition-root exemption, previously scoped to exactly one file), `tools/importlinter.toml`
**Cites:** `composition.py`'s own module docstring ("the ONE exemption... MAY import adapters and the api... registered by name in `tools/importlinter.toml` and MUST NOT spread"), 11_CODING §25 (size lints, no negotiating)

---

## Context

Wiring `held_action.expire` as a third scheduler job (ADR-022) pushed `composition.py` past two hard size-lint limits at once: the file itself (816 lines, hard limit 800) and `_wire_scheduler` (83 lines, hard limit 80). This was named as a real risk in the 2026-08-13 session handoff ("composition.py is sitting exactly at the 800-line hard limit... the next addition will need a genuine module split") — it just arrived sooner than a "someday" item, on the third job in three ADRs.

The obstacle is not size alone: `composition.py`'s own docstring states the import-matrix exemption that lets it import both `adapters/` and `api/` is registered by name in `tools/importlinter.toml` for exactly this one module, "MUST NOT spread." Scheduler wiring genuinely needs both — `_make_schedule_parser` imports `kang.adapters.scheduler` (cron parsing), `_make_job_runner` imports `kang.api.dispatch` (the job → operation dispatch seam, ADR-006 Part B) — so moving it to a second file requires either extending that exemption or finding some other shape.

## Decision

**Extend the exemption, deliberately, to a second file that is the same role, not a second role.** `kang.kernel.runtime.scheduler_wiring` is not a new kind of module — it is the composition root's own scheduler-wiring concern, split out for a mechanical reason (the size lint), containing exactly the same class of code the exemption was written for: plain construction, concretions meeting interfaces, zero domain logic. The exemption's own stated purpose ("something must instantiate concretions and inject them") applies identically; what's being extended is which *file* does it, not the *role's* scope. `composition.py` keeps `build_core`, `serve`, `Core`, store/handler wiring; `scheduler_wiring.py` gets the scheduler-specific slice: `JOB_OPERATIONS`, the three job-id constants, `_make_schedule_parser`, `_SchedulerWiring`, `_make_job_runner`, `_wire_scheduler`, `_make_ticking_server_class`, `TICK_INTERVAL_S`. `composition.py` calls into it exactly as it called its own private functions before — the public seam (`build_core`, `serve`) is unchanged.

`tools/importlinter.toml`'s `ignore_imports` gains two lines mirroring the existing pair exactly, naming the new module instead of adding a wildcard or loosening the rule's shape:
```
"kang.kernel.runtime.scheduler_wiring -> kang.adapters.**",
"kang.kernel.runtime.scheduler_wiring -> kang.api.**",
```

**What this is not:** not a general loosening ("composition-root-like files may import freely") — the contract still names exact modules, not a pattern. A third file would need its own line, its own justification, same as this one needed this ADR.

## Consequences

- `composition.py` returns to real headroom under both size limits, not another same-file trim.
- Two files now carry the composition-root exemption instead of one — a real, named increase in the "MUST NOT spread" surface, accepted because the alternative (an unbounded single file, or a same-file trim that will hit the wall again on the next job) is worse, per 11 §25's own "split the unit" answer to a lint failure.
- Future scheduler-related wiring (a fourth job, e.g.) grows `scheduler_wiring.py`, not `composition.py` — the size pressure moves to the file that actually owns that growth.

## Verification

A pure code-organization change — no behavior to live-verify against a real Core beyond what ADR-022's own live verification already re-proves (all three jobs still register and run correctly post-split). What this ADR needs proof of instead: the split didn't break the import contract it depends on, and every existing caller of the moved symbols still resolves. Confirmed: `lint-imports` reports all 8 contracts kept including the two new `scheduler_wiring` exemption lines; the full backend suite (817 tests) passes with the three test files that imported scheduler-wiring symbols from `composition` repointed at `scheduler_wiring` directly (not re-exported — the honest representation of where the symbols now live); `lint_sizes.py` reports 0 hard violations with real headroom on both files.
