-- 0004_api.sql — API-layer persistent state: the invocation ledger, the
-- idempotency store, and local sessions.
--
-- Constitutional home: 12_API §4 (invocation resource), §12 (explain reads
-- invocation rows from PERMANENT storage), API-004 (idempotency keys, 7-day
-- retention), API-003 (local sessions). These are execution/observability
-- infrastructure, not synchronizable domain truth — no sync quartet
-- (sessions and idempotency are per-device; the invocation ledger is a
-- local execution history like job_run).
--
-- Delta owed to 07 §5.5: reconcile `invocation` (general execution ledger)
-- with `agent_invocation` (the agent-specific projection). Recorded openly.

CREATE TABLE invocation (            -- execution history for `explain` (12 §12)
  id            TEXT PRIMARY KEY,               -- UUIDv7
  correlation_id TEXT NOT NULL,                 -- the one thread (SEC-006)
  kind          TEXT NOT NULL CHECK (kind IN ('command','query','agent')),
  operation     TEXT NOT NULL,                  -- registry operation name
  principal     TEXT NOT NULL,
  trigger       TEXT NOT NULL,                  -- 'kang'|'cli'|'job:{id}'|'event:{type}'
  started       TEXT NOT NULL,
  finished      TEXT,
  outcome       TEXT CHECK (outcome IN ('ok','failed','degraded','denied')),
  manifest      TEXT,                           -- context manifest JSON (agents)
  manifest_pruned INTEGER NOT NULL DEFAULT 0    -- content→ids-only after 180d
);
-- Consumer: explain.invocation {correlation_id} (12 §12).
CREATE INDEX idx_invocation_corr ON invocation(correlation_id);

CREATE TABLE idempotency_key (       -- API-004: return the original outcome
  key           TEXT PRIMARY KEY,               -- client-generated UUIDv7
  outcome_json  TEXT NOT NULL,                  -- the first outcome, verbatim
  created_at    TEXT NOT NULL
);
-- Consumer: the 7-day retention sweep (API-004).
CREATE INDEX idx_idempotency_created ON idempotency_key(created_at);

CREATE TABLE session (               -- API-003: local session → principal
  token         TEXT PRIMARY KEY,
  principal     TEXT NOT NULL,
  first_party   INTEGER NOT NULL DEFAULT 0,
  created_at    TEXT NOT NULL
);
