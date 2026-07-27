# Session handoff — 2026-07-27

**Status:** non-normative orientation document (17 §12 — guides are never
binding law). Read this to get oriented in under two minutes, then read the
things it cites. It deliberately does **not** restate ADR or CLAIMS content.

---

## 1. Milestone state — M0–M5 complete

M5 ("The deterministic secretary", 18 §3) delivered:

- **Domain areas** — `deadlines` end to end (port, service, sqlite + fake
  stores, contract suite). Migration `0006` created `goal`, `project`,
  `milestone`, `competition`, `deadline`, which 07 §5.2 had documented since
  Phase 0 but which had **never been migrated**; it also paid `0001`'s
  deferred `task.project_id` FK.
- **The deterministic Planner** (`domain/planner/`) — pure, zero I/O, zero
  model calls. This is the release-blocking degradation floor (05 §16), built
  before any model exists to fall back from (18 §7.6).
- **Notification queue + ladder + notifier** — migration `0007`,
  `domain/notifications/`. The notifier lives in `domain/` (17 §2's stated
  home) and is wired as a bus subscriber at the composition root, so no
  `kernel/notifier` package was added.
- **Calendar-read stub** — migration `0008` (`calendar_cache`, also never
  previously migrated). Read-only by design; calendar *write* is v0.2 and
  consequential.
- **Scheduler joined the Core**, `morning_plan` registered as the first real
  job row, using cron-list schedules built from
  `config/defaults/kang.toml` — 05:45 Mon–Sat, 06:45 Sun, `Asia/Kuching`.
  Saturday is a school day; the week has **seven** planned mornings.

Trigger times are config, not code (05 Appendix E). Editing `kang.toml`
changes the schedule; nothing is hardcoded.

## 2. ADRs filed this session

All in `docs/adr/`; the index is `docs/adr/INDEX.md`.

| ADR | Decided |
|---|---|
| 001 | Held-action lifecycle: `approved` ≠ done; adds `executed`; split `commit_mode` (`transactional` \| `redrive`) chosen at registration |
| 002 | The approval channel: `first_party_only` is a per-operation **channel** control, orthogonal to capabilities; distinct `first_party_required` error code |
| 003 | `goal.horizon` does **not** gain `'5yr'` — the 5-year goal stays in the vault until it is a real commitment |
| 004 | Registered five M5 event types; `plan.generated` is **not** recovery-grade (no `plan` table; the plan is derived state) |
| 005 | Notification queue schema — per-device operational state, **no sync quartet**, acks additive |
| 006 | Wall-clock `cron:` schedules behind a Scheduler adapter + the job→operation seam (dispatch as `kernel:scheduler`, `first_party=False`). Amended: missing config **fails closed, not dead** |

## 3. Tests

**330 → 529** over the session. Full suite green; 0 hard lint violations;
citation linter exits 0.

Claim-to-test mapping is `tests/suites/CLAIMS.md` — read that, not this, to
learn what is actually proven.

Two kernel defects were found and fixed by tests during M5, both latent
before any subscriber existed:

- **Bus fan-out was not re-entrant** — a handler that published recursed
  without bound and *hung* the process rather than failing. Fixed with a
  re-entrancy guard plus a drain-until-quiet loop, bounded independently of
  EB-011.2 (`causation_depth(None)` is 0, so the depth guard cannot bound a
  publisher that omits `causation_id`).
- **Notification dedup counted `queued` rows** — two simultaneous enqueues
  would have suppressed *each other*, telling Kang nothing at all.

## 4. Open — in 03_ROADMAP §8's RESERVED registry

Three deliberate simplifications, each with a `RESERVED(trigger)` marker at
its site and a registry row, so they surface at every version-boundary
review (03 §9) rather than calcifying silently:

1. **Same-day-deadline `critical` threshold.** 05 §13 names "deadline in
   danger *today*" but never defines it. Everything approaching is
   `attention`. **Kang's call — a product decision, not a code one.**
2. **24h no-re-notification "unchanged item".** Implemented narrowly as
   same-entity-refs + same-priority. Errs toward over-notifying on purpose:
   a false delivery is annoying, a false suppression loses a deadline.
   Needs real volume, then an ADR.
3. **Product-state gating.** The ladder assumes state == `Idle` (the most
   permissive row of 09_UI §9's table). Waits on M6's product-state machine.

## 5. Next — M6, "Kang can see it"

Per 18 §3: the dashboard (four constitutional zones, palette navigation,
quick capture, permission screen, the unique confirm dialog — 09_UI), the
Tauri shell, UI built on the generated client only.

Gate: client contract tests (unknown-field tolerance), UI render-tree
snapshots (13 §2.6), zero non-client imports.

Note the pre-committed spike (18 §8.5 / 04 §20): **Tauri global-hotkey and
tray behaviour on Windows 11 must be spiked before M6 commits**, and the
spike's output is a decision, not code.

## 6. Known gaps not fixed

- **`job.timeout_s` is not enforced.** The column exists and `Scheduler`
  calls the runner synchronously, so a hung job hangs catch-up. Pre-existing
  (M3 scope), flagged in ADR-006, **not** introduced by this session. Needs
  the supervised-task machinery D014 names.
- **`app_state` vs `setting`** — `07_DATABASE.md` §5.5 says `setting`;
  `migrations/0003_scheduler.sql` and `job_store.py` create and query
  `app_state`. Docs and code disagree. Found early in this session, still
  unreconciled, and it will bite whichever milestone next touches that table.
- **The unlock-detection spike never ran.** `afterschool_mode = "event"`
  sits in `kang.toml` with no implementation; only the `17:00` fallback and
  the manual path are proven. Bounded to one day per the intake's own
  instruction; if it costs more, ship the fallback.
