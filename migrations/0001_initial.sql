-- 0001_initial.sql — bedrock schema: the sync-preparation discipline ships
-- with the very first migration (D009: cheap now, impossible to retrofit).
--
-- Constitutional home: 07_DATABASE §5.6 (change_log), §5.1 (tombstone),
-- §5.2 (task), §4.1 (trigger duties), Part VI (index doctrine), Part XIII
-- (migration rules). schema_version (07 §5.5) is bootstrapped by the
-- harness, not here — a migration cannot record itself into a table it has
-- not yet created.
--
-- Revision/updated_at bumps ride the store layer's optimistic UPDATE
-- (DB-001/DB-003: revision checks are the concurrency mechanism, so the
-- bump belongs to the same statement); triggers below carry only change
-- capture, the third sanctioned trigger duty (07 §4.1). No business logic
-- in triggers, ever.

-- ---------------------------------------------------------------- change_log
-- Outbox: row-level change capture (07 §5.6 verbatim).
CREATE TABLE change_log (
  seq INTEGER PRIMARY KEY,           -- strictly ordered by the single writer
  entity TEXT NOT NULL, entity_id TEXT NOT NULL,
  op TEXT NOT NULL CHECK (op IN ('insert','update','delete')),
  fields TEXT,                       -- JSON: changed field names (update only)
  revision INTEGER NOT NULL, device_id TEXT NOT NULL, at TEXT NOT NULL,
  synced INTEGER NOT NULL DEFAULT 0
);

-- Consumer: sync outbox scan + 90-day janitor rotation (07 §5.6, Part VI).
CREATE INDEX idx_changelog_syn ON change_log(synced, seq);

-- ----------------------------------------------------------------- tombstone
-- Completes the delete story for synchronizable rows (07 §5.1).
CREATE TABLE tombstone (
  id TEXT PRIMARY KEY,               -- id of the destroyed row
  entity TEXT NOT NULL,              -- 'task' | 'memory_record' | ...
  deleted_at TEXT NOT NULL, deleted_by TEXT NOT NULL,
  policy_ref TEXT                    -- retention.toml line or 'kang:explicit'
);

-- ---------------------------------------------------------------------- task
-- The M0 trivial entity (07 §5.2 verbatim; project FK arrives with the
-- project table at M5 — adding a column-level FK later is a new migration).
-- Sync quartet: created_at, updated_at, device_id, revision (D009).
CREATE TABLE task (
  id TEXT PRIMARY KEY,
  project_id TEXT,                   -- REFERENCES project(id) from migration adding project
  title TEXT NOT NULL, notes TEXT,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN
    ('open','scheduled','done','deferred','dropped')),
  priority INTEGER NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
  due TEXT, plan_date TEXT,          -- date scheduled into a daily plan
  estimate_min INTEGER, actual_min INTEGER,   -- calibration data (lessons!)
  completed_at TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  device_id TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1
);

-- Planner P0 indexes (07 Part VI starting set) arrive with their consumers
-- (v_today_tasks, M5): the index doctrine forbids speculative indexes.

-- ------------------------------------------------- change capture: task
-- Third sanctioned trigger duty (07 §4.1). Timestamps for insert/update come
-- from NEW.updated_at (the injected clock's value — deterministic); delete
-- has no NEW row, so capture stamps wall clock, the one sanctioned SQL-side
-- time read.
CREATE TRIGGER trg_task_capture_insert AFTER INSERT ON task
BEGIN
  INSERT INTO change_log (entity, entity_id, op, fields, revision, device_id, at)
  VALUES ('task', NEW.id, 'insert', NULL, NEW.revision, NEW.device_id,
          NEW.updated_at);
END;

CREATE TRIGGER trg_task_capture_update AFTER UPDATE ON task
BEGIN
  INSERT INTO change_log (entity, entity_id, op, fields, revision, device_id, at)
  SELECT 'task', NEW.id, 'update',
         (SELECT json_group_array(name) FROM (
            SELECT 'project_id'   AS name WHERE OLD.project_id   IS NOT NEW.project_id
            UNION ALL SELECT 'title'        WHERE OLD.title        IS NOT NEW.title
            UNION ALL SELECT 'notes'        WHERE OLD.notes        IS NOT NEW.notes
            UNION ALL SELECT 'status'       WHERE OLD.status       IS NOT NEW.status
            UNION ALL SELECT 'priority'     WHERE OLD.priority     IS NOT NEW.priority
            UNION ALL SELECT 'due'          WHERE OLD.due          IS NOT NEW.due
            UNION ALL SELECT 'plan_date'    WHERE OLD.plan_date    IS NOT NEW.plan_date
            UNION ALL SELECT 'estimate_min' WHERE OLD.estimate_min IS NOT NEW.estimate_min
            UNION ALL SELECT 'actual_min'   WHERE OLD.actual_min   IS NOT NEW.actual_min
            UNION ALL SELECT 'completed_at' WHERE OLD.completed_at IS NOT NEW.completed_at
         )),
         NEW.revision, NEW.device_id, NEW.updated_at;
END;

CREATE TRIGGER trg_task_capture_delete AFTER DELETE ON task
BEGIN
  INSERT INTO change_log (entity, entity_id, op, fields, revision, device_id, at)
  VALUES ('task', OLD.id, 'delete', NULL, OLD.revision, OLD.device_id,
          strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
END;
