# ADR-024 — Splitting `held_action.status`'s `cancelled` into `cancelled` | `expired`

**Status:** accepted
**Date:** 2026-08-17
**Supersedes:** none
**Affected documents:** 07_DATABASE §5.5 (schema delta), 12_API §7 ("expiry 24h ⇒ `cancelled`" becomes `expired`), `src/kang/domain/ports/held_action.py`, `src/kang/adapters/sqlite/held_action_store.py`, `src/kang/adapters/fakes/held_action_store.py`, `src/kang/api/operations/held_action_ops.py`
**Cites:** `migrations/0005_held_action_lifecycle.sql` (the table-rebuild pattern this migration follows — SQLite cannot `ALTER` a `CHECK` in place), ADR-021 §Amendments (the append-only amendment pattern this ADR uses on ADR-022, not a rewrite), ADR-022 (the sweep whose write target this ADR changes)
**Related:** [[022-held-action-expiry-sweep.md]] (amended below, not rewritten)

---

## Context

A read-only investigation on 2026-08-16 (this session) established, by grep against real code — not recollection, and re-verified a second time after an earlier report was independently challenged and held up:

- `cancel()` (`held_action_store.py:122-128`) and `expire_due()` (`held_action_store.py:159-172`) write the identical literal `"cancelled"`. No other column distinguishes an explicit Kang decline from an automatic 24h-window expiry.
- This was documented as deliberate, at the time, in `held_action_ops.py`'s cancel-handler docstring (`:141-144`). The premise it was written under no longer holds: when written, `expire_due()` had no scheduled caller, so the expiry path produced zero rows and the collapse cost nothing. ADR-022 (2026-08-13/14) wired the sweep as a real, running third scheduler job. Both events now genuinely occur in the live system.
- The real `%KANG_HOME%` database was queried directly before drafting this ADR (read-only connection, `mode=ro`, no write lock taken): **zero `held_action` rows exist today.** This migration touches no live data in the one environment that matters.

This ADR is scoped to exactly one change — splitting the collapsed terminal state. The originating investigation scoped two further changes alongside it (transition provenance; event publication on transitions); both are filed as **separate ADRs (025, 026)** and are explicitly not built here — see "What this ADR does not do," below.

---

## Decision

### D1 — Split the terminal state

`held_action.status`'s CHECK constraint gains a fifth value:

```sql
status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN
                ('pending','approved','executed','cancelled','expired'))
```

`cancelled` narrows to mean *Kang explicitly declined* (`held_action.cancel {id}` — unchanged: same guard, same target literal). `expired` means *the 24h window closed with no decision* — `expire_due()`'s write target changes from `'cancelled'` to `'expired'`. `expire_due()`'s own guard (`WHERE status = 'pending' AND expires_at <= ?`) is unchanged; only the literal it writes changes.

### Migration shape

Follows `migrations/0005_held_action_lifecycle.sql`'s exact rebuild pattern: `CREATE TABLE held_action_new` with the five-value CHECK, `INSERT INTO held_action_new (<full column list>) SELECT <same> FROM held_action`, `DROP TABLE held_action`, `ALTER TABLE ... RENAME`, recreate `idx_held_action_pending`. One difference from `0005`: the `INSERT`'s column list must name `params` explicitly (added by migration `0015`, after `0005` shipped — `0005`'s own `INSERT` never had to mention it).

**Historical `cancelled` rows are not reclassified.** The real database holds zero rows today, so this is moot in the one environment that matters, but it is not attempted as a matter of design, not merely because there's nothing to do: there is no way to know, retroactively, whether a pre-existing `cancelled` row was a decline or an expiry — resolving that ambiguity going forward is this ADR's whole purpose; it cannot resolve it backward. Any `cancelled` row from before this migration stays `cancelled`, regardless of which event actually produced it. Stated directly in the migration's own SQL comment, not left to be inferred.

### What this ADR does not do (deferred, not overlooked)

- **Transition provenance** (`decided_at`/`decided_by` columns, recording who/when for a transition) — filed as **ADR-025**. Not built here. Requires a `HeldActionStore` Protocol signature change across both adapters and the shared contract-test fixture (`tests/fixtures/held_action_store_contract.py`) — real surface area that does not belong in a one-column `CHECK` split.
- **Event publication** (`held_action.*` registered on the bus, published on transitions) — filed as **ADR-026**. Not built here. Requires restructuring `_approve_transactional`'s existing crash-tested one-transaction shape (`held_action_ops.py:119-131`, closed by a dedicated crash-kill test under ADR-021) around `EventBus.publish`'s event-before-state-commit ordering (EB-004) — a transaction-boundary redesign, not an additive change, and not one to land in the same commit as D1.

---

## Consequences

- **Pre-existing doc drift, corrected in the same pass, since these exact blocks are being edited anyway:**
  - `docs/07_DATABASE.md §5.5`'s `held_action` DDL snippet already omitted the `params` column (added by migration `0015`, never backported into the doc) — independent of this ADR, fixed alongside it.
  - `held_action_ops.py`'s cancel-handler docstring separately claimed `expire_due` is "not wired to a job yet" — false since ADR-022 (2026-08-13/14). Caught in the same investigation that found F1; fixed in the same edit as the docstring's D1-required correction (its "expiry would also produce the same terminal state" claim, which D1 makes false on its own).
- `docs/12_API.md §7`: "expiry 24h ⇒ `cancelled`" becomes "expiry 24h ⇒ `expired`".
- `src/kang/domain/ports/held_action.py`: `HELD_ACTION_STATUSES` gains `"expired"`; the port docstring's own "24h expiry ⇒ cancelled" citation is corrected.
- `held_action_ops.py`'s expire-handler docstring ("cancels every pending held action") becomes "expires."
- Tests asserting the old collapsed behavior are updated to assert `expired`, not deleted: `test_held_action_operations.py::TestExpire` (three assertions), `test_boot_catchup.py::test_held_action_expire_is_registered_and_boot_catches_up_a_missed_day`.
- `tests/suites/CLAIMS.md`'s ADR-022 claim row is updated — the claim describes what the cited tests currently prove, which changes as of this ADR.
- **What gets harder:** nothing structural. This is a one-column enum split with no new mechanism.
- **Explicitly not decided here:** whether `expired` rows should remain visible in the approval-queue UI or be filed away — a product question the originating investigation flagged as the one that determines whether this split delivers real value, deliberately left to whoever builds the UI surface, not decided by this ADR.

---

## Amendment to ADR-022 — 2026-08-17 — `expire_due()`'s write target corrected

**Status:** accepted (recorded here per the append-only amendment pattern ADR-021 established; ADR-022's original body is not rewritten, per this project's own history discipline).

ADR-022's own text states, in two places, that `expire_due()` writes `'cancelled'` — its Decision section ("pending held actions past their 24h window now genuinely transition to `cancelled`") and its Live-verification section ("genuinely transitioned `pending → cancelled`"). Both were accurate when ADR-022 was accepted (2026-08-13/14): `cancelled` was the only terminal value `expire_due()` had ever written, because the schema at the time had no `expired` state to write instead.

ADR-024 (this document) changes `expire_due()`'s write target to `'expired'`. ADR-022's Decision and Live-verification sections are left as written — they correctly describe the system as it was built and verified at that time. This amendment exists so a future reader of ADR-022 knows: as of ADR-024, `expire_due()` writes `expired`, not `cancelled`. Read ADR-022's `cancelled` references as historical, superseded on this one point.
