-- 0006_domain_entities.sql — the M5 domain schema: goal, project, milestone,
-- competition, deadline. Shapes are 07_DATABASE §5.2 verbatim.
--
-- Constitutional home: 07_DATABASE §5.2 (entity shapes), Part VI (index
-- doctrine: every index cites its consumer), §4.1 (third sanctioned trigger
-- duty — change capture only, never business logic), §5.1 (tombstones),
-- Appendix B (the sanctioned CASCADE list: project → task, milestone;
-- competition → deadline). 18 §3 M5 (domain areas tasks/projects/deadlines/
-- competitions-tracking).
--
-- Creation order follows FK dependency: goal → project → milestone,
-- competition → deadline.
--
-- `task` is RECREATED here, not altered: 0001 created it with a bare
-- `project_id TEXT` and the comment "REFERENCES project(id) from migration
-- adding project" — this is that migration, and SQLite cannot add a foreign
-- key to an existing table. The recreate-copy-drop-rename pattern matches
-- 0005's. Its triggers and indexes are dropped and rebuilt with it (a
-- trigger bound to a dropped table dies with it).

-- ---------------------------------------------------------------------- goal
CREATE TABLE goal (
  id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT,
  horizon TEXT NOT NULL CHECK (horizon IN ('quarter','year','life')),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN
    ('active','achieved','revised','retired')),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  device_id TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1
);
-- No '5yr' horizon: ADR-003 (accepted) keeps the 5-year candidate in the
-- vault/guide until it is a real commitment, not a forced-choice artifact.

-- ------------------------------------------------------------------- project
CREATE TABLE project (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN
    ('active','paused','completed','archived','abandoned')),
  vault_folder TEXT,                 -- path within vault (reference, not content)
  github_repo TEXT,                  -- owner/name
  goal_id TEXT REFERENCES goal(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  device_id TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1
);

-- ----------------------------------------------------------------- milestone
CREATE TABLE milestone (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  title TEXT NOT NULL, due TEXT,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN
    ('pending','reached','missed','dropped')),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  device_id TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1
);

-- --------------------------------------------------------------- competition
-- M5 tracks competitions that already exist as rows. Discovery, evaluation,
-- and scouting are Phase 3 (03_ROADMAP §4) — `evaluation` and `result` are
-- columns awaiting those consumers, deliberately unwritten until then.
CREATE TABLE competition (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, url TEXT,
  status TEXT NOT NULL DEFAULT 'discovered' CHECK (status IN
    ('discovered','evaluating','entered','skipped','submitted',
     'judged','archived')),
  evaluation TEXT,                   -- JSON: fit/feasibility/effort/risk brief
  result TEXT,                       -- JSON: outcome after judging
  project_id TEXT REFERENCES project(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  device_id TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1
);

-- ------------------------------------------------------------------ deadline
CREATE TABLE deadline (
  id TEXT PRIMARY KEY,
  competition_id TEXT REFERENCES competition(id) ON DELETE CASCADE,
  project_id     TEXT REFERENCES project(id)     ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN
    ('registration','submission','event','school','custom')),
  title TEXT NOT NULL, at TEXT NOT NULL,
  lead_days TEXT NOT NULL DEFAULT '[14,7,3,1]',   -- JSON alert schedule
  status TEXT NOT NULL DEFAULT 'tracked' CHECK (status IN
    ('tracked','alerted','met','missed','cancelled')),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  device_id TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
  CHECK (competition_id IS NOT NULL OR project_id IS NOT NULL
         OR kind IN ('school','custom'))
);

-- ----------------------------------------------- task: recreate with its FK
DROP TRIGGER trg_task_capture_insert;
DROP TRIGGER trg_task_capture_update;
DROP TRIGGER trg_task_capture_delete;

CREATE TABLE task_new (
  id TEXT PRIMARY KEY,
  project_id TEXT REFERENCES project(id) ON DELETE CASCADE,  -- NULL = standalone
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

INSERT INTO task_new
  (id, project_id, title, notes, status, priority, due, plan_date,
   estimate_min, actual_min, completed_at, created_at, updated_at,
   device_id, revision)
  SELECT id, project_id, title, notes, status, priority, due, plan_date,
         estimate_min, actual_min, completed_at, created_at, updated_at,
         device_id, revision
  FROM task;

DROP TABLE task;
ALTER TABLE task_new RENAME TO task;

-- Change capture, rebuilt for the recreated table (07 §4.1). Identical
-- semantics to 0001's: insert/update stamp NEW.updated_at (the injected
-- clock's value — deterministic); delete has no NEW row, so it stamps wall
-- clock, the one sanctioned SQL-side time read.
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

-- Change capture for the deadline entity: the deadline lifecycle
-- (tracked → alerted → met/missed) is synchronizable truth like task.
CREATE TRIGGER trg_deadline_capture_insert AFTER INSERT ON deadline
BEGIN
  INSERT INTO change_log (entity, entity_id, op, fields, revision, device_id, at)
  VALUES ('deadline', NEW.id, 'insert', NULL, NEW.revision, NEW.device_id,
          NEW.updated_at);
END;

CREATE TRIGGER trg_deadline_capture_update AFTER UPDATE ON deadline
BEGIN
  INSERT INTO change_log (entity, entity_id, op, fields, revision, device_id, at)
  SELECT 'deadline', NEW.id, 'update',
         (SELECT json_group_array(name) FROM (
            SELECT 'competition_id' AS name WHERE OLD.competition_id IS NOT NEW.competition_id
            UNION ALL SELECT 'project_id'  WHERE OLD.project_id  IS NOT NEW.project_id
            UNION ALL SELECT 'kind'        WHERE OLD.kind        IS NOT NEW.kind
            UNION ALL SELECT 'title'       WHERE OLD.title       IS NOT NEW.title
            UNION ALL SELECT 'at'          WHERE OLD.at          IS NOT NEW.at
            UNION ALL SELECT 'lead_days'   WHERE OLD.lead_days   IS NOT NEW.lead_days
            UNION ALL SELECT 'status'      WHERE OLD.status      IS NOT NEW.status
         )),
         NEW.revision, NEW.device_id, NEW.updated_at;
END;

CREATE TRIGGER trg_deadline_capture_delete AFTER DELETE ON deadline
BEGIN
  INSERT INTO change_log (entity, entity_id, op, fields, revision, device_id, at)
  VALUES ('deadline', OLD.id, 'delete', NULL, OLD.revision, OLD.device_id,
          strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
END;

-- ------------------------------------------------------------------ indexes
-- Part VI doctrine: every index cites its consumer; speculative indexes are
-- forbidden. These are 07 Part VI's "Planner P0" starting set, arriving now
-- with the consumers M5 builds.
CREATE INDEX idx_task_plan     ON task(plan_date, status) WHERE status IN ('open','scheduled');
CREATE INDEX idx_task_project  ON task(project_id, status);
CREATE INDEX idx_deadline_at   ON deadline(at) WHERE status = 'tracked';
