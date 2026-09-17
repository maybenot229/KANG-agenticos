-- 0021_memory_revision_device_id.sql — memory_revision gains its own
-- device_id (ADR-048 Amendment, 2026-09-18), closing the gap 0020 flagged.
--
-- Constitutional home: docs/adr/048-memory-truth-schema.md (Amendment
-- 2026-09-18, correcting D3's "memory_revision exactly as 07 writes it"),
-- 07_DATABASE Part X §1 ("device_id on every synchronizable row"), Part X
-- §5 (LWW losers are "preserved in memory_revision" — the row IS
-- synchronizable), §5.1 (memory_revision DDL, amended in the same commit),
-- §5.6 (change capture), 06_MEMORY §8.2 (revision semantics).
--
-- Why. 07's own memory_revision DDL, copied verbatim into 0020, carries no
-- device_id — a third internal inconsistency in 07 of the same class
-- ADR-046 found for conversation/message: Part X §1 requires the column on
-- every synchronizable row and Part X §5 makes memory_revision one. 0020's
-- capture trigger worked around the missing column by deriving device_id
-- from the owning memory_record row via a subquery. That is (a) order-
-- dependent inside the edit transaction — a store that snapshots the old
-- content into memory_revision BEFORE stamping the record's new device_id
-- captures the previous writer's device, not the editor's — and (b) still
-- leaves the row itself without the column a future sync merge orders by
-- (Part X §5: `(revision, device_id)`). D009's own rule applies: cheap now
-- (the table is empty), brutal after years of revisions. Kang's decision,
-- 2026-09-18.
--
-- SQLite cannot add a NOT NULL column without a default via ALTER TABLE
-- ADD COLUMN, and a default here would be a lie (an invented device) —
-- so the standard rebuild: new table, order-preserving copy, drop, rename
-- (0005/0016/0020's own pattern). 0020's memory_revision capture trigger
-- dies with the dropped table and is recreated below reading
-- NEW.device_id directly — the subquery is gone.
--
-- HISTORICAL ROWS: any pre-existing memory_revision row (none can exist on
-- the real %KANG_HOME% — 0020 has never been applied there, schema_version
-- head was 19 when 0020 was written; and no code path writes this table
-- yet) is copied with device_id taken from its owning memory_record row —
-- the only honest value available, and exactly what 0020's trigger would
-- have captured for it. The copy does not assume emptiness.
--
-- Real %KANG_HOME% checked read-only before writing this migration
-- (2026-09-18, no lock taken): schema_version head = 19; memory_revision
-- does not exist there yet.

CREATE TABLE memory_revision_new (   -- edit history (Memory §8.2)
  record_id  TEXT NOT NULL REFERENCES memory_record(id) ON DELETE CASCADE,
  revision   INTEGER NOT NULL,
  content    TEXT NOT NULL,
  edited_by  TEXT NOT NULL, edited_at TEXT NOT NULL,
  device_id  TEXT NOT NULL,          -- ADR-048 Amendment: the editing device
                                     --   (Part X §1), not derived from the
                                     --   parent row
  PRIMARY KEY (record_id, revision)
);

INSERT INTO memory_revision_new (record_id, revision, content, edited_by,
                                 edited_at, device_id)
SELECT r.record_id, r.revision, r.content, r.edited_by, r.edited_at,
       m.device_id
FROM memory_revision r JOIN memory_record m ON m.id = r.record_id
ORDER BY r.rowid;

DROP TABLE memory_revision;
ALTER TABLE memory_revision_new RENAME TO memory_revision;

-- Insert-only capture (revisions are append-only; ADR-048 D3), now from the
-- row's own device_id — no subquery, no ordering dependence on the
-- surrounding transaction.
CREATE TRIGGER trg_memory_revision_capture_insert AFTER INSERT ON memory_revision
BEGIN
  INSERT INTO change_log (entity, entity_id, op, fields, revision, device_id, at)
  VALUES ('memory_revision', NEW.record_id, 'insert', NULL, NEW.revision,
          NEW.device_id, NEW.edited_at);
END;
