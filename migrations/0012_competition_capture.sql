-- 0012_competition_capture.sql — change-capture triggers for `competition`,
-- its first write path (ADR-014).
--
-- Constitutional home: 07_DATABASE §5.6 ("Populated by narrow AFTER-
-- triggers on synchronizable tables... exercised (and tested) from day
-- one"). Same pattern as 0011_project_capture.sql for `project` (ADR-013)
-- — 0006_domain_entities.sql added the `competition` table itself but
-- only wired capture triggers for `task`/`deadline`, the two entities
-- with a write path at the time.

CREATE TRIGGER trg_competition_capture_insert AFTER INSERT ON competition
BEGIN
  INSERT INTO change_log (entity, entity_id, op, fields, revision, device_id, at)
  VALUES ('competition', NEW.id, 'insert', NULL, NEW.revision, NEW.device_id,
          NEW.updated_at);
END;

CREATE TRIGGER trg_competition_capture_update AFTER UPDATE ON competition
BEGIN
  INSERT INTO change_log (entity, entity_id, op, fields, revision, device_id, at)
  SELECT 'competition', NEW.id, 'update',
         (SELECT json_group_array(name) FROM (
            SELECT 'name'       AS name WHERE OLD.name       IS NOT NEW.name
            UNION ALL SELECT 'url'        WHERE OLD.url        IS NOT NEW.url
            UNION ALL SELECT 'status'     WHERE OLD.status     IS NOT NEW.status
            UNION ALL SELECT 'evaluation' WHERE OLD.evaluation IS NOT NEW.evaluation
            UNION ALL SELECT 'result'     WHERE OLD.result     IS NOT NEW.result
            UNION ALL SELECT 'project_id' WHERE OLD.project_id IS NOT NEW.project_id
         )),
         NEW.revision, NEW.device_id, NEW.updated_at;
END;

CREATE TRIGGER trg_competition_capture_delete AFTER DELETE ON competition
BEGIN
  INSERT INTO change_log (entity, entity_id, op, fields, revision, device_id, at)
  VALUES ('competition', OLD.id, 'delete', NULL, OLD.revision, OLD.device_id,
          strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
END;
