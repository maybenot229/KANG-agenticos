-- 0013_milestone_capture.sql — change-capture triggers for `milestone`,
-- its first write path (ADR-015).
--
-- Constitutional home: 07_DATABASE §5.6 ("Populated by narrow AFTER-
-- triggers on synchronizable tables... exercised (and tested) from day
-- one"). Same pattern as 0011_project_capture.sql (ADR-013) and
-- 0012_competition_capture.sql (ADR-014) — 0006_domain_entities.sql added
-- the `milestone` table itself but only wired capture triggers for
-- `task`/`deadline`, the two entities with a write path at the time.

CREATE TRIGGER trg_milestone_capture_insert AFTER INSERT ON milestone
BEGIN
  INSERT INTO change_log (entity, entity_id, op, fields, revision, device_id, at)
  VALUES ('milestone', NEW.id, 'insert', NULL, NEW.revision, NEW.device_id,
          NEW.updated_at);
END;

CREATE TRIGGER trg_milestone_capture_update AFTER UPDATE ON milestone
BEGIN
  INSERT INTO change_log (entity, entity_id, op, fields, revision, device_id, at)
  SELECT 'milestone', NEW.id, 'update',
         (SELECT json_group_array(name) FROM (
            SELECT 'project_id' AS name WHERE OLD.project_id IS NOT NEW.project_id
            UNION ALL SELECT 'title'   WHERE OLD.title   IS NOT NEW.title
            UNION ALL SELECT 'due'     WHERE OLD.due     IS NOT NEW.due
            UNION ALL SELECT 'status'  WHERE OLD.status  IS NOT NEW.status
         )),
         NEW.revision, NEW.device_id, NEW.updated_at;
END;

CREATE TRIGGER trg_milestone_capture_delete AFTER DELETE ON milestone
BEGIN
  INSERT INTO change_log (entity, entity_id, op, fields, revision, device_id, at)
  VALUES ('milestone', OLD.id, 'delete', NULL, OLD.revision, OLD.device_id,
          strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
END;
