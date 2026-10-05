-- 0022_embedding_v1.sql — embedding version 1 and its vector tables
-- (ADR-055 D4; ADR-054 D1). The first migration that needs sqlite-vec:
-- `open_connection` loads and verifies it before any migration runs
-- (ADR-055 D3), so `vec0` is always available here.
--
-- Constitutional home: docs/adr/055-embeddings-slice.md D4/D5,
-- docs/adr/054-embedding-model-and-dimension.md D1, 07_DATABASE Part VIII
-- DB-004 (the `embedding_version` protocol: one table per version, never
-- mixed), §6.2 (vec tables are derived; built by the embedding worker),
-- DB-003's dated clarification (vec tables bind to the storage-local rowid
-- alias ADR-048 D2 landed for exactly this purpose).
--
-- 1. Version 1 is registered HERE, not by configuration: a model change is
--    always a reviewed migration (ADR-055 D4). `providers.toml` only says
--    which provider serves it; the worker refuses to store a vector whose
--    model or dimension disagrees with this row (D6).
INSERT INTO embedding_version (ver, model, dim, created_at, status)
VALUES (1, 'nomic-embed-text', 768, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
        'active');

-- 2. All three v1 tables together — ADR-048 D3's precedent for fts_*: no
--    one-off shape the others must later match. Only vec_memory_v1 has a
--    producer in this slice. Cosine, because 06 §5.2's semantic term is
--    cosine similarity.
CREATE VIRTUAL TABLE vec_memory_v1 USING vec0(
  record_rowid INTEGER PRIMARY KEY,
  embedding float[768] distance_metric=cosine
);
CREATE VIRTUAL TABLE vec_episode_v1 USING vec0(
  record_rowid INTEGER PRIMARY KEY,
  embedding float[768] distance_metric=cosine
);
CREATE VIRTUAL TABLE vec_chunk_v1 USING vec0(
  record_rowid INTEGER PRIMARY KEY,
  embedding float[768] distance_metric=cosine
);

-- 3. Invalidation by trigger; creation never (ADR-055 D4, Finding 3).
--    07 §6.2 forbids triggers doing I/O — computing a vector is I/O;
--    deleting one is a single-row delete in this file, exactly what the
--    fts_* triggers already do. A trigger sees every writer: the store's
--    lifecycle methods, the recovery applier's replay, and future janitor
--    transitions. Retrievable = 'active' or 'under_review' (06 Part III:
--    an under_review record is "still retrievable but marked contested").
CREATE TRIGGER trg_vec_memory_v1_delete AFTER DELETE ON memory_record
BEGIN
  DELETE FROM vec_memory_v1 WHERE record_rowid = OLD.rowid;
END;

CREATE TRIGGER trg_vec_memory_v1_invalidate
AFTER UPDATE OF content, sensitivity, status ON memory_record
WHEN NEW.content IS NOT OLD.content
  OR NEW.sensitivity IS NOT OLD.sensitivity
  OR NEW.status NOT IN ('active', 'under_review')
BEGIN
  DELETE FROM vec_memory_v1 WHERE record_rowid = NEW.rowid;
END;

CREATE TRIGGER trg_vec_episode_v1_delete AFTER DELETE ON episode
BEGIN
  DELETE FROM vec_episode_v1 WHERE record_rowid = OLD.rowid;
END;

CREATE TRIGGER trg_vec_episode_v1_invalidate AFTER UPDATE OF content ON episode
WHEN NEW.content IS NOT OLD.content
BEGIN
  DELETE FROM vec_episode_v1 WHERE record_rowid = NEW.rowid;
END;

CREATE TRIGGER trg_vec_chunk_v1_delete AFTER DELETE ON vault_chunk
BEGIN
  DELETE FROM vec_chunk_v1 WHERE record_rowid = OLD.rowid;
END;

CREATE TRIGGER trg_vec_chunk_v1_invalidate AFTER UPDATE OF content ON vault_chunk
WHEN NEW.content IS NOT OLD.content
BEGIN
  DELETE FROM vec_chunk_v1 WHERE record_rowid = NEW.rowid;
END;
