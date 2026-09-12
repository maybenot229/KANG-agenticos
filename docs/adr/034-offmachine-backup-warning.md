# ADR-034 — the off-machine backup warning (07 Part XII.5)

**Status:** proposed
**Date:** 2026-09-13
**Supersedes:** none
**Affected documents:** 07_DATABASE Part XII.5 (implements it; no change), 09_UI §12 (a doc gap surfaced, not fixed — see Context), 15_EVENT_BUS §6.1 (registers `backup.offsite_stale`), 05_AGENTS Appendix E (a job this table does not itemize — a second gap surfaced), 12_API §16, `config/defaults/{kang,permissions}.toml`
**Cites:** 07_DATABASE Part XII.5 (`docs/07_DATABASE.md:718`), 09_UI §12 (`docs/09_UI_DESIGN.md:180`), ADR-033 (the raw-timestamp precedent this extends), ADR-031/032 (the job-wiring and scope-reuse precedent this follows)
**Related:** [[033-system-health-backup-status.md]] — backup age now lives in `system.health`; this ADR adds the fifth Health signal that field's own precedent didn't cover

---

## Context

07_DATABASE Part XII.5, in full:

> "**Off-machine:** KANG's own duty ends at `backups/`; the health panel warns (weekly) if `%KANG_HOME%` shows no evidence of external backup (last-backup-age heuristic on a Kang-configured marker). KANG cannot force this; it can refuse to let it be forgotten."

Nothing in `src/` reads or writes any such marker. `backups/manifest.jsonl` (ADR-031/032/033) records KANG's own on-machine snapshots — it says nothing about what Kang did with them afterward, which is the entire point of Part XII.5's mechanism existing separately.

### Finding: 09_UI §12 enumerates four Health fields, and this is a fifth

09_UI §12's own list: *"job statuses, backup age + last restore-verification result, index parity, integrity-incident counter."* Off-machine backup evidence is not among them, yet Part XII.5 explicitly assigns the health panel the job of warning about it. This is not a contradiction — 09_UI's list and Part XII.5's mechanism don't disagree, they're just never cross-referenced — but it means 09_UI §12 is silent on a responsibility Part XII.5 gives its own panel. Recorded here rather than silently patched over; resolution below is to treat this as the panel's fifth field, consistent with Part XII.5's own words, not to shoehorn it into "backup age" (a different question: how old is KANG's *own* copy, vs. whether Kang has ever moved a copy off this machine).

### Finding: 05_AGENTS Appendix E does not itemize a job for this either

Appendix E's scheduling table (`docs/05_AGENTS.md:477`) lists `backup.snapshot / verify` and nothing else in the backup family. `health.tick` (5m, "any" state, `skip`) is the closest named row, but it belongs to the unbuilt `health_monitor` agent's general "metrics collection; threshold alerts" mandate — no `health.tick` job, no `health_monitor` wiring, and no other Health field is driven by a periodic tick today (`system.health`'s existing fields are all computed live, per request, not batch-updated). Building the general `health_monitor`/`health.tick` framework now, to host one check, would be exactly the speculative, oversized seam the smell checklist warns against ("a diff that touches many layers for a small feature"). **Decision: a narrowly-named job, `backup_offsite_check`, in the same family as `backup_snapshot`/`backup_verify`, not a general health-tick framework.** This is a second gap in Appendix E worth a line, not a blocker — the same category of finding ADR-031 recorded for `run_all_missed` and "Sleeping," and ADR-032 recorded for "monthly" having no scheduler dialect.

---

## Decision

### D1 — The marker is a Kang-configured file path; its mtime is the evidence

`[backup] external_marker_path` in `kang.toml`, read once at boot. Kang's own off-machine process (an external drive copy, a cloud sync job, anything outside KANG's control — Part XII.5: "KANG's own duty ends at `backups/`") is expected to touch that file each time it completes. The check reads the file's mtime; a missing or unconfigured path reads as "no evidence," not an error — **the honest answer Part XII.5 itself names** ("KANG cannot force this"), not a state this feature is meant to prevent.

