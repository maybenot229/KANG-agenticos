-- 0003_scheduler.sql — the DB-backed job scheduler (D014) + app_state.
--
-- Constitutional home: 07_DATABASE §5.5 (job, job_run, app_state — verbatim
-- shapes), 04_ARCHITECTURE D014 (jobs are rows; cron|event schedules;
-- catch-up policies; quarantine on repeated failure), 05_AGENTS §11.
--
-- Tension resolved (07 wins on schema): 04 §15 prose mentions job
-- last_run/next_run columns; 07 §5.5 omits them — last-processed-slot is
-- derived from job_run.started. This migration follows 07.

CREATE TABLE job (                   -- scheduler (D014)
  id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE,
  schedule TEXT NOT NULL,            -- cron expr | 'event:{type}' | 'every:{s}'
  catch_up TEXT NOT NULL CHECK (catch_up IN
    ('run_once_latest','run_all_missed','skip')),
  enabled INTEGER NOT NULL DEFAULT 1,
  timeout_s INTEGER NOT NULL DEFAULT 300,
  quarantined INTEGER NOT NULL DEFAULT 0,      -- auto-disable on repeated failure
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);

CREATE TABLE job_run (
  id INTEGER PRIMARY KEY,            -- local-only: rowid fine (DB-003)
  job_id TEXT NOT NULL REFERENCES job(id) ON DELETE CASCADE,
  started TEXT NOT NULL,             -- the SLOT time this run represents
  finished TEXT,
  outcome TEXT CHECK (outcome IN ('ok','failed','timeout','skipped')),
  detail TEXT, correlation_id TEXT NOT NULL
);

-- Consumer: last-processed-slot (max started) + catch-up idempotency, and
-- the consecutive-failure count for quarantine (05 §11).
CREATE INDEX idx_job_run_job ON job_run(job_id, started);

CREATE TABLE app_state (             -- runtime-mutable UI/system state ONLY
  key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL
);  -- Config truth stays in TOML (D003). app_state holds window layouts,
    -- last-seen markers, product state — and the automation kill-switch.
