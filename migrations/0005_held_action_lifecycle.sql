-- 0005_held_action_lifecycle.sql — held_action gains the `executed` terminal
-- state and an `operation` column, per ADR 001 (held-action crash-semantics).
--
-- Constitutional home: docs/adr/001-held-action-crash-semantics.md (Decision
-- §2 + Amendment: approved != done; commit_mode is registry metadata, not a
-- row column). 07_DATABASE §5.5 (held_action schema — this migration is that
-- delta, applied).
--
-- SQLite cannot ALTER a CHECK constraint in place (07 Part XIII: migrations
-- are forward-only, no down-migrations) — the table is recreated per the
-- standard SQLite pattern: new table, copy, drop, rename. No data exists in
-- `held_action` at this schema version (the feature has no live callers yet,
-- 12_API §7 handlers unwired) — a plain copy is sufficient; a future
-- migration touching a populated held_action table would need an explicit
-- backfill for the new `operation` column, which this one does not require.

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
                  ('pending','approved','executed','cancelled'))
                                                  -- 'executed': the held effect
                                                  --   committed (ADR 001) —
                                                  --   'approved' alone means
                                                  --   intent only, not done
);

INSERT INTO held_action_new
  (id, operation, action, principal, reason, reversibility, correlation_id,
   created_at, expires_at, status)
  SELECT id, '', action, principal, reason, reversibility, correlation_id,
         created_at, expires_at, status
  FROM held_action;

DROP TABLE held_action;
ALTER TABLE held_action_new RENAME TO held_action;

-- Consumer: the approval queue view + the 24h expiry sweep (12 §7).
CREATE INDEX idx_held_action_pending ON held_action(status, created_at)
  WHERE status = 'pending';
