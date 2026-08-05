import EmptyState from "../common/EmptyState";

/**
 * Projects domain (09_UI §2/UI-001). `src/kang/domain/projects/` is an
 * empty stub (`__init__.py` only, no service, no store, no operation) —
 * an honest gap, not a bug: nothing to route to yet.
 */
export default function ProjectsScreen() {
  return (
    <EmptyState
      label="Projects"
      heading="Projects"
      message="The projects domain has no backend yet — no store, no service, no operation exists to show anything real here."
    />
  );
}
