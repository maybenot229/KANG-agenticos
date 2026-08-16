-- 0017_held_action_provenance.sql — held_action gains `decided_at` and
-- `decided_by`, per ADR-025.
--
-- Constitutional home: docs/adr/025-held-action-transition-provenance.md
-- (the ADR this migration applies), 07_DATABASE §5.5 (held_action schema).
--
-- Before this migration no held-action transition was attributable in
-- durable state: `reason` and `correlation_id` are both written once at
-- creation and describe the REQUEST, never the decision; the dispatcher's
-- audit payloads carry no request params (so no held-action id); the
-- invocation ledger has no params column; no held_action.* event type is
-- registered. "Who cancelled this, and when" had no answer. These two
-- columns are that answer, in row state — a row must be able to explain
-- itself without replaying a bus.
--
-- Written on every transition OUT OF `pending` (approve / cancel /
-- expire). Deliberately NOT written by mark_executed: `executed` inherits
-- the approve step's provenance, because the DECISION was the approval —
-- execution is the effect landing, an outcome rather than a decision.
--
-- NULL SEMANTICS, STATED BECAUSE THE TWO READINGS ARE INDISTINGUISHABLE
-- FROM THE DATA AND THE WRONG ONE MISLEADS:
--   * NULL on a `pending` row  = no decision has been made yet. Correct
--                                and expected; this is why the columns
--                                are nullable at all.
--   * NULL on a TERMINAL row   = "predates ADR-025", NOT "no decision
--                                occurred". A pre-migration cancelled row
--                                had a real decider; the system simply
--                                did not record them at the time. Never
--                                read a NULL here as "nobody decided."
--
-- A plain ALTER TABLE ADD COLUMN would suffice (no CHECK change — the
-- same reasoning 0015 used for `params`). The full rebuild is chosen
-- anyway: 0016 rebuilt this table one migration ago, and a rebuild keeps
-- the whole column list — nullability and all — readable in one
-- CREATE TABLE that matches 07 §5.5's own snippet, instead of leaving the
-- table's true shape to be reconstructed by mentally replaying two
-- migrations. The cost is a copy of a table verified to hold zero rows.
--
-- Confirmed against the real %KANG_HOME% database immediately before
-- writing this migration (read-only connection, no lock taken): zero
-- held_action rows, schema_version head 15 (the running Core has not
-- booted since ADR-024 — 0016 and this migration both apply on its next
-- start). The INSERT...SELECT below is a full copy regardless of row
-- count, the same discipline 0005/0015/0016 all used.

CREATE TABLE held_action_new (
  id            TEXT PRIMARY KEY,               -- UUIDv7
  operation     TEXT NOT NULL,                  -- registry operation name
                                                  --   (e.g. 'memory.delete') —
                                                  --   resolves commit_mode on
                                                  --   approval/recovery; distinct
                                                  --   from `action`'s free text
  action        TEXT NOT NULL,                  -- what will happen (exact)
  principal     TEXT NOT NULL,                  -- who ASKED (not who decided —
                                                  --   see decided_by below)
  reason        TEXT NOT NULL,                  -- why the action was REQUESTED
                                                  --   (never why it transitioned)
  reversibility TEXT NOT NULL,                  -- the reversibility statement
  correlation_id TEXT NOT NULL,                 -- threads to the REQUESTING
                                                  --   invocation/audit entry
  created_at    TEXT NOT NULL,
  expires_at    TEXT NOT NULL,                  -- created_at + 24h (12 §7)
  status        TEXT NOT NULL DEFAULT 'pending' CHECK (status IN
                  ('pending','approved','executed','cancelled','expired')),
                                                  -- 'cancelled': Kang explicitly
                                                  --   declined. 'expired': the 24h
                                                  --   window closed with no
                                                  --   decision (ADR-024).
  params        TEXT NOT NULL DEFAULT '{}',      -- ADR-021: the original
                                                  --   request's params, JSON
  decided_at    TEXT,                            -- ADR-025: when the transition
                                                  --   out of `pending` happened
                                                  --   (injected Clock, never wall
                                                  --   time — 11 §25). NULL: see
                                                  --   the header's NULL semantics.
  decided_by    TEXT                             -- ADR-025: the principal who
                                                  --   effected that transition —
                                                  --   'kang' for approve/cancel,
                                                  --   'kernel:scheduler' for the
                                                  --   expiry sweep (the identity
                                                  --   that job already mints its
                                                  --   session and audits under;
                                                  --   not a new principal value)
);

INSERT INTO held_action_new
  (id, operation, action, principal, reason, reversibility, correlation_id,
   created_at, expires_at, status, params, decided_at, decided_by)
  SELECT id, operation, action, principal, reason, reversibility,
         correlation_id, created_at, expires_at, status, params, NULL, NULL
  FROM held_action;

DROP TABLE held_action;
ALTER TABLE held_action_new RENAME TO held_action;

-- Consumer: the approval queue view + the 24h expiry sweep (12 §7).
CREATE INDEX idx_held_action_pending ON held_action(status, created_at)
  WHERE status = 'pending';
