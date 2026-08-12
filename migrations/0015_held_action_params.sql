-- 0015_held_action_params.sql — held_action gains `params`, the schema
-- delta ADR-001's Consequences called "owed... applied by the
-- follow-through PR", finally applied by ADR-021 (job.enable/job.disable,
-- the first real consequential operation).
--
-- Constitutional home: docs/adr/001-held-action-crash-semantics.md
-- (Consequences: "record the effect linkage... so recovery and `explain`
-- can confirm completion" — the missing half was the original request's
-- params, without which nothing can replay an approved action's effect
-- at all), docs/adr/021-held-action-first-consequential-operation.md.
--
-- A plain ADD COLUMN suffices (unlike 0005's full table rebuild, which
-- was forced by a CHECK-constraint change SQLite cannot ALTER in place —
-- this migration touches no CHECK). Same "no live rows to backfill"
-- precedent 0005 established: the feature has no live callers yet (12_API
-- §7 handlers unwired until this ADR), so a constant default is exact,
-- not a guess at historical data.

ALTER TABLE held_action ADD COLUMN params TEXT NOT NULL DEFAULT '{}';
