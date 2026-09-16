# ADR-046 — Multi-turn chat: a real `conversation`/`message` store

**Status:** accepted (2026-09-16)
**Date:** 2026-09-16
**Supersedes:** none
**Affected documents:** `07_DATABASE.md` §5.5 (a dated clarifying comment on the already-specified `conversation`/`message` DDL — resolving a real gap found while grounding this, not a schema change)
**Cites:** ADR-044 (`chat.send`, stateless this slice, D6/Consequences explicitly naming multi-turn history as undecided future work), 06_MEMORY §1.3 ("Conversation transcripts | History (queryable, but untrusted raw material) | Conversation store, retention-limited" — NOT memory, so none of this needs the write gate), 06_MEMORY §7.1/§9.1 (90-day retention; `from_conversation` link type, "survives transcript purge as id-only" — Phase 2, not this slice), 07_DATABASE §5.5 (`docs/07_DATABASE.md:530-540`, the already-specified `conversation`/`message` DDL this ADR implements, not invents), DB-003 (UUIDv7 identity; `job_run`/`model_call` named as the local-only exemption — `conversation`/`message` are not named there either way)
**Related:** [[044-basic-chat-agent.md]]

---

## Context

ADR-044 shipped `chat.send` deliberately stateless server-side, naming multi-turn history as its own future design question — not decided, not built blind. Kang asked for it directly this session.

**The schema is not new work — it already exists, fully specified, in `07_DATABASE.md` §5.5:**

```sql
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
```

This ADR's job is to implement that schema and wire it into `chat.send` — not to design a new one.

**A real gap found while grounding this, not assumed from the schema alone:** `conversation`/`message` use `TEXT` (UUIDv7-shaped) primary keys, which DB-003 says are for "every synchronizable entity" — yet neither table carries the sync quartet (`device_id`/`revision`) Part X §1 requires of "every synchronizable row," and neither is named in DB-003's own local-only exemption list (`job_run`, `model_call` — both `INTEGER PRIMARY KEY`, confirmed by reading their real migrations). The doc is internally ambiguous: TEXT id says "synchronizable," missing quartet columns say "local-only," and neither named list settles it either way.

