-- 0018_model_call.sql — the usage & cost ledger (D010, ADR-038), the
-- Model Router's own write path.
--
-- Constitutional home: 07_DATABASE §5.5 (`model_call`'s schema,
-- `docs/07_DATABASE.md:520-528`), 05_AGENTS AG-008 ("every call lands in
-- model_call"), docs/adr/038-model-router-taskspec.md D4.
--
-- Local-only ledger, `INTEGER PRIMARY KEY` rowid (07_DATABASE §5.1:
-- "job_run, model_call MAY use INTEGER PRIMARY KEY rowids") — no
-- `revision`/`device_id`, no change_log capture trigger: this table never
-- syncs and has no concurrent-writer conflict to detect, the same
-- reasoning `job_run` (0003_scheduler.sql) already used.
--
-- Deviation from 07_DATABASE's own written schema, named rather than
-- copied blindly: `invocation_id TEXT REFERENCES agent_invocation(id)
-- ON DELETE SET NULL` is OMITTED here. `agent_invocation` (07 §5.5's own
-- agent-specific projection) is not yet migrated — ADR-038 D1 scopes the
-- real agent runtime out of this slice — and `PRAGMA foreign_keys=ON`
-- (every real connection, `connection.py`) makes SQLite refuse even a
-- NULL-valued insert against a REFERENCES clause naming a table that
-- does not exist (confirmed empirically before writing this migration,
-- not assumed): every `model_call` row would fail to insert from the
-- Router's very first real call. The column returns, with its FK, in
-- the migration that creates `agent_invocation` — additive, per this
-- project's own migration discipline, not a redesign.

CREATE TABLE model_call (            -- usage & cost ledger (D010)
  id INTEGER PRIMARY KEY,            -- local-only: rowid fine (DB-003)
  provider TEXT NOT NULL, model TEXT NOT NULL, task_class TEXT NOT NULL,
  tokens_in INTEGER NOT NULL, tokens_out INTEGER NOT NULL,
  cost_usd REAL NOT NULL DEFAULT 0, latency_ms INTEGER NOT NULL,
  outcome TEXT NOT NULL CHECK (outcome IN ('ok','error','timeout','fallback')),
  at TEXT NOT NULL
);

-- Consumer: the health panel's spend-vs-caps view (AG-008), the future
-- budget-ledger slice's own threshold reads.
CREATE INDEX idx_modelcall_at ON model_call(at);