**Deliberately tolerant, unlike `kang.toml`'s other config.** `load_planner_triggers` fails the whole scheduler closed on anything wrong with `[planner.triggers]` (07 F8) — correct there, because an invented trigger time is automation firing at a moment nobody chose. This key has the opposite risk profile: an absent or malformed `[backup]` section is itself the correct "stale" reading, and a typo in it must not be able to take down `morning_plan`/`deadline_sweep`/`backup.snapshot` by raising where `_wire_scheduler` can't recover. `load_external_backup_marker` (new, `adapters/config/backup_config.py`) never raises; it returns `None` on anything short of a valid string path.

### D2 — The staleness threshold is 7 days, read directly from Part XII.5's own word

Part XII.5 says "(weekly)" once, describing the panel's warning cadence. Rather than inventing a second, undocumented number for "how old is too old," **the threshold IS that same week** — a marker older than 7 days (or absent entirely) is stale. This is the narrowest reading the text supports: one number, not two, and it is the number the document already wrote down (contrast ADR-032 D2's `±expected churn`, which truly has no number anywhere in the constitution and was deliberately left unset).

### D3 — `BackupService` gains `external_backup_status(now: str) -> ExternalBackupStatus`

```python
@dataclass(frozen=True)
class ExternalBackupStatus:
    last_marker_at: str | None   # the marker file's mtime, raw timestamp
    stale: bool                  # last_marker_at is None, or > 7 days old
```