**Resolved here, not routed around:** conversation transcripts are explicitly non-memory, retention-purged (90 days, 06_MEMORY §7.1), single-writer, append-only (a `message` row is never edited once written; `conversation`'s own mutable fields — `message_count`, `last_message` — are monotonic bookkeeping, never a field two devices would race to edit differently). That is not the shape sync-quartet conflict resolution exists for. But `conversation.id` still needs to be a stable, UUIDv7-shaped identity — `from_conversation` (06_MEMORY §9.1) is a real, if Phase-2, future reference from a memory record to a conversation id that "survives transcript purge as id-only," which only works if that id lives in the same identity space every other entity's id does, not a local integer rowid. **Decision: `conversation`/`message` are a third category DB-003's own binary doesn't yet name — UUIDv7 identity for stable cross-reference, but explicitly exempt from the sync quartet because they are single-writer/append-only/retention-purged, not conflict-resolution candidates.** A dated comment goes on the real DDL in `07_DATABASE.md` recording this, the same way migration 0018's own header named its deviation rather than copying blindly.

## Decision

### D1 — The schema, as already specified, migrated as-is (migration 0019)

No column changes. The dated clarifying comment (D-above) lands in `07_DATABASE.md` §5.5 and in the migration file itself, mirroring `0018_model_call.sql`'s own precedent for naming a deviation rather than silently matching or silently diverging.

### D2 — A new domain port: `ConversationStore`

```
Conversation: id, started, last_message, title: str | None, message_count, purged: bool
Message: id, conversation_id, role, content, at
MESSAGE_ROLES = ("kang", "kang_system", "agent")

ConversationStore (Protocol):
  start(conversation_id, started_at) -> Conversation
  get(conversation_id) -> Conversation | None
  append_message(conversation_id, message_id, role, content, at) -> Message
      # also bumps conversation.message_count/last_message, one transaction
  recent_messages(conversation_id, limit) -> tuple[Message, ...]
```

Real adapter `adapters/sqlite/conversation_store.py`; fake `adapters/fakes/conversation_store.py`; contract-paired per 13 §2.3 (`tests/fixtures/conversation_store_contract.py`, run against both).

### D3 — `role="kang_system"` is what a degraded reply uses — its own real, resolved meaning, not left unused

The schema's third role value has never been assigned meaning anywhere in this codebase. Decided here: a genuine model-generated reply is `role="agent"`; the chat agent's own `degradation` text (AGP-8, "never an invented reply") is `role="kang_system"` — a real system notice about what happened, not the agent speaking, and not hidden from the transcript either (a real degraded exchange is still real history, not something to omit on the next turn).

### D4 — `chat.send`: server mints `conversation_id` on a first call, never accepts a client-chosen one for creation

Matches this codebase's own existing convention (`deadline.create`, `task.create`, ... — the server always mints ids via `new_id()`, never a client-supplied one for creation). `chat.send`'s request gains `conversation_id: str | None = None`: omitted starts a new conversation (server mints, returns it); present must name an existing conversation (unknown id → `invalid_request`, never a silent create-under-that-id, which would break the minting convention). Response gains `conversation_id: str` — always present, either freshly minted or echoed.

### D5 — `run_cognitive_agent` gains a `history` parameter; stays a pure, non-persisting single-exchange executor

```
run_cognitive_agent(agent, message, context_chips, history: tuple[Message, ...], deps) -> AgentRunResult
```

`history` is formatted into the prompt (persona / prior transcript, oldest→newest / current context chips / Kang's new message) — the executor still does no I/O beyond `deps.route`/`deps.read_prompt`, matching its existing design exactly. **Conversation lifecycle (resolve-or-create, fetch history, persist the exchange) is NOT this executor's job** — it belongs to `model_wiring.py::make_chat_run`'s own closure, which already plays the composition role of gluing the agent registry, Router, and now the `ConversationStore` together. Persistence order: Kang's own message is appended *before* the model call (a crash mid-call still records what Kang actually said); the reply (or degradation) is appended *after*.

History is capped at the last 20 messages — a plain count cap, not a token-budget-aware truncation (that is Phase-2 Context-Assembler territory, 06_MEMORY's own real recipe mechanism `chat`'s own recipe stays deferred to). Named as a known simplification, not hidden.

## Consequences

- **Real multi-turn conversations, for the first time anywhere in the running system.**
- **Two things stay explicitly unbuilt, both named:** the 90-day retention/purge janitor pass (`conversation_days=90`, memory_steward's own future mechanical work, Phase 2/whenever memory_steward gets a real trigger) and any UI-facing `conversation.list`/`message.list` read API (PRD's own "Conversation history" system view, not asked for this slice). Neither is silently assumed solved.
- **FTS search over `message.content`** (`fts_message`, named in `07_DATABASE.md:608`) also stays unbuilt — deep search across chat history is real, later, Phase-2-adjacent work.
- **A real, dated clarification lands in `07_DATABASE.md`**, not a silent guess left for a future session to re-discover the same ambiguity.

## Verification

**Implemented and verified (2026-09-16), same day as acceptance.** What landed: migration `0019_conversation.sql` (the schema exactly as already specified, plus the dated D1 comment); `domain/ports/conversation_store.py` (`Conversation`, `Message`, `MESSAGE_ROLES`, `ConversationNotFound`, `ConversationStore`); `adapters/sqlite/conversation_store.py` + `adapters/fakes/conversation_store.py`, contract-paired via `tests/fixtures/conversation_store_contract.py`; `agents/runtime/executor.py` gains `history` on `run_cognitive_agent`'s own prompt composition, plus `ChatTurnDeps`/`run_chat_turn` — the conversation-lifecycle orchestration `run_cognitive_agent` itself deliberately does not own; `chat.send`'s schema/handler/wiring all gain `conversation_id` end to end (`api/schemas/chat.py`, `api/operations/chat_ops.py` — converts `ConversationNotFound` to `invalid_request`, the one domain-port exception `api` may legally import — and `kernel/runtime/model_wiring.py`, whose `make_chat_run` grew a 7th parameter and was bundled into a new `ChatWiringDeps` dataclass per 11 §4 rather than left over the hard limit).

The dated clarifying comment landed in `07_DATABASE.md` in two places: DB-003's own decision text (a one-sentence pointer to the real resolution) and directly above the `conversation`/`message` DDL in §5.5 (the full argument).

Proven, not assumed: the shared `ConversationStoreContract` (10 tests: start/get/append/recent-messages, an unknown-conversation append refusing, the limit keeping the newest messages, two conversations staying independent) runs identically against `FakeConversationStore` and `SqliteConversationStore` — the latter with 2 more integration-only tests (messages survive a reopen; deleting a conversation cascades to its messages, confirmed against the real DDL's own `ON DELETE CASCADE`). `agents/runtime/executor.py`'s test file grew from 13 to 20 tests: `run_cognitive_agent`'s history composition (oldest-first ordering, provably; "(none yet)" when empty, never an omitted section) plus `run_chat_turn`'s own 5 (mints a conversation when none is given; raises `ConversationNotFound` for an unknown one; persists Kang's message then the reply, in order; a degraded reply persists as `role="kang_system"`, never `"agent"`; continuing a conversation genuinely includes its own prior turn's real reply text in the next prompt). `chat_ops.py`'s test file grew from 3 to 4 (the new one: `ConversationNotFound` converts to `invalid_request`).

Live-verified beyond pytest, as a real throwaway `%KANG_HOME%` with the real shipped config and no real credential set: a first `chat.send` call mints a conversation and the real `conversation`/`message` tables show `message_count=2` (Kang's message + the degraded reply, persisted as `role="kang_system"`); a second call with that same `conversation_id` appends two more (`message_count=4`) — genuinely the same conversation, not a new one; an unknown `conversation_id` is genuinely refused (`invalid_request`, `"no conversation 'totally-made-up-id'"`). Throwaway home deleted after.

Full suite: **1078 passed** (up from 1050 — 28 new test items, confirmed exactly by collection count, no silent coverage loss). Full lint suite: 0 hard violations (`make_chat_run`'s own 7-parameter hard violation, found mid-implementation, fixed with `ChatWiringDeps`, never bumped). Import contracts: 8/8 kept, no new exemption needed. Zero network, zero model calls anywhere in the automated suite (13_TESTING §1).
