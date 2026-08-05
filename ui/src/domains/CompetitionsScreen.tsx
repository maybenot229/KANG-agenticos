import EmptyState from "../common/EmptyState";

/**
 * Competitions domain (09_UI §2/UI-001). Same finding as dashboard Zone 4
 * (`zones/Opportunities.tsx`): `src/kang/domain/competitions/` is an
 * empty stub, and the Scout/discovery pipeline that would populate this
 * domain is `03_ROADMAP.md`'s Phase 2 (M7) objective, not built yet by
 * design.
 */
export default function CompetitionsScreen() {
  return (
    <EmptyState
      label="Competitions"
      heading="Competitions"
      message="The competitions domain has no backend yet — tracking and discovery are both later-phase work (Phase 2 of the roadmap)."
    />
  );
}
