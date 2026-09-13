# ADR-031 — KANG has never taken a backup: wiring `backup.snapshot` as a fourth automatic job

**Status:** accepted (2026-09-13)
**Date:** 2026-08-17
**Supersedes:** none
**Affected documents:** 05_AGENTS Appendix E (the scheduling table — a fourth row, with two corrections), 12_API §16 (a new operation), `config/defaults/permissions.toml`, `src/kang/kernel/runtime/scheduler_wiring.py`
**Cites:** 07_DATABASE Part XII (`docs/07_DATABASE.md:714-726`), 05_AGENTS Appendix E (`:179`) and Appendix A (`:116`), 12_API `:201`, `adapters/sqlite/backup.py:9`
**Related:** [[022-held-action-expiry-sweep.md]] — the same finding shape (a built, tested mechanism with zero callers), and the pattern this ADR applies; [[030-o1-execution-model.md]] — which surfaced the expired-milestone-promise class this belongs to

---

## Context

**`kang.db` has never been backed up automatically. The mechanism has existed and been tested since M1.**

`adapters/sqlite/backup.py` provides `integrity_check` and `vacuum_into` — the latter already gating on integrity before it will write a snapshot ("a suspect database is frozen, not archived"). Five tests cover them (`integration/sqlite/test_backup.py`), and `suites/backup_restore/test_restore_drill.py` proves the full C1 restore drill. **Neither function has a single caller in `src/`.**

The module says what was supposed to happen, in its own header (`:9`):

> "The scheduled daily job (02:30) arrives with the scheduler at M3; these are its mechanisms."

The scheduler shipped at M3 (ADR-006). It registers three jobs — `morning_plan`, `deadline_sweep`, `held_action_expire` — and backup is not among them. This is the same shape as ADR-022's finding (`expire_due()`: fully implemented, fully tested, zero callers, promised to a milestone that passed), found the same way, and it was surfaced by ADR-030's closing note asking whether other in-code milestone promises had expired the same way. **This is the second confirmed one.** Unlike the first, this one is data protection.

`system.health` is at least honest about the gap rather than reporting a fiction: `api/schemas/system.py:8-12` explicitly records that backup age is **not** in its response because "no port/store exposes them yet."

### The vocabulary already exists — this ADR invents none

- **`backup.snapshot_now`** — 12_API `:201`, listed with `restore.run {snapshot}` as "(consequential; freeze-aware)". The *manual* trigger.
- **`backup.snapshot` / `verify`** — 05_AGENTS Appendix E `:179`: `| backup.snapshot / verify | daily / monthly | Sleeping | run_all_missed |`. The *scheduled* pair.
- **`backup_monitor`** — 05_AGENTS Appendix A `:116`, a **mechanical** agent owning "Snapshot execution + verification (07_DATABASE Part 12)", with "alert on any failure — **no silent skip, ever**".

07_DATABASE Part XII specifies the policy in full: daily 02:30 snapshot → `integrity_check` → `VACUUM INTO backups/daily/kang-YYYYMMDD.db` → record in `backups/manifest.jsonl` (size, duration, integrity result, schema_version); retention 30 daily + 12 monthly (first snapshot of each month promoted); event log and audit files included in the daily job (audit: current-month file copy; eventlog: its own `VACUUM INTO`).

---

## Two spec details that do not survive contact with the code

Named here rather than silently implemented or silently ignored.

**1. Appendix E's `run_all_missed` is wrong for a snapshot job.** Every other catch-up policy choice in this system has been reasoned about (`deadline_sweep` and `held_action_expire` both take `run_once_latest` because replaying a missed slot recomputes an identical result). A snapshot after five days of downtime would, under `run_all_missed`, produce **five snapshots of the same current database** under five different dates — five copies of identical content, four of them lying about what the system looked like on those days, consuming five times the disk. `run_once_latest` is correct: take one snapshot now, and let the manifest record honestly that days were missed.

**This ADR uses `run_once_latest` and amends Appendix E**, rather than implementing a spec line whose consequence appears unconsidered. Flagged prominently because overriding a normative table is exactly the thing that should never be quiet.

**2. Appendix E's "Sleeping" product state cannot be honored — product state does not exist in code.** `Job` carries `id`/`name`/`schedule`/`catch_up`/`created_at`/`enabled`/`timeout_s`/`quarantined` (`domain/ports/scheduler.py:33-43`) and nothing about product state; grep finds it only in comments acknowledging its absence (`notification_service.py:44` "assuming the most permissive product state"; `scheduler_wiring.py:221` "any product state"). For `deadline_sweep` that was harmless — its Appendix E cell says "any product state." For backup it is a real deferral: a `VACUUM INTO` at 10-year scale (07 Part XII targets < 60 s for ≤15 GB) is I/O-heavy and genuinely should not run mid-use.

**Accepted as a stated limit, not papered over:** at today's scale (`kang.db` is ~290 KB) the snapshot is effectively instantaneous and the distinction is academic. It stops being academic well before 15 GB. Recorded as a RESERVED trigger rather than pretended-away.

---

## Decision

### D1 — Register `backup.snapshot` and wire it as a fourth automatic job

Following ADR-020/ADR-022's established pattern exactly: an operation, a `Job` row, a scope, a grant on `kernel:scheduler`.

