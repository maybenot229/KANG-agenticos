-- 0023_embedding_v1_int8_index.sql — the int8 kNN companion for embedding
-- version 1 (ADR-057 D1/D2). `vec_memory_v1` stays the version's lossless
-- float32 store (DB-004); this table is the index search reads, because
-- exact float kNN over the 10-year corpus missed 07 Part XIV's 250 ms
-- hybrid-fetch budget (ADR-056 D1's trigger, fired by ADR-057).
--
-- Constitutional home: docs/adr/057-int8-knn-index.md, ADR-055 D4 (the
-- invalidation rule this mirrors), 07_DATABASE §6.2, DB-004.
--
-- Quantization: each vector is divided by its own largest absolute component
-- (1 if all are zero), then `vec_quantize_int8(·, 'unit')`. Cosine distance is
-- unchanged by that scaling; without it a real nomic-embed-text vector
-- (components within ±0.17) would use ~43 of the 256 levels (ADR-057 F1).
CREATE VIRTUAL TABLE vec_memory_v1_i8 USING vec0(
  record_rowid INTEGER PRIMARY KEY,
  embedding int8[768] distance_metric=cosine
);

-- Backfill from every existing float vector, in SQL — nothing is re-embedded.
-- Element order is pinned by ORDER BY inside the aggregate.
INSERT INTO vec_memory_v1_i8 (record_rowid, embedding)
SELECT f.record_rowid,
       vec_quantize_int8(vec_f32((
         SELECT json_group_array(
                  e.value / (SELECT coalesce(nullif(max(abs(x.value)), 0), 1)
                             FROM vec_each(f.embedding) x)
                  ORDER BY e.rowid)
         FROM vec_each(f.embedding) e)), 'unit')
FROM vec_memory_v1 f;

-- Invalidation, mirroring 0022's triggers for vec_memory_v1 exactly
-- (ADR-057 D2): the two tables are written together and deleted together.
CREATE TRIGGER trg_vec_memory_v1_i8_delete AFTER DELETE ON memory_record
BEGIN
  DELETE FROM vec_memory_v1_i8 WHERE record_rowid = OLD.rowid;
END;

CREATE TRIGGER trg_vec_memory_v1_i8_invalidate
AFTER UPDATE OF content, sensitivity, status ON memory_record
WHEN NEW.content IS NOT OLD.content
  OR NEW.sensitivity IS NOT OLD.sensitivity
  OR NEW.status NOT IN ('active', 'under_review')
BEGIN
  DELETE FROM vec_memory_v1_i8 WHERE record_rowid = NEW.rowid;
END;
