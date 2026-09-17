-- 0020_memory_truth_schema.sql — the memory-truth DDL (ADR-048), Phase 2's
-- first migration: schema-bearing truth precedes every policy that governs
-- it (18 §7.2). Lands 07_DATABASE §5.1, §5.3, §5.4, Part VIII, §6.1's four
-- FTS5 tables with sync triggers, and §4.1's third trigger duty (change
-- capture) for every synchronizable table this slice creates — plus the
-- `message` rebuild (07 §5.5) D2 requires. No ports, stores, fakes,
-- operations, config, vec tables, secondary indexes, or views land here
-- (ADR-048 D4) — this migration is truth and its schema suite only.
--
-- Constitutional home: docs/adr/048-memory-truth-schema.md (D1-D5),
-- 07_DATABASE.md §5.1 (memory_record/memory_revision/memory_candidate_queue/
-- episode, docs/07_DATABASE.md:206-281), §5.3 (vault_note/vault_chunk,
-- :399-421), §5.4 (link/link_index, :423-446), §5.5 (message rebuild,
-- :550-555), §4.1 (trigger duties, :150-154), §5.6 (change capture, :576-
-- 589), §6.1 (FTS5, :615-626), Part VIII (embedding_version, :664-687),
-- Part XIII.5 (provenance invariant), Appendix B (sanctioned CASCADEs).
--
-- Deviations from 07's literal DDL, each named by ADR-048 rather than
-- silently matched:
--
-- D1 — memory_record.status narrows to ('active','under_review',
--   'superseded','archived'), loses 'candidate'/'rejected' and its
--   DEFAULT. A candidate lives only in memory_candidate_queue, which
--   lands with no sync quartet, no capture trigger, no index (its
--   consumers arrive with the gate/janitor slices).
--
-- D2 — memory_record, episode, vault_chunk, and message (rebuilt here)
--   each gain an explicit `rowid INTEGER PRIMARY KEY` first column;
--   `id TEXT NOT NULL UNIQUE` remains the identity everywhere outside
--   adapters/sqlite (FKs, change_log.entity_id, ports, API responses).
--   This is what fts_*'s `content_rowid='rowid'` binds to — a value
--   SQLite's own INTEGER PRIMARY KEY contract guarantees stable, unlike
--   the implicit rowid on a TEXT PRIMARY KEY table (not guaranteed
--   stable across VACUUM by SQLite's own documentation, even though
--   probed-unchanged on this machine — see ADR-048 Finding 2).
--
-- D3 — everything above lands in this one migration (embedding_version
--   first, since ADR-038's own empirical lesson is that a REFERENCES to
--   a not-yet-created table refuses every insert under
--   PRAGMA foreign_keys=ON, not just at CREATE time).
--
-- D4 — deliberately NOT landed here: vec_* tables (no dimension until
--   the embedding-model spike runs), secondary indexes (no consumer
--   yet — index doctrine forbids speculative indexes), views (same
--   rule), config/defaults/memory.toml (no reader yet), any store/port/
--   fake/operation (this migration is truth only).
--
-- D5 — memory_record's update-capture trigger fires
--   AFTER UPDATE OF <every column except last_accessed, access_count>
--   (listed explicitly below, not a bare AFTER UPDATE) — a retrieval
--   touching only access statistics runs on the read-only pool anyway
--   (DB-001) and must never emit a change_log row or read as a truth
--   mutation.
--
-- A gap found while writing this migration, not pre-specified by
-- ADR-048 or the build brief, resolved here rather than left silent:
-- 07's own memory_revision DDL (verbatim, copied below) carries no
-- device_id column, but ADR-048 D3 requires memory_revision's insert
-- to be change-captured, and change_log.device_id is NOT NULL (07
-- §5.6). memory_revision rows are always inserted in the same
-- transaction as the memory_record update that produced them (06
-- §8.2), so the capture trigger derives device_id from the owning
-- memory_record row via a subquery on NEW.record_id rather than from a
-- column memory_revision does not have. This is an implementation
-- mechanics gap, not a decision — no Decision/Consequence text is
-- touched; flagged in the build report for Kang to confirm or correct.
--
-- Real %KANG_HOME% checked read-only before writing this migration
-- (2026-09-17, no lock taken): schema_version head = 19, `message` has
-- 0 rows, `conversation` has 0 rows. The message rebuild below is a
-- full, order-preserving copy regardless of row count anyway (the same
-- discipline 0005/0015/0016 used) — it does not assume emptiness.

