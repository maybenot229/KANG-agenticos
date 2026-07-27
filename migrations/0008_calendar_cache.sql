-- 0008_calendar_cache.sql — the calendar read stub's backing table.
--
-- Constitutional home: 07_DATABASE §5.2 (calendar_cache, verbatim), 18 §3 M5
-- ("calendar-read stub"), 02_PRD §12 (the provider is the truth).
--
-- DERIVED, and therefore deliberately WITHOUT the sync quartet: the truth
-- lives at the calendar provider, and this table is rebuildable by
-- re-fetching (07 §1.4.1 — derived data is rebuildable, never authoritative).
-- Same reasoning that kept the quartet off `notification` (ADR-005), reached
-- from the other direction: that one is per-device operational state, this
-- one is a cache of somebody else's truth. Neither replicates.
--
-- M5 builds the READ path only. Calendar WRITE is v0.2 (02_PRD §15's version
-- table) and is a consequential action (05 Appendix D) when it arrives, so
-- it will need a held-action path and a commit_mode — not a column here.
-- Nothing populates this table yet; the Planner reads it and correctly sees
-- an empty day, which is the honest behaviour with no provider configured.

CREATE TABLE calendar_cache (       -- DERIVED (truth = provider, PRD §12); rebuildable
  provider_event_id TEXT PRIMARY KEY,
  calendar_id TEXT NOT NULL, title TEXT, starts TEXT, ends TEXT,
  all_day INTEGER NOT NULL DEFAULT 0, fetched_at TEXT NOT NULL
);

-- Consumer: the Planner's per-day lookup (v_today_* shape, 07 §4.1) — the
-- only query this table has. Index doctrine (07 Part VI): cites its consumer.
CREATE INDEX idx_calendar_starts ON calendar_cache(starts);
