-- 0016_held_action_expired_state.sql — held_action gains the `expired`
-- terminal state, per ADR-024.
--
-- Constitutional home: docs/adr/024-held-action-terminal-state-split.md
-- (the ADR this migration applies), 07_DATABASE §5.5 (held_action schema).
--
-- Before this migration, `cancel()` (Kang explicitly declines) and
-- `expire_due()` (the 24h sweep, ADR-022) wrote the identical literal
-- 'cancelled' — no field distinguished the two. That was deliberate when
-- written (expire_due() had no scheduled caller, so the collapse cost
-- nothing); ADR-022 wired the sweep as a real job, so both events now
-- genuinely occur. `expired` narrows `expire_due()`'s own target;
-- `cancel()`'s target and guard are unchanged.
--
-- SQLite cannot ALTER a CHECK constraint in place (same reason 0005
-- rebuilt the table) — the standard SQLite pattern: new table, copy,
-- drop, rename.
--
-- HISTORICAL 'cancelled' ROWS ARE NOT RECLASSIFIED. There is no way to
-- know, retroactively, whether a pre-existing 'cancelled' row was a
-- decline or an expiry — resolving that ambiguity going forward is this
-- migration's whole purpose; it cannot resolve it backward. Any row that
-- was 'cancelled' before this migration stays 'cancelled' after it,
-- regardless of which event actually produced it.
--
-- Confirmed against the real %KANG_HOME% database before writing this
-- migration (read-only connection, no lock taken): zero held_action rows
-- exist. This migration touches no live data in the one environment that
-- matters, but does not assume that as a precondition — the INSERT...
-- SELECT below is a full, order-preserving copy regardless of row count,
-- the same discipline 0005 and 0015 both used.

CREATE TABLE held_action_new (
  id            TEXT PRIMARY KEY,               -- UUIDv7
  operation     TEXT NOT NULL,                  -- registry operation name
                                                  --   (e.g. 'memory.delete') —
                                                  --   resolves commit_mode on
                                                  --   approval/recovery; distinct
                                                  --   from `action`'s free text
  action        TEXT NOT NULL,                  -- what will happen (exact)
  principal     TEXT NOT NULL,                  -- who asked
  reason        TEXT NOT NULL,                  -- why (one paragraph max)
  reversibility TEXT NOT NULL,                  -- the reversibility statement
  correlation_id TEXT NOT NULL,                 -- thread to invocation/audit
  created_at    TEXT NOT NULL,
  expires_at    TEXT NOT NULL,                  -- created_at + 24h (12 §7)
  status        TEXT NOT NULL DEFAULT 'pending' CHECK (status IN
                  ('pending','approved','executed','cancelled','expired')),
                                                  -- 'cancelled': Kang explicitly
                                                  --   declined (held_action.cancel).
                                                  -- 'expired' (ADR-024): the 24h
                                                  --   window closed with no
                                                  --   decision (expire_due()'s
                                                  --   sweep) — previously
                                                  --   collapsed into 'cancelled'.
  params        TEXT NOT NULL DEFAULT '{}'       -- ADR-021: the original
                                                  --   request's params, JSON
);

INSERT INTO held_action_new
  (id, operation, action, principal, reason, reversibility, correlation_id,
   created_at, expires_at, status, params)
  SELECT id, operation, action, principal, reason, reversibility,
         correlation_id, created_at, expires_at, status, params
  FROM held_action;

DROP TABLE held_action;
ALTER TABLE held_action_new RENAME TO held_action;

-- Consumer: the approval queue view + the 24h expiry sweep (12 §7).
CREATE INDEX idx_held_action_pending ON held_action(status, created_at)
  WHERE status = 'pending';
