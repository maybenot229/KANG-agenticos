-- 0011_project_capture.sql — change-capture triggers for `project`, its
-- first write path (ADR-013).
--
-- Constitutional home: 07_DATABASE §5.6 ("Populated by narrow AFTER-
-- triggers on synchronizable tables... exercised (and tested) from day
-- one"). 0006_domain_entities.sql added the `project` table itself but
-- only wired capture triggers for `task`/`deadline` — the two entities
-- with a real write path at the time. `project.create` (ADR-013) is
-- `project`'s first, so its capture trigger arrives with it, mirroring
-- 0006's own `trg_task_capture_*`/`trg_deadline_capture_*` pattern
-- exactly (identical shape, `project`'s own columns).

CREATE TRIGGER trg_project_capture_insert AFTER INSERT ON project
BEGIN
  INSERT INTO change_log (entity, entity_id, op, fields, revision, device_id, at)
  VALUES ('project', NEW.id, 'insert', NULL, NEW.revision, NEW.device_id,
          NEW.updated_at);
END;

CREATE TRIGGER trg_project_capture_update AFTER UPDATE ON project
BEGIN
  INSERT INTO change_log (entity, entity_id, op, fields, revision, device_id, at)
  SELECT 'project', NEW.id, 'update',
         (SELECT json_group_array(name) FROM (
            SELECT 'name'         AS name WHERE OLD.name         IS NOT NEW.name
            UNION ALL SELECT 'description' WHERE OLD.description IS NOT NEW.description
            UNION ALL SELECT 'status'      WHERE OLD.status      IS NOT NEW.status
            UNION ALL SELECT 'vault_folder' WHERE OLD.vault_folder IS NOT NEW.vault_folder
            UNION ALL SELECT 'github_repo' WHERE OLD.github_repo IS NOT NEW.github_repo
            UNION ALL SELECT 'goal_id'     WHERE OLD.goal_id     IS NOT NEW.goal_id
         )),
         NEW.revision, NEW.device_id, NEW.updated_at;
END;

CREATE TRIGGER trg_project_capture_delete AFTER DELETE ON project
BEGIN
  INSERT INTO change_log (entity, entity_id, op, fields, revision, device_id, at)
  VALUES ('project', OLD.id, 'delete', NULL, OLD.revision, OLD.device_id,
          strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
END;