- **Operation** `backup.snapshot`, `kind="command"`, no request fields, response `{snapshot, bytes, duration_ms, integrity_ok}`. Scope `backups.write` (new). Not `first_party_only` — routine automated maintenance, like `deadline.sweep`. **No `commit_mode`:** it touches no `kang.db` state, so it is not consequential in ADR-001's sense.
- **Job** `id="backup_snapshot"`, `schedule="daily"`, `catch_up="run_once_latest"` (per correction 1), `timeout_s=120` — Part XII's own "< 60 s at 10-year size" target, doubled, matching how `deadline_sweep` took Appendix A's named figure rather than inventing one.
- **Grant** `"kernel:scheduler" = [..., "backups.write"]`, the same shape ADR-020 and ADR-022 each added one in.

### D2 — What the job actually does

1. `integrity_check` on `kang.db`; on failure **raise**, never snapshot suspect state (Part XV F1 — `vacuum_into` already enforces this internally).
2. `VACUUM INTO backups/daily/kang-YYYYMMDD.db`.
3. `VACUUM INTO backups/daily/eventlog-YYYYMMDD.db` — the event log gets its own snapshot per Part XII. **Not optional:** DB-001's durability pairing restores by replaying the event log for post-snapshot Tier-1 effects, so a kang.db snapshot without its event log is a restore that silently loses the recovery window.
4. Copy the current-month audit file (`audit/YYYY-MM.jsonl`).
5. Append one line to `backups/manifest.jsonl`: date, paths, sizes, duration, integrity result, `schema_version`.
6. Prune: keep the newest 30 daily; promote the first snapshot of each month to `backups/monthly/`; keep the newest 12 monthly.

### D3 — Deferred, each with a trigger

- **`backup.verify` — the monthly restore test (D016).** Deferred to its own ADR: it is a second job with materially different mechanics (open a snapshot read-only, run the named-query suite against it, row-count sanity vs. live). **Trigger: immediately after D1 lands** — see the honesty note below, because this one is not a comfortable deferral. **Closed: [[032-backup-verify-job.md]] (2026-09-11).**
- **`restore.run` / `backup.snapshot_now`** — both consequential (12_API `:201`), so both need the ADR-021 held-action gate. Trigger: a UI surface that offers them, or a real restore need.
- **Single-record restore** (Memory §7.2) — Phase 2, with the memory browser.
- **Off-machine backup warning** (Part XII.5) — trigger: `system.health` gains the backup-age field it currently and honestly omits.
- **Product-state gating** (correction 2) — trigger: product state exists at all, or `kang.db` exceeds ~1 GB, whichever is first.
- **The `backup_monitor` agent** (Appendix A) — M7. This ADR wires the job directly to the operation, exactly as ADR-020/022 did; the agent is the later shape that would own it, and "alert on any failure — no silent skip, ever" is already satisfied in the interim by the scheduler's existing failure→quarantine path plus `job.overrun` auditing.

### The honesty note this ADR must not omit

07_DATABASE Part XII.3 is unambiguous:

> "**A backup that hasn't been restore-tested is treated as nonexistent.**"

By the constitution's own standard, **D1 alone does not give KANG backups.** It gives KANG snapshots that are taken, recorded, and pruned. That is strictly better than the current state of nothing, and it is a prerequisite for the verification job — but until `backup.verify` lands, no document, health panel, or session summary may claim KANG "has backups." **`backup.verify` landed 2026-09-11 ([[032-backup-verify-job.md]]) — this caveat is now historical, kept for the record of why D1 alone was insufficient.** Stated here so the next reader inherits the caveat with the capability, and so D3's first item is understood as a debt with a date, not a nice-to-have.

---

## Consequences

- **The second expired milestone promise is closed** (`backup.py:9`, "arrives with the scheduler at M3"). ADR-030 found the first (`connection.py:6`, the write-executor and read pool). A systematic sweep of the remaining in-code milestone promises is not done here — recorded as worth its own pass.
- **05_AGENTS Appendix E gains a row and two corrections** (`run_once_latest` over `run_all_missed`; "Sleeping" recorded as unbuildable-today rather than silently dropped).
- **A `backups/` tree appears under `%KANG_HOME%`** — `daily/`, `monthly/`, `manifest.jsonl`. New convention, matching Part XII's own paths.
- **What gets harder:** nothing structural — this is the fourth instance of the job→operation pattern, and the first three each made the next one cheaper.
- **Explicitly not claimed:** that this makes the data safe. See the honesty note.

---

## Live verification (2026-08-17)

Against a real, throwaway `%KANG_HOME%` (never the real one), a real
`python -m kang.kernel.runtime.composition` process:

- Registered the four jobs, backdated `backup_snapshot` by 3 days, booted.
- Boot catch-up ran it once — `job_run` shows `outcome='ok'`.
- `backups/daily/` holds all three artefacts: `kang-20260831.db` (221 KB),
  `eventlog-20260831.db` (41 KB), `audit-20260831.jsonl` (1.1 KB).
- `backups/monthly/kang-202608.db` — the first-of-month promotion fired.
- One `manifest.jsonl` line, `"integrity_ok": true`, `"schema_version": 17`,
  `"pruned": []`.
- **The snapshot is genuinely restorable, not merely present**: reopened
  directly, `PRAGMA integrity_check` returns `ok`, `schema_version` reads
  17, and `task`/`held_action`/`job`/`schema_version` are all there.
- Process stopped, throwaway home deleted. The real, persistent
  `%KANG_HOME%` was not touched — confirmed by listing it afterwards
  (still no `backups/` directory, because the real Core has not yet been
  restarted onto this code).

Proven automatically too, on every run:
`suites/replay/test_boot_catchup.py::test_backup_snapshot_is_registered_and_a_real_boot_takes_a_real_snapshot`
runs the same shape and additionally asserts that two days of downtime
yield exactly ONE snapshot — the `run_once_latest` correction, tested
rather than asserted.
