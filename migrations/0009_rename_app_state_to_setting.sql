-- 0009_rename_app_state_to_setting.sql — correct the app_state/setting drift.
--
-- Constitutional home: 07_DATABASE §5.5 (`setting` — key, value, updated_at
-- — verbatim shape, unchanged by this migration).
--
-- This is a doc/code conformance fix, not a new design decision: §5.5 has
-- named `setting` throughout, unamended, since before 0003 was written.
-- 0003's header claimed "07 §5.5 (job, job_run, app_state — verbatim
-- shapes)" — that claim was false. 0003 introduced `app_state`; §5.5
-- specifies `setting`. 0003 is historical and applied (07 Part XIII.4:
-- frozen, not edited in place); this migration corrects the drift going
-- forward rather than rewriting history.
--
-- Shape is identical to app_state's — this is a rename, not a redesign.
-- SQLite has no ALTER TABLE ... RENAME TO that also lets us reason about it
-- explicitly here, but the standard forward-only pattern (07 Part XIII) is
-- used regardless, so the migration reads the same as any other: create the
-- correctly-named table, migrate rows, drop the old one.

CREATE TABLE setting (               -- runtime-mutable UI/system state ONLY
  key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL
);  -- Config truth stays in TOML (D003). setting holds window layouts,
    -- last-seen markers, product state — and the automation kill-switch.

INSERT INTO setting (key, value, updated_at)
  SELECT key, value, updated_at FROM app_state;

DROP TABLE app_state;
