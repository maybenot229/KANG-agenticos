import EmptyZone from "./EmptyZone";

/**
 * Zone 4 — "What opportunities exist?" (09_UI §4): filtered digest of
 * competitions found and relevant findings, batched. This depends on the
 * Scout/discovery pipeline, which `03_ROADMAP.md`'s Phase 2 (M7) objectives
 * name explicitly — it architecturally does not exist yet by design, not
 * by oversight (`src/kang/domain/competitions/` is an empty stub). Not
 * built ahead of the infrastructure it needs (18 §1.4).
 */
export default function Opportunities() {
  return (
    <EmptyZone
      label="Opportunities"
      heading="Opportunities"
      message="Discovery pipeline not built yet (Phase 2 of the roadmap) — nothing to surface here until it exists."
    />
  );
}
