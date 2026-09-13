# ADR-033 — `system.health` exposes backup age + last restore-verification result

**Status:** accepted (2026-09-13)
**Date:** 2026-09-12
**Supersedes:** none
**Affected documents:** 09_UI §12 (no change — this ADR fulfills it), 12_API §16, `src/kang/api/operations/system_ops.py`
**Cites:** 09_UI §12 (`docs/09_UI_DESIGN.md:180`), `api/schemas/system.py`'s own docstring (which named this exact gap on arrival), ADR-031/032 (the manifest this reads), 12_API API-005 (additive response fields need no ADR by that rule alone — filed anyway; see Context)
**Related:** [[031-daily-backup-job.md]], [[032-backup-verify-job.md]] — both D3-style deferred this, ADR-031 naming the trigger directly: *"system.health gains the backup-age field it currently and honestly omits"*

---

## Context

`system.health`'s own response schema docstring named this gap the day it was built, 2026-08-05, before `backup.snapshot`/`.verify` existed to fill it:

> "Backup age, restore-verification, index parity, and the integrity-incident counter are NOT in this response — no port/store exposes them yet... Named as a real, open gap, not silently completed."

09_UI §12 is the normative source: *"job statuses, backup age + last restore-verification result, index parity, integrity-incident counter."* Two of those four now have a real source — `backups/manifest.jsonl` (ADR-031/032) — and two do not (index parity is a search/FTS concern, unbuilt; the integrity-incident counter is 10_SECURITY's incident framework, unbuilt). This ADR closes exactly the two that are ready, and states plainly that the other two remain the same honestly-named gap `system.health` already carries.

**Why an ADR for what API-005 already allows without one.** Additive response fields need no ADR by API-005's own rule. Filed anyway because implementing this raised one real interpretive question and surfaced one real finding, both worth a decision on record rather than a silent implementation choice — the same standard ADR-031/032 held themselves to for smaller gaps than this.

### The interpretive question: raw timestamp or precomputed age

"Backup age" could mean a precomputed duration (`"3d 4h"`) or a raw timestamp the client ages itself. **Every other timestamp this API serves is raw** — `task.created_at`, `deadline.at`, `SnapshotRecord.taken_at` itself — and none is ever pre-aged server-side. Precomputing would also give this one field a clock dependency (`w.clock`) that every sibling field in `SystemHealthResponse` lacks, for a computation the client must already do for every other timestamp it renders. **Decision: raw timestamps, client computes age** — `last_snapshot_at`/`last_verify_at`, both `str | None`, plus `last_verify_ok: bool | None` for the result half of "last restore-verification result." Consistent with the existing vocabulary rather than inventing a duration type.

### The finding: `manifest.jsonl` has no rotation, unlike every other append-only log in this system

Reading it to answer "what's the latest entry" means reading the whole file. SEC-013's audit log — the closest precedent, also append-only — rotates monthly (`audit/YYYY-MM.jsonl`) specifically so no single file grows unbounded. `manifest.jsonl` does not: ADR-031's `_prune()` removes old snapshot **files**, never manifest **lines**. At current cadence (2-3 lines/day) this is genuinely negligible for years — but it is an unbounded growth with no stated retention, which every other durable log in this system was given deliberately. **Not fixed here** — rotating an already-shipped file format is a bigger, separate decision (a live format change, not an additive read) — but recorded as a RESERVED item with a real trigger rather than left for a future session to rediscover from scratch.

---

## Decision

### D1 — `SystemHealthResponse` gains three fields, read from the manifest

```python
last_snapshot_at: str | None   # most recent "kind": "snapshot" line's taken_at
last_verify_at: str | None     # most recent "kind": "verify" line's verified_at
last_verify_ok: bool | None    # that same line's integrity_ok AND read_shapes_ok;
                                #   None only when no verify has ever run
```

`last_verify_ok` is `integrity_ok AND (not read_shape_errors)`, not `integrity_ok` alone — a verify run with a clean integrity check but a broken read shape (D1's own `read_shape_errors`, ADR-032) is still a failed restore-test by 07 Part XII.3's own standard ("every view returns"), and reporting only `integrity_ok` would silently drop that half of the finding.

### D2 — `BackupService` gains one new, read-only method: `latest_status()`

```python
def latest_status(self) -> BackupStatus:
    """The most recent snapshot and verify entries from the manifest, or
    None for either that has never run. Pure read — opens no `kang.db`
    connection, touches nothing, never raises (a missing manifest means
    no backup has ever run, not an error)."""
```

Reads `backups/manifest.jsonl` linearly, keeping the last-seen line of each `kind`. No index, no cache — matching the "boring by construction" standard this codebase already applies to a table this size (ADR-031's own "at today's scale... effectively instantaneous" reasoning extends here identically).

### D3 — `make_system_health_handler` takes `backups: BackupService`

Composition wiring adds one argument, following exactly how `backup.snapshot`/`.verify`'s own handlers were threaded through `_HandlerWiring` in ADR-031.

### D4 — RESERVED: manifest rotation

Recorded in `03_ROADMAP §8`. Trigger: `manifest.jsonl` measurably exceeds a size where a linear scan is no longer "effectively instantaneous" — the same scale-triggered honesty ADR-031 already applied to product-state gating, not a number invented now for a file currently measured in kilobytes.

---

## Consequences

- **`system.health`'s own docstring narrows to two remaining gaps** (index parity, integrity-incident counter) instead of four — each still needs the port/store that would back it before it can be exposed, unchanged from today.
- **No new operation, no new scope, no authority change** — `system.health`'s existing `system.read` scope (ADR-027) already covers the wider response; nothing here required about who may call it.
- **What gets harder:** nothing structural — fourth read-only extension of an existing operation this session, same shape as `deadline.list`/`audit.list`'s own precedent that `system.health`'s docstring already named as the pattern to follow.
- **Explicitly not decided here:** manifest rotation's actual shape (RESERVED, D4) and the two still-missing metrics (index parity, integrity-incident counter) — both remain open, named gaps, not silently folded into "Health complete."

---

## Live verification (2026-09-12)

Against a real, throwaway `%KANG_HOME%` (never the real one): booted a real Core, drove every step through the real dispatcher (`ApiRequest` + idempotency keys, API-004) rather than reaching into privates.

1. `system.health` before any backup ever ran: `last_snapshot_at`/`last_verify_at`/`last_verify_ok` all `null` — the "nothing yet" state.
2. `backup.snapshot` — real snapshot taken, `manifest.jsonl` gets its first `"kind": "snapshot"` line.
3. `system.health` again: `last_snapshot_at` now populated with the snapshot's real `taken_at`; `last_verify_at`/`last_verify_ok` still both `null` — the two-different-"nothing-yet"-states distinction (D1) holding in practice, not just in the schema docstring.
4. `backup.verify` — real restore test against the snapshot just taken: `integrity_ok: true`, `read_shape_errors: []`, second manifest line with `"kind": "verify"`.
5. `system.health` again: `last_snapshot_at` unchanged, `last_verify_at` populated with the verify's real `verified_at`, `last_verify_ok: true`.
6. Raw `manifest.jsonl` inspected directly: two lines, distinguishable only by `kind`, exactly as ADR-031/032 designed it — `latest_status()` read both correctly with no adapter-specific special-casing.

Process closed, throwaway home deleted, real `%KANG_HOME%` confirmed untouched afterward (no `backups/` directory exists there — it has not restarted onto this code, matching ADR-031/032's own confirmed state).
