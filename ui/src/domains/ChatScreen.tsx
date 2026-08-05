import EmptyState from "../common/EmptyState";

/**
 * Chat domain (09_UI §2/UI-001, §5 Agent Interaction Surfaces). No
 * `chat.*` operation is registered, no model router exists, no agents
 * exist — conversational access is entirely Phase 2 (M7) scope
 * (`03_ROADMAP.md`), not a gap in this milestone's build.
 */
export default function ChatScreen() {
  return (
    <EmptyState
      label="Chat"
      heading="Chat"
      message="Conversational access has no backend yet — the model router and agents are later-phase work (Phase 2 of the roadmap)."
    />
  );
}
