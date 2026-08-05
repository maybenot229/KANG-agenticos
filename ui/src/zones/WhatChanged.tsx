import EmptyState from "../common/EmptyState";

/**
 * Zone 3 — "What changed?" (09_UI §4): completed/new items digest since
 * last visit, overnight agent activity summary (one line + link to §12
 * Audit). No digest or activity-log query operation exists in the
 * registry today (`kang.api.registry.OPERATIONS` has no such entry) —
 * this is an honest gap, not a bug: building a real digest means new
 * domain-level aggregation, not just exposing an existing store method
 * the way Zone 2's `deadline.list` did.
 */
export default function WhatChanged() {
  return (
    <EmptyState
      label="What Changed"
      heading="What Changed"
      message="Activity digest not yet available — no operation exists yet to summarize what changed since your last visit."
    />
  );
}
