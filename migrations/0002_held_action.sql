-- 0002_held_action.sql — the consequential-action gate's data plumbing.
--
-- Constitutional home: 12_API §7 (held_action resource: what/who/why/
-- reversibility + id + 24h expiry + status), 09_UI §7 (dialog contents),
-- 10_SECURITY SEC-003 (out-of-band approval). Held actions are per-device
-- operational confirmations, not synchronizable truth — no sync quartet
-- (they do not replicate; a confirmation belongs to the device that asked).
--
-- Approval authority (Kang-only, first-party session) is enforced at the
-- API/session layer (M4), not by this table.

CREATE TABLE held_action (
  id            TEXT PRIMARY KEY,               -- UUIDv7
  action        TEXT NOT NULL,                  -- what will happen (exact)
  principal     TEXT NOT NULL,                  -- who asked
  reason        TEXT NOT NULL,                  -- why (one paragraph max)
  reversibility TEXT NOT NULL,                  -- the reversibility statement
  correlation_id TEXT NOT NULL,                 -- thread to invocation/audit
  created_at    TEXT NOT NULL,
  expires_at    TEXT NOT NULL,                  -- created_at + 24h (12 §7)
  status        TEXT NOT NULL DEFAULT 'pending' CHECK (status IN
                  ('pending','approved','cancelled'))
);

-- Consumer: the approval queue view + the 24h expiry sweep (12 §7).
CREATE INDEX idx_held_action_pending ON held_action(status, created_at)
  WHERE status = 'pending';
