import EmptyState from "../common/EmptyState";

/**
 * Know domain (09_UI §2/UI-001, §6 Memory Browser). `src/kang/domain/
 * memory/` and `src/kang/domain/vault/` are both empty stubs — the
 * 06_MEMORY infrastructure the Memory Browser is the UI half of doesn't
 * exist yet at this phase.
 */
export default function KnowScreen() {
  return (
    <EmptyState
      label="Know"
      heading="Know"
      message="The memory and vault domains have no backend yet — the Memory Browser has nothing real to show until 06_MEMORY's storage layer exists."
    />
  );
}
