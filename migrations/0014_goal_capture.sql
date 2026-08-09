-- 0014_goal_capture.sql — change-capture triggers for `goal`, its first
-- write path (ADR-016).
--
-- Constitutional home: 07_DATABASE §5.6 ("Populated by narrow AFTER-
-- triggers on synchronizable tables... exercised (and tested) from day
-- one"). 0006_domain_entities.sql added the `goal` table itself but only
-- wired capture triggers for `task`/`deadline` — the two entities with a
-- real write path at the time. `goal.create` (ADR-016) is `goal`'s first,
-- so its capture trigger arrives with it, mirroring 0011/0012/0013's own
-- `trg_project_capture_*`/`trg_competition_capture_*`/
-- `trg_milestone_capture_*` pattern exactly (identical shape, `goal`'s
-- own columns).

CREATE TRIGGER trg_goal_capture_insert AFTER INSERT ON goal
BEGIN
  INSERT INTO change_log (entity, entity_id, op, fields, revision, device_id, at)
  VALUES ('goal', NEW.id, 'insert', NULL, NEW.revision, NEW.device_id,
          NEW.updated_at);
END;

CREATE TRIGGER trg_goal_capture_update AFTER UPDATE ON goal
BEGIN
  INSERT INTO change_log (entity, entity_id, op, fields, revision, device_id, at)
  SELECT 'goal', NEW.id, 'update',
         (SELECT json_group_array(name) FROM (
            SELECT 'title'       AS name WHERE OLD.title       IS NOT NEW.title
            UNION ALL SELECT 'description' WHERE OLD.description IS NOT NEW.description
            UNION ALL SELECT 'horizon'     WHERE OLD.horizon     IS NOT NEW.horizon
            UNION ALL SELECT 'status'      WHERE OLD.status      IS NOT NEW.status
         )),
         NEW.revision, NEW.device_id, NEW.updated_at;
END;

CREATE TRIGGER trg_goal_capture_delete AFTER DELETE ON goal
BEGIN
  INSERT INTO change_log (entity, entity_id, op, fields, revision, device_id, at)
  VALUES ('goal', OLD.id, 'delete', NULL, OLD.revision, OLD.device_id,
          strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
END;
