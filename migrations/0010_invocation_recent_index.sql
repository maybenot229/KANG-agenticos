-- 0010_invocation_recent_index.sql — index invocation(started) for the
-- System-domain Invocations view's `recent()` read (09_UI §12).
--
-- Constitutional home: 12_API §4/§12 (the invocation ledger). 0004_api.sql
-- indexed `correlation_id` only (explain.invocation's lookup shape);
-- InvocationStore.recent() orders by `started DESC, id DESC` for the
-- run-history list added 2026-08-05 — an unindexed ORDER BY here means a
-- full-table sort on every load of a table every command/query appends to
-- forever. Composite on (started, id) so the tiebreaker in the query is
-- covered too.

CREATE INDEX idx_invocation_started ON invocation(started DESC, id DESC);
