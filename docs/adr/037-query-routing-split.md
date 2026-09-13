# ADR-037 — Splitting query routing out of `composition.py`, extending the composition-root import exemption to a third file

**Status:** proposed
**Date:** 2026-09-14
**Affected documents:** `17_PROJECT_STRUCTURE.md` §4.3 (the composition-root exemption, previously scoped to two files — and corrected here to actually say so; ADR-023 never updated its prose, only `composition.py`'s own docstring and `tools/importlinter.toml`), `tools/importlinter.toml`
**Cites:** ADR-023 (the identical split, one file earlier — "a third file would need its own line, its own justification, same as this one needed this ADR"), ADR-036 D4 resumed (the read-pool query-routing slice that triggered this), 11_CODING §25 (size lints, no negotiating)

---

## Context

Implementing ADR-036 D4's deferred read-pool query-routing slice — `_build_query_handlers`, `_build_query_project_cluster_handlers`, and the async `_dispatch_query` orchestration — pushed `composition.py` past two hard size-lint limits at once: the file itself (851 lines, hard limit 800) and, independently, two functions (`_build_core_locked` at 81 lines, `serve` at 88 lines, both hard limit 80) grew past their own limits from the new wiring and routing logic each needed. This is ADR-023's exact scenario one slice later: that ADR's own text named the risk explicitly — "a third file would need its own line, its own justification, same as this one needed this ADR."

The obstacle is the same one ADR-023 resolved: `composition.py`'s own docstring states the import-matrix exemption letting it import both `adapters/` and `api/` is registered by exact name in `tools/importlinter.toml`, "MUST NOT spread" beyond the named files. The query-routing code genuinely needs both — it constructs `Sqlite*Store` instances per call (`adapters.sqlite.*`) and calls `Dispatcher`'s new phase methods (`api.dispatch`) — so moving it to its own file requires extending the exemption again, the same way ADR-023 did for `scheduler_wiring.py`.

A pre-existing gap surfaced while investigating this: `17_PROJECT_STRUCTURE.md` §4.3's composition-root-exception paragraph still read "Exactly one module... It is the only file in `src/` exempt" — ADR-023 never actually updated that prose (only `composition.py`'s own docstring and `tools/importlinter.toml` were updated at the time, despite `17_PROJECT_STRUCTURE.md` being listed as an affected document). Left uncorrected, this ADR would have made the doc doubly wrong. Fixed here, in the same PR, alongside this ADR's own change (14_CLAUDE §6: behavior changes update docs in the same PR — the doc was already behind before this change, so bringing it current is this change's own obligation, not a separate one).

## Decision

**Extend the exemption, deliberately, to a third file that is the same role, not a third role.** `kang.kernel.runtime.query_routing` is not a new kind of module — it is the composition root's own read-pool-routing concern, split out for the identical mechanical reason as `scheduler_wiring.py` (the size lint), containing exactly the same class of code the exemption was written for: plain construction, concretions meeting interfaces, zero domain logic — the pipeline STEPS it orchestrates are defined in `api/dispatch.py`'s `Dispatcher.prepare_query`/`run_query_handler`/`finish_query`/`fail_query`, not redefined here; this module only threads them across `WriteExecutor`/`ReadPool`.

`composition.py` keeps `build_core`, `serve`, `Core`, `_build_handlers` (commands + `system.health`), and store/bus wiring; `query_routing.py` gets the query-specific slice: `_build_query_handlers`, `_build_query_project_cluster_handlers`, `_dispatch_query`. `composition.py` calls into it exactly as it called its own private functions before — the public seam (`build_core`, `serve`) is unchanged, per ADR-023's own precedent.

`tools/importlinter.toml`'s `ignore_imports` gains two lines mirroring the existing pairs exactly, naming the new module instead of adding a wildcard or loosening the rule's shape:
```
"kang.kernel.runtime.query_routing -> kang.adapters.**",
"kang.kernel.runtime.query_routing -> kang.api.**",
```

`pyproject.toml`'s `[tool.ruff.lint.per-file-ignores]` gains a `BLE001` exemption for `query_routing.py` specifically (not `composition.py`, which needs none): `_dispatch_query` is the identical API-006 ingress supervision point `dispatch.py`'s own `dispatch()` already carries the exemption for — it exists only because a read-pool-routed query dispatch cannot be `dispatch()`'s single atomic call without defeating the read pool's purpose, and it converts every failure to the identical envelope via `Dispatcher.error_envelope`.

**What this is not:** not a general loosening ("composition-root-like files may import freely") — the contract still names exact modules, not a pattern. A fourth file would need its own line, its own justification, same as this one needed this ADR (and the same as ADR-023's own text said about this one).

## Consequences

- `composition.py` returns to real headroom under both size limits (704 lines after the split; `_build_core_locked` and `serve` both comfortably under 80 lines), not another same-file trim.
- Three files now carry the composition-root exemption instead of two — a real, named increase in the "MUST NOT spread" surface, accepted for the same reason ADR-023 accepted the second: the alternative (an unbounded single file, or a same-file trim that hits the wall again on the next slice) is worse, per 11 §25's own "split the unit" answer to a lint failure.
- `17_PROJECT_STRUCTURE.md` §4.3's composition-root-exception paragraph now names all three files and states the actual current count, correcting the staleness ADR-023 left behind rather than perpetuating it.
- Future read-pool-routing growth (a query operation ADR-036 D4's own deferred `system.health` gap eventually resolves, say) grows `query_routing.py`, not `composition.py` — the size pressure moves to the file that actually owns that growth.

## Verification

A pure code-organization change, same as ADR-023's own — no behavior to live-verify beyond what ADR-036 D4's own live verification already covers (this ADR carries no behavior change of its own; see ADR-036 D4's "resumed" note for the read-pool routing's own live-verification proof). Confirmed: `lint-imports --config tools/importlinter.toml` reports all 8 contracts kept, including the two new `query_routing` exemption lines; `ruff check .` passes with 0 errors (including the relocated `BLE001` exemption); `tools/lint_sizes.py` reports 0 hard violations (down from 3 before the split: the file itself, `_build_core_locked`, and `serve`); the full backend suite (920 tests) passes unchanged.