The marker path is bound at construction (`SqliteBackupService.__init__(..., external_backup_marker=...)`), matching `_root`'s own pattern — not a per-call parameter, since it never changes within a Core's lifetime, exactly like the backups directory itself. `now` stays per-call, matching every other method on this port. A shared pure function, `external_backup_is_stale(last_marker_at, now)`, lives on the port module itself so `SqliteBackupService` and `FakeBackupService` cannot silently disagree about what "stale" means (13 §2.3's fake/real parity).

### D4 — `system.health` gains two fields, computed live, every request

`external_backup_marker_at: str | None`, `external_backup_stale: bool`. Not batch-computed by the weekly job — read fresh on every `system.health` call, exactly like `last_snapshot_at`/`last_verify_at` already are (ADR-033). The weekly job's own cadence governs only how often the *notification* fires, never how current the panel's own number is.

### D5 — `backup_offsite_check`, a fifth backup-family job, weekly, `run_once_latest`

`cron:0 3 * * 0` (Sunday 03:00, the same 3am maintenance slot `backup_verify` already uses monthly). `run_once_latest`: multiple missed weeks catch up to one check of current state, not N redundant reads of the same still-unchanged marker (the same reasoning ADR-031 applied to `backup_snapshot`). Registered operation: `backup.offsite_check`, scope `backups.read` — new, because unlike `backup.snapshot`/`.verify` (which genuinely write files and the manifest), this operation only reads and, when stale, announces; reusing `backups.write` would overstate what it does. Granted to `kernel:scheduler` alongside the existing `backups.write`.

### D6 — Staleness becomes a fact event, `backup.offsite_stale`, only when true

Mirrors `deadline.approaching`'s own shape exactly: `recovery_grade=False` ("a pure fact's whole existence IS the event," EB-008 rule 2), `entity_refs=({"kind": "backup", "id": "offsite"},)` (a stable, logical identity — not a DB-backed entity, but a single named "thing" a de-dup rule and a deep-link can point at, in the same spirit `entity_refs`'s `{kind, id}` shape already allows), `causation_id=None` (a genuine root cause — no accompanying mutation event precedes it, unlike `deadline.approaching`, which follows its own `deadline.updated`). Published under a new domain principal, `kernel:backups` (`events.publish:kang`), matching `kernel:deadlines`/`kernel:tasks`'s own one-line grants. **Not published when the marker is fresh** — no event, no notification, matching Part XII.5's own "warns... if no evidence" framing (silence is the healthy state).

### D7 — A new notifier enqueue handler, priority `attention`

`make_backup_offsite_enqueue_handler`, parallel to `make_deadline_enqueue_handler`, subscribed alongside it in `_wire_notifier` (a second `Subscriber`, not a rewritten shared one — the notifier module's own docstring is explicit that `enqueue_*` is meant to be one function per fact-event, "one seam" per concept). Priority `attention`, the cap 05_AGENTS' `backup_monitor` row already names (`notify≤attention`) — not `critical` (Kang not backing up off-machine is not an emergency the way a deadline "in danger today" is), not `digest`/`silent` (Part XII.5's "refuse to let it be forgotten" asks for something Kang actually sees, not a number buried in a weekly roll-up). The existing 24h de-dup window, combined with a 7-day check cadence, produces exactly the intended behavior with no new logic: a still-stale marker renotifies every week (checks are far enough apart that dedup never suppresses a genuine repeat), while a same-day re-run (e.g., a restart-triggered catch-up) is correctly suppressed as a duplicate.

---

## Consequences

- **09_UI §12's Health panel now has a real fifth field**, alongside the four it names — a doc gap surfaced (see Context), not silently absorbed into "backup age."
- **05_AGENTS Appendix E gains a job row this ADR itemizes but the document itself doesn't yet** — third such gap this backup thread has found (after ADR-031's `run_all_missed`/"Sleeping" and ADR-032's "monthly"), consistent with the pattern of a document written ahead of the code that would exercise it.
- **A new scope (`backups.read`) and a new event type (`backup.offsite_stale`) enter their respective closed registries** — both additive, both following existing family-naming conventions, neither widening what `kang` already holds via `*`.
- **What Kang must still do himself:** configure `[backup] external_marker_path` and point his own off-machine process at it. KANG cannot do this part — Part XII.5 says so directly — and an unconfigured marker will correctly and permanently read `stale=True`, nagging weekly, until he does.
- **Explicitly not decided here:** the general `health_monitor`/`health.tick` framework (05_AGENTS' broader "metrics collection; threshold alerts" mandate) stays unbuilt; this ADR adds one narrowly-scoped job in the existing backup family, not that framework. Index parity and the integrity-incident counter (09_UI §12's other two open gaps) remain untouched.

---

## Live verification (2026-09-13)

Against a real, throwaway `%KANG_HOME%` (never the real one), with a real `[backup] external_marker_path` in `kang.toml` pointing at a real file this script controlled — every step driven through the real dispatcher, never privates:

1. Touched the marker, then booted a real Core. `system.health`: `external_backup_marker_at` populated with the marker's real mtime, `external_backup_stale: false`.
2. `backup.offsite_check` with the fresh marker: `stale: false`, and — the central claim of D6's "silence is the healthy state" — the real `notification` table had **zero** rows afterward.
3. Aged the marker file's mtime to `2026-01-01` (`os.utime`, real file, no clock injection needed since this reads the filesystem directly) — now 8+ months stale, far past the 7-day threshold.
4. `system.health` again: `external_backup_stale: true`, `external_backup_marker_at` reflecting the aged mtime.
5. `backup.offsite_check` again: `stale: true`. The real `notification` table now had exactly one row: `priority='attention'`, `state='delivered'` (Idle-assumed ladder, matching every other `attention` notification today), `payload` carrying `"kind": "backup.offsite_stale"` and the stale marker's own timestamp.
6. Confirmed `backups/manifest.jsonl` was never created by any of this — this check reads a wholly different source (the marker file) and touches nothing ADR-031/032/033 already own.

Also confirmed via the real subprocess replay suite (`tests/suites/replay/test_boot_catchup.py::test_backup_offsite_check_is_registered_and_a_real_boot_warns_when_stale`): a real `serve()` boot, `backup_offsite_check` backdated 10 days, catches up exactly once (`run_once_latest`) against the **shipped, unconfigured** default `kang.toml` — proving the "ships unconfigured, nags honestly" path (D1) end-to-end, not just the configured path exercised above.

Process closed, throwaway home and marker directory deleted, real `%KANG_HOME%` confirmed untouched afterward (no `backups/` directory; `config/kang.toml` carries no `external_marker_path`).
