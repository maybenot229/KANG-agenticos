# ADR-032 — `backup.verify`: closing the "nonexistent until restore-tested" gap ADR-031 left open

**Status:** proposed
**Date:** 2026-09-11
**Supersedes:** none
**Affected documents:** 07_DATABASE Part XII.3 (two interpretive decisions on underspecified terms — see Decision), 12_API §16, `config/defaults/permissions.toml`, `src/kang/kernel/runtime/scheduler_wiring.py`
**Cites:** 07_DATABASE Part XII.3 (`docs/07_DATABASE.md:721`), §4.1 (`:152` — the four named views), ADR-031 D3 (this job's own deferral, "trigger: immediately after D1 lands"), ADR-013 (analogy-picking creates implicit commitments — cited against inventing a churn tolerance by feel)
**Related:** [[031-daily-backup-job.md]] — D1 shipped; this is D3's first item, the one ADR-031 itself called "not a comfortable deferral"

---

## Context

07_DATABASE Part XII.3 is the reason ADR-031's D1 alone was not enough:

> "A backup that hasn't been restore-tested is treated as nonexistent."

Its own spec: "open latest snapshot read-only → `integrity_check` → run the *named-query suite* against it (every view returns, plans don't regress) → row-count sanity vs. live (±expected churn) → write result to manifest + health panel."

**Two of its terms have no referent in code, checked rather than assumed — the same discipline ADR-031 applied to `run_all_missed` and "Sleeping".**

### 1. "The named-query suite" does not exist, and half its subjects don't either

§4.1 names four views as "the sanctioned read shapes": `v_active_deadlines`, `v_today_tasks`, `v_project_memory`, `v_contested_records`. None is a real `CREATE VIEW` — grepping every migration finds zero. Two are real anyway, as store methods the code already cites as that exact read shape:

- `DeadlineStore.active()` — its own docstring: *"the `v_active_deadlines` read shape (07 §4.1)."*
- `TaskStore.plannable()` — its own docstring: *"07 Part VI's `v_today_tasks` read shape."*

The other two have no implementation of any kind. `domain/memory/` is `__all__: list[str] = []`, header: *"built at Phase 2."* `v_project_memory` and `v_contested_records` are Memory's read shapes; Memory does not exist yet.

### 2. "±expected churn" has no number anywhere

Grepped every doc for "churn": three unrelated hits (embedding-model churn, provider churn, decade-scale model churn) and this one line, which never defines its own tolerance. Inventing one — 5%? 10%? — would be fabricating a threshold the constitution never set, the exact thing rule 8.6 forbids ("if you did not run it, you do not report it... if you do not know, say so").

### 3. "monthly" is not a schedule literal

`kernel/scheduler/schedule.py`'s interval parser supports exactly `every:{s}`, `daily`, `hourly`, `minutely` — no `monthly`. The full 5-field cron dialect (`adapters/scheduler/cron.py`) does support day-of-month, and is already load-bearing for `morning_plan`'s own wall-clock trigger, using the timezone `kang.toml` already provides. No new dependency: `_wire_scheduler` already fails closed to no automation at all when `kang.toml` is missing, regardless of which dialect a job uses — the three existing interval-form jobs already require it via that same all-or-nothing gate, not per-job.

---

## Decision

### D1 — The named-query suite is the two read shapes that actually exist today

`backup.verify` calls `DeadlineStore.active()` and `TaskStore.plannable()` against a connection opened on the restored snapshot, and reports whether each raised. This is not a substitute invented to paper over the gap — it is the literal, already-cited implementation of two of the four named views. `v_project_memory`/`v_contested_records` are excluded, not silently skipped: the result names them absent and why, so a reader sees `2/4 checked`, never `passed`.

**RESERVED, not built:** the other two, trigger = Memory ships (Phase 2) and its own read shapes exist to call.

### D2 — Row counts are reported, never gated

`backup.verify` returns `live_row_counts`/`snapshot_row_counts` for a fixed, named table set (`task`, `deadline`, `held_action`, `job`, `project`, `competition`, `milestone`, `goal`, `notification` — every table `_Stores` already wires, excluding `session`/`idempotency_key`/`schema_version`, which measure nothing about churn). **No pass/fail threshold is applied to the difference.** A verify run cannot fail on row-count drift, because there is no constitutional number to fail it against — only `integrity_ok` and `read_shapes_ok` (D1) determine the run's own status. Whoever specifies a real tolerance amends Part XII.3 with an actual number; this ADR does not guess one on their behalf.

### D3 — `backup_verify` as a fifth automatic job

Following ADR-020/022/031's pattern:

- **Operation** `backup.verify`, `kind="command"`, no request fields. Scope `backups.write` — reused, not a new `backups.verify`: this operation also appends to `manifest.jsonl`, the same file `backup.snapshot` writes, and ADR-031 already established `backups.write` as the family's scope for "does something to the backups directory," not "took the snapshot" specifically.
- **Job** `id="backup_verify"`, `schedule="cron:0 3 1 * *"` (03:00, 1st of the month — after that day's 02:30 daily snapshot has already run, per correction 3), `catch_up="run_once_latest"` (a missed verify, once caught up, need not replay every missed month — the latest snapshot is what there is to check), `timeout_s=120` (Part XII's own restore-test target is "< 5 min"; 120s matches `backup_snapshot`'s own margin below that, not a fresh number).
- **Grant** — no `permissions.toml` change: `backups.write` is already granted to `kernel:scheduler` by ADR-031.

### D4 — Refuses only when there is nothing to verify

Unlike `take_snapshot` (which refuses to *write* suspect state), `verify_latest` **does not raise on a failed check** — a corrupted snapshot or a broken read shape is exactly the finding this job exists to surface, and 05_AGENTS Appendix A is explicit: "alert on any failure — no silent skip, ever." It raises `BackupError` only when no daily snapshot exists to open at all — a distinct condition (nothing to check) from a bad result (checked and failed).

---

## Consequences

- **ADR-031 D3's flagged item is closed.** Snapshots taken since ADR-031 landed are now restore-tested, monthly, automatically.
- **Two more underspecified spec terms are resolved and recorded**, rather than each future session re-deriving or, worse, silently guessing differently each time.
- **`system.health` integration remains deferred** — ADR-031 D3 already named this as its own trigger ("system.health gains the backup-age field it currently and honestly omits"); this ADR does not pull it forward.
- **What gets harder:** nothing structural — fifth instance of the job→operation pattern.
- **Explicitly not claimed:** that row-count reporting catches meaningful drift. Without a defined tolerance it is a number for a human to read, not a gate a machine enforces.

---

## Live verification (2026-09-11)

Against a real, throwaway `%KANG_HOME%` (never the real one): seeded a real daily snapshot via `take_snapshot`, backdated the `backup_verify` job by 40 days, booted a real Core. Boot catch-up ran verify once (`job_run.outcome='ok'`); the returned record showed `integrity_ok=True`, `read_shapes_ok=True`, both live/snapshot row counts populated and equal (no writes occurred between snapshot and verify), `schema_version` matching, and one new `manifest.jsonl` line distinguishable from the snapshot's own by its `"kind": "verify"` field. Manifest carried both the real seeded `snapshot` line and the new `verify` line in the same file, distinguishable by `kind`: `integrity_ok: true`, `read_shapes_checked: ["v_active_deadlines", "v_today_tasks"]`, `read_shape_errors: []`, `read_shapes_not_built: ["v_project_memory", "v_contested_records"]`, `live_row_counts`/`snapshot_row_counts` identical (no writes occurred between snapshot and verify — `job: 5`, every other table 0), `schema_version: 17`. `job_run` for `backup_verify` shows `outcome='ok'`.

Process stopped, throwaway home deleted, real `%KANG_HOME%` confirmed untouched afterward (no `backups/` directory exists there — it has not restarted onto this code).
