-- 0019_conversation.sql — chat transcript persistence (ADR-046),
-- Appendix A's `chat` agent's own first real store.
--
-- Constitutional home: 07_DATABASE §5.5 (`conversation`/`message`
-- schema, `docs/07_DATABASE.md:530-540`), 06_MEMORY §1.3 ("Conversation
-- transcripts... NOT memory... Conversation store, retention-limited"),
-- docs/adr/046-chat-conversation-history.md.
--
-- UUIDv7 TEXT identity, but NO sync quartet (device_id/revision) —
-- a third category DB-003's own binary (synchronizable-with-quartet vs.
-- local-only-INTEGER-rowid) didn't yet name, resolved and dated in
-- 07_DATABASE.md §5.5/DB-003 by this same ADR: single-writer,
-- append-only, retention-purged rows still need stable UUIDv7 identity
-- (from_conversation, §9.1, survives transcript purge as id-only) but
-- are never a field two devices would race to edit differently.

CREATE TABLE conversation (
  id TEXT PRIMARY KEY, started TEXT NOT NULL, last_message TEXT NOT NULL,
  title TEXT, message_count INTEGER NOT NULL DEFAULT 0,
  purged INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE message (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversation(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('kang','kang_system','agent')),
  content TEXT NOT NULL, at TEXT NOT NULL
);

-- Consumer: ConversationStore.recent_messages — oldest-first paging
-- back through one conversation's own transcript.
CREATE INDEX idx_message_conversation_at ON message(conversation_id, at);