-- ------------------------------------------------------------- embedding_version
-- 07 Part VIII. Created first: every embedding_ver FK below references it,
-- and PRAGMA foreign_keys=ON refuses inserts against a REFERENCES to a
-- table that does not yet exist (ADR-038's own empirical lesson). Zero
-- rows land here — nothing registers version 1 in this slice.
CREATE TABLE embedding_version (
  ver INTEGER PRIMARY KEY, model TEXT NOT NULL, dim INTEGER NOT NULL,
  created_at TEXT NOT NULL, status TEXT NOT NULL CHECK (status IN
    ('active','migrating','retired'))
);

-- ------------------------------------------------------------------ memory_record
-- 07 §5.1, D1 (status narrowed, no DEFAULT), D2 (rowid), DB-005's private
-- invariant made a real forward-only CHECK.
CREATE TABLE memory_record (
  rowid         INTEGER PRIMARY KEY,            -- D2: storage-local FTS5
                                                  --   binding only; never
                                                  --   crosses adapters/sqlite
  id            TEXT NOT NULL UNIQUE,            -- UUIDv7 — the identity
                                                  --   everywhere else
  type          TEXT NOT NULL CHECK (type IN
                 ('profile','preference','fact','relationship',
                  'lesson','rule','observation','reflection')),
  status        TEXT NOT NULL CHECK (status IN
                 ('active','under_review','superseded',
                  'archived')),                  -- deleted = row gone + tombstone
                                                  -- D1: no DEFAULT — the gate
                                                  --   supplies 'active'
                                                  --   explicitly at approval;
                                                  --   'candidate'/'rejected'
                                                  --   live only in
                                                  --   memory_candidate_queue
  content       TEXT NOT NULL CHECK (length(content) > 0),
  trust_tier    INTEGER NOT NULL CHECK (trust_tier IN (0,1,2)),
  confidence    REAL NOT NULL DEFAULT 1.0 CHECK (confidence BETWEEN 0 AND 1),
  sensitivity   TEXT NOT NULL DEFAULT 'normal' CHECK (sensitivity IN
                 ('normal','sensitive','private')),
  content_enc   BLOB,            -- §11: ciphertext when sensitivity='private'
  source_kind   TEXT NOT NULL CHECK (source_kind IN
                 ('stated','observed','vault','web','rule','consolidation')),
  source_detail TEXT NOT NULL,   -- url | vault path#anchor | rule:{id} | invocation id
  source_quote  TEXT,            -- original wording where applicable
  reason        TEXT NOT NULL CHECK (length(reason) > 0),
  created_by    TEXT NOT NULL,   -- principal: 'kang' | 'rule:{id}' | 'agent:{id}' | 'plugin:{id}'
  created_at    TEXT NOT NULL, updated_at TEXT NOT NULL,
  device_id     TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
  importance    REAL NOT NULL DEFAULT 0.5 CHECK (importance BETWEEN 0 AND 1),
  pinned        INTEGER NOT NULL DEFAULT 0 CHECK (pinned IN (0,1)),
  last_accessed TEXT, access_count INTEGER NOT NULL DEFAULT 0,
  embedding_ver INTEGER REFERENCES embedding_version(ver),  -- NULL = not yet embedded
  CHECK (sensitivity <> 'private' OR (content = '[encrypted]' AND content_enc IS NOT NULL))
);

-- Change capture (07 §4.1 third duty, §5.6). D5: the update trigger's OF
-- list and the fields diff both name every column except last_accessed
-- and access_count — a statistics-only write emits no row and never
-- bumps a synchronizable field.
CREATE TRIGGER trg_memory_record_capture_insert AFTER INSERT ON memory_record
BEGIN
  INSERT INTO change_log (entity, entity_id, op, fields, revision, device_id, at)
  VALUES ('memory_record', NEW.id, 'insert', NULL, NEW.revision, NEW.device_id,
          NEW.updated_at);
END;

CREATE TRIGGER trg_memory_record_capture_update AFTER UPDATE OF
  id, type, status, content, trust_tier, confidence, sensitivity, content_enc,
  source_kind, source_detail, source_quote, reason, created_by, created_at,
  updated_at, device_id, revision, importance, pinned, embedding_ver
ON memory_record
BEGIN
  INSERT INTO change_log (entity, entity_id, op, fields, revision, device_id, at)
  SELECT 'memory_record', NEW.id, 'update',
         (SELECT json_group_array(name) FROM (
            SELECT 'id'            AS name WHERE OLD.id            IS NOT NEW.id
            UNION ALL SELECT 'type'          WHERE OLD.type          IS NOT NEW.type
            UNION ALL SELECT 'status'        WHERE OLD.status        IS NOT NEW.status
            UNION ALL SELECT 'content'       WHERE OLD.content       IS NOT NEW.content
            UNION ALL SELECT 'trust_tier'    WHERE OLD.trust_tier    IS NOT NEW.trust_tier
            UNION ALL SELECT 'confidence'    WHERE OLD.confidence    IS NOT NEW.confidence
            UNION ALL SELECT 'sensitivity'   WHERE OLD.sensitivity   IS NOT NEW.sensitivity
            UNION ALL SELECT 'content_enc'   WHERE OLD.content_enc   IS NOT NEW.content_enc
            UNION ALL SELECT 'source_kind'   WHERE OLD.source_kind   IS NOT NEW.source_kind
            UNION ALL SELECT 'source_detail' WHERE OLD.source_detail IS NOT NEW.source_detail
            UNION ALL SELECT 'source_quote'  WHERE OLD.source_quote  IS NOT NEW.source_quote
            UNION ALL SELECT 'reason'        WHERE OLD.reason        IS NOT NEW.reason
            UNION ALL SELECT 'created_by'    WHERE OLD.created_by    IS NOT NEW.created_by
            UNION ALL SELECT 'created_at'    WHERE OLD.created_at    IS NOT NEW.created_at
            UNION ALL SELECT 'updated_at'    WHERE OLD.updated_at    IS NOT NEW.updated_at
            UNION ALL SELECT 'device_id'     WHERE OLD.device_id     IS NOT NEW.device_id
            UNION ALL SELECT 'revision'      WHERE OLD.revision      IS NOT NEW.revision
            UNION ALL SELECT 'importance'    WHERE OLD.importance    IS NOT NEW.importance
            UNION ALL SELECT 'pinned'        WHERE OLD.pinned        IS NOT NEW.pinned
            UNION ALL SELECT 'embedding_ver' WHERE OLD.embedding_ver IS NOT NEW.embedding_ver
         )),
         NEW.revision, NEW.device_id, NEW.updated_at;
END;

CREATE TRIGGER trg_memory_record_capture_delete AFTER DELETE ON memory_record
BEGIN
  INSERT INTO change_log (entity, entity_id, op, fields, revision, device_id, at)
  VALUES ('memory_record', OLD.id, 'delete', NULL, OLD.revision, OLD.device_id,
          strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
END;

-- ----------------------------------------------------------------- memory_revision
-- 07 §5.1 verbatim (edit history, Memory §8.2). FK targets memory_record's
-- UNIQUE text column (id), not its rowid — SQLite enforces a FK against
-- any UNIQUE column, not only the declared PRIMARY KEY.
CREATE TABLE memory_revision (
  record_id  TEXT NOT NULL REFERENCES memory_record(id) ON DELETE CASCADE,
  revision   INTEGER NOT NULL,
  content    TEXT NOT NULL,
  edited_by  TEXT NOT NULL, edited_at TEXT NOT NULL,
  PRIMARY KEY (record_id, revision)
);

-- Insert-only capture (revisions are append-only; ADR-048 D3). device_id
-- is not a memory_revision column (07's own DDL) — derived from the
-- owning memory_record row; see the header note above.
CREATE TRIGGER trg_memory_revision_capture_insert AFTER INSERT ON memory_revision
BEGIN
  INSERT INTO change_log (entity, entity_id, op, fields, revision, device_id, at)
  VALUES ('memory_revision', NEW.record_id, 'insert', NULL, NEW.revision,
          (SELECT device_id FROM memory_record WHERE id = NEW.record_id),
          NEW.edited_at);
END;

-- ------------------------------------------------------------ memory_candidate_queue
-- 07 §5.1 verbatim — quarantine (D1: the only home of a candidate). No
-- sync quartet, no capture trigger, no index — operational, never
-- synchronized (ADR-005's own shape); its consumers (approval-queue list,
-- janitor) arrive in later slices.
CREATE TABLE memory_candidate_queue (
  id TEXT PRIMARY KEY,                  -- UUIDv7 — becomes the record's id
                                         --   on approval (ADR-048 D1)
  payload      TEXT NOT NULL,           -- full proposed record as JSON
  flags        TEXT NOT NULL DEFAULT '[]',  -- ['near_duplicate','conflict']
  flag_context TEXT,                    -- ids of dup/conflict counterparts
  proposed_at  TEXT NOT NULL, expires_at TEXT NOT NULL,   -- +14d
  resolved     TEXT CHECK (resolved IN ('approved','edited','rejected','expired')),
  resolved_at  TEXT
);

-- ------------------------------------------------------------------------ episode
-- 07 §5.1, D2 (rowid). No candidate state (D1) — episodes are written by
-- registered rules or Kang (06 §4.1) and never queue.
CREATE TABLE episode (
  rowid      INTEGER PRIMARY KEY,       -- D2
  id         TEXT NOT NULL UNIQUE,
  type       TEXT NOT NULL CHECK (type IN
              ('plan','review','retrospective','session','decision')),
  occurred_at TEXT NOT NULL,      -- event time (distinct from created_at)
  content    TEXT NOT NULL,       -- structured JSON body, type-specific schema
  summary    TEXT,                -- human-readable one-liner for lists
  status     TEXT NOT NULL DEFAULT 'active' CHECK (status IN
              ('active','compressed','archived')),
  compressed_into TEXT REFERENCES episode(id),   -- abstraction pass (Memory §6.1)
  source_kind TEXT NOT NULL, source_detail TEXT NOT NULL,
  reason TEXT NOT NULL, created_by TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  device_id TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
  embedding_ver INTEGER REFERENCES embedding_version(ver)
);

-- Change capture: no access-statistics columns exist here, so a bare
-- AFTER UPDATE (0001's shape) is exact, not an approximation of D5.
CREATE TRIGGER trg_episode_capture_insert AFTER INSERT ON episode
BEGIN
  INSERT INTO change_log (entity, entity_id, op, fields, revision, device_id, at)
  VALUES ('episode', NEW.id, 'insert', NULL, NEW.revision, NEW.device_id,
          NEW.updated_at);
END;

CREATE TRIGGER trg_episode_capture_update AFTER UPDATE ON episode
BEGIN
  INSERT INTO change_log (entity, entity_id, op, fields, revision, device_id, at)
  SELECT 'episode', NEW.id, 'update',
         (SELECT json_group_array(name) FROM (
            SELECT 'id'              AS name WHERE OLD.id              IS NOT NEW.id
            UNION ALL SELECT 'type'            WHERE OLD.type            IS NOT NEW.type
            UNION ALL SELECT 'occurred_at'     WHERE OLD.occurred_at     IS NOT NEW.occurred_at
            UNION ALL SELECT 'content'         WHERE OLD.content         IS NOT NEW.content
            UNION ALL SELECT 'summary'         WHERE OLD.summary         IS NOT NEW.summary
            UNION ALL SELECT 'status'          WHERE OLD.status          IS NOT NEW.status
            UNION ALL SELECT 'compressed_into' WHERE OLD.compressed_into IS NOT NEW.compressed_into
            UNION ALL SELECT 'source_kind'     WHERE OLD.source_kind     IS NOT NEW.source_kind
            UNION ALL SELECT 'source_detail'   WHERE OLD.source_detail   IS NOT NEW.source_detail
            UNION ALL SELECT 'reason'          WHERE OLD.reason          IS NOT NEW.reason
            UNION ALL SELECT 'created_by'      WHERE OLD.created_by      IS NOT NEW.created_by
            UNION ALL SELECT 'created_at'      WHERE OLD.created_at      IS NOT NEW.created_at
            UNION ALL SELECT 'updated_at'      WHERE OLD.updated_at      IS NOT NEW.updated_at
            UNION ALL SELECT 'device_id'       WHERE OLD.device_id       IS NOT NEW.device_id
            UNION ALL SELECT 'revision'        WHERE OLD.revision        IS NOT NEW.revision
            UNION ALL SELECT 'embedding_ver'   WHERE OLD.embedding_ver   IS NOT NEW.embedding_ver
         )),
         NEW.revision, NEW.device_id, NEW.updated_at;
END;

CREATE TRIGGER trg_episode_capture_delete AFTER DELETE ON episode
BEGIN
  INSERT INTO change_log (entity, entity_id, op, fields, revision, device_id, at)
  VALUES ('episode', OLD.id, 'delete', NULL, OLD.revision, OLD.device_id,
          strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
END;

-- --------------------------------------------------------------------- vault_note
-- 07 §5.3 verbatim. Derived table (truth = the Markdown files) — no
-- change-capture trigger (07 Appendix A).
CREATE TABLE vault_note (
  path TEXT PRIMARY KEY,             -- vault-relative, forward slashes
  title TEXT, mtime TEXT NOT NULL, size INTEGER NOT NULL,
  content_hash TEXT NOT NULL,        -- change detection
  indexed_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'indexed' CHECK (status IN
    ('indexed','stale','missing'))   -- 'missing' drives broken-link flow (Memory XIV-5)
);

-- -------------------------------------------------------------------- vault_chunk
-- 07 §5.3, D2 (rowid). Derived — no change-capture trigger.
CREATE TABLE vault_chunk (
  rowid      INTEGER PRIMARY KEY,     -- D2
  id         TEXT NOT NULL UNIQUE,
  note_path TEXT NOT NULL REFERENCES vault_note(path) ON DELETE CASCADE,
  anchor TEXT,                       -- heading anchor
  seq INTEGER NOT NULL,              -- order within note
  content TEXT NOT NULL,             -- the excerpt text (derived copy, rebuildable)
  token_est INTEGER NOT NULL,
  embedding_ver INTEGER REFERENCES embedding_version(ver),
  UNIQUE (note_path, seq)
);

-- -------------------------------------------------------------------------- link
-- 07 §5.4 verbatim; type enum copied from 06 §9.1 verbatim (13 values).
CREATE TABLE link (
  id TEXT PRIMARY KEY,
  src_kind TEXT NOT NULL, src_id TEXT NOT NULL,   -- ('memory','episode','project',
  dst_kind TEXT NOT NULL, dst_id TEXT NOT NULL,   --  'task','competition','goal',
  type TEXT NOT NULL CHECK (type IN               --  'note','conversation','person')
    ('relates_to','derived_from','supersedes','superseded_by','contradicts',
     'about_project','about_competition','about_goal','about_person',
     'references_note','from_conversation','evidence_for','evidence_against')),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','broken','retired')),
  created_by TEXT NOT NULL, created_at TEXT NOT NULL, reason TEXT,
  device_id TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
  UNIQUE (src_kind, src_id, dst_kind, dst_id, type)
);

-- Change capture: `link` is synchronizable (07 §5.4), 0001's shape.
CREATE TRIGGER trg_link_capture_insert AFTER INSERT ON link
BEGIN
  INSERT INTO change_log (entity, entity_id, op, fields, revision, device_id, at)
  VALUES ('link', NEW.id, 'insert', NULL, NEW.revision, NEW.device_id,
          NEW.created_at);
END;

CREATE TRIGGER trg_link_capture_update AFTER UPDATE ON link
BEGIN
  INSERT INTO change_log (entity, entity_id, op, fields, revision, device_id, at)
  SELECT 'link', NEW.id, 'update',
         (SELECT json_group_array(name) FROM (
            SELECT 'id'         AS name WHERE OLD.id         IS NOT NEW.id
            UNION ALL SELECT 'src_kind'   WHERE OLD.src_kind   IS NOT NEW.src_kind
            UNION ALL SELECT 'src_id'     WHERE OLD.src_id     IS NOT NEW.src_id
            UNION ALL SELECT 'dst_kind'   WHERE OLD.dst_kind   IS NOT NEW.dst_kind
            UNION ALL SELECT 'dst_id'     WHERE OLD.dst_id     IS NOT NEW.dst_id
            UNION ALL SELECT 'type'       WHERE OLD.type       IS NOT NEW.type
            UNION ALL SELECT 'status'     WHERE OLD.status     IS NOT NEW.status
            UNION ALL SELECT 'created_by' WHERE OLD.created_by IS NOT NEW.created_by
            UNION ALL SELECT 'created_at' WHERE OLD.created_at IS NOT NEW.created_at
            UNION ALL SELECT 'reason'     WHERE OLD.reason     IS NOT NEW.reason
            UNION ALL SELECT 'device_id'  WHERE OLD.device_id  IS NOT NEW.device_id
            UNION ALL SELECT 'revision'   WHERE OLD.revision   IS NOT NEW.revision
         )),
         NEW.revision, NEW.device_id, NEW.created_at;
END;

CREATE TRIGGER trg_link_capture_delete AFTER DELETE ON link
BEGIN
  INSERT INTO change_log (entity, entity_id, op, fields, revision, device_id, at)
  VALUES ('link', OLD.id, 'delete', NULL, OLD.revision, OLD.device_id,
          strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
END;

-- -------------------------------------------------------------------- link_index
-- 07 §5.4 verbatim, WITHOUT ROWID — nothing keys on its rowid, no trigger.
CREATE TABLE link_index (
  src TEXT NOT NULL, dst TEXT NOT NULL,   -- composite refs 'kind:id' / 'note:path'
  type TEXT NOT NULL,
  origin TEXT NOT NULL CHECK (origin IN ('link','wikilink','fk')),
  PRIMARY KEY (src, dst, type, origin)
) WITHOUT ROWID;

-- ------------------------------------------------------------------ message rebuild
-- ADR-048 D2: message gains the rowid alias fts_message's content_rowid
-- binds to. The 0016 table-recreate pattern (ADR-024): new table,
-- order-preserving copy regardless of row count, drop, rename, recreate
-- the index that died with the dropped table.
CREATE TABLE message_new (
  rowid INTEGER PRIMARY KEY,
  id TEXT NOT NULL UNIQUE,
  conversation_id TEXT NOT NULL REFERENCES conversation(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('kang','kang_system','agent')),
  content TEXT NOT NULL, at TEXT NOT NULL
);

INSERT INTO message_new (id, conversation_id, role, content, at)
  SELECT id, conversation_id, role, content, at FROM message ORDER BY rowid;

DROP TABLE message;
ALTER TABLE message_new RENAME TO message;

-- Consumer: ConversationStore.recent_messages — oldest-first paging
-- back through one conversation's own transcript (07 §5.5, unchanged).
CREATE INDEX idx_message_conversation_at ON message(conversation_id, at);

-- ---------------------------------------------------------------------------- FTS5
-- 07 §6.1: external-content mode, no text duplication, identical pattern
-- across all four tables except fts_memory's private exclusion. Each
-- content_rowid='rowid' binds to D2's explicit column. SQLite triggers
-- have no IF — the private condition is expressed as INSERT ... SELECT
-- ... WHERE for each branch (07 §6.1 / ADR-048 D3).

CREATE VIRTUAL TABLE fts_memory USING fts5(
  content, content='memory_record', content_rowid='rowid',
  tokenize = 'porter unicode61'
);

CREATE TRIGGER trg_fts_memory_insert AFTER INSERT ON memory_record
WHEN NEW.sensitivity <> 'private'
BEGIN
  INSERT INTO fts_memory(rowid, content) VALUES (NEW.rowid, NEW.content);
END;

CREATE TRIGGER trg_fts_memory_update AFTER UPDATE OF content, sensitivity ON memory_record
BEGIN
  INSERT INTO fts_memory(fts_memory, rowid, content)
    SELECT 'delete', OLD.rowid, OLD.content WHERE OLD.sensitivity <> 'private';
  INSERT INTO fts_memory(rowid, content)
    SELECT NEW.rowid, NEW.content WHERE NEW.sensitivity <> 'private';
END;

CREATE TRIGGER trg_fts_memory_delete AFTER DELETE ON memory_record
BEGIN
  INSERT INTO fts_memory(fts_memory, rowid, content)
    SELECT 'delete', OLD.rowid, OLD.content WHERE OLD.sensitivity <> 'private';
END;

CREATE VIRTUAL TABLE fts_episode USING fts5(
  content, content='episode', content_rowid='rowid',
  tokenize = 'porter unicode61'
);

CREATE TRIGGER trg_fts_episode_insert AFTER INSERT ON episode
BEGIN
  INSERT INTO fts_episode(rowid, content) VALUES (NEW.rowid, NEW.content);
END;

CREATE TRIGGER trg_fts_episode_update AFTER UPDATE OF content ON episode
BEGIN
  INSERT INTO fts_episode(fts_episode, rowid, content) VALUES ('delete', OLD.rowid, OLD.content);
  INSERT INTO fts_episode(rowid, content) VALUES (NEW.rowid, NEW.content);
END;

CREATE TRIGGER trg_fts_episode_delete AFTER DELETE ON episode
BEGIN
  INSERT INTO fts_episode(fts_episode, rowid, content) VALUES ('delete', OLD.rowid, OLD.content);
END;

CREATE VIRTUAL TABLE fts_chunk USING fts5(
  content, content='vault_chunk', content_rowid='rowid',
  tokenize = 'porter unicode61'
);

CREATE TRIGGER trg_fts_chunk_insert AFTER INSERT ON vault_chunk
BEGIN
  INSERT INTO fts_chunk(rowid, content) VALUES (NEW.rowid, NEW.content);
END;

CREATE TRIGGER trg_fts_chunk_update AFTER UPDATE OF content ON vault_chunk
BEGIN
  INSERT INTO fts_chunk(fts_chunk, rowid, content) VALUES ('delete', OLD.rowid, OLD.content);
  INSERT INTO fts_chunk(rowid, content) VALUES (NEW.rowid, NEW.content);
END;

CREATE TRIGGER trg_fts_chunk_delete AFTER DELETE ON vault_chunk
BEGIN
  INSERT INTO fts_chunk(fts_chunk, rowid, content) VALUES ('delete', OLD.rowid, OLD.content);
END;

CREATE VIRTUAL TABLE fts_message USING fts5(
  content, content='message', content_rowid='rowid',
  tokenize = 'porter unicode61'
);

CREATE TRIGGER trg_fts_message_insert AFTER INSERT ON message
BEGIN
  INSERT INTO fts_message(rowid, content) VALUES (NEW.rowid, NEW.content);
END;

CREATE TRIGGER trg_fts_message_update AFTER UPDATE OF content ON message
BEGIN
  INSERT INTO fts_message(fts_message, rowid, content) VALUES ('delete', OLD.rowid, OLD.content);
  INSERT INTO fts_message(rowid, content) VALUES (NEW.rowid, NEW.content);
END;

CREATE TRIGGER trg_fts_message_delete AFTER DELETE ON message
BEGIN
  INSERT INTO fts_message(fts_message, rowid, content) VALUES ('delete', OLD.rowid, OLD.content);
END;

-- Index any pre-existing content (07 §6.1). fts_message is the only one
-- that can be non-empty this migration (message predates 0020); the
-- other three are empty — harmless, keeps the migration uniform.
INSERT INTO fts_memory(fts_memory) VALUES ('rebuild');
INSERT INTO fts_episode(fts_episode) VALUES ('rebuild');
INSERT INTO fts_chunk(fts_chunk) VALUES ('rebuild');
INSERT INTO fts_message(fts_message) VALUES ('rebuild');
