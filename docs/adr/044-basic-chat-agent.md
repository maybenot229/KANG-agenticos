# ADR-044 — Basic chat: Appendix A's 16th agent, zero tools, sync, client-supplied context

**Status:** accepted (2026-09-16)
**Date:** 2026-09-16
**Supersedes:** none
**Affected documents:** `05_AGENTS.md` Appendix A (adds a 16th catalog row — a real amendment, not an implementation of an existing one, unlike ADR-040/041/042/043); `12_API.md` API-007 (a narrow, argued, timeout-bounded exception — see D6)
**Cites:** 03_ROADMAP Phase 1 ("chat with basic context"; "Intentionally postponed: all cognitive agents *beyond basic chat*" — the phrase this ADR takes at face value: chat is the one cognitive agent Phase 1 does NOT postpone), 02_PRODUCT_REQUIREMENTS §10.13 (FR-081/082, Tier 1), 09_UI_DESIGN.md:89 (the Chat domain's own contract: "the current context... is visible as removable chips"), 06_MEMORY.md:464 ("Chat (general)" recipe row — Phase 2, explicitly NOT this ADR's mechanism, see D4), 05_AGENTS §1.2/AG-004/AG-005 (the registered-agent model this ADR extends, not bypasses), ADR-041 (the mechanical executor's own shape, mirrored here for cognitive agents), ADR-038/039 (`Router`/`AnthropicProvider`, both built and tested against fakes, neither wired into `Core` until this ADR)
**Related:** [[040-agent-registry.md]], [[041-mechanical-agent-executor.md]], [[043-deadline-sweep-agent-envelope-routing.md]]

---

## Context

Two forks were asked and answered directly by Kang this session (not defaulted): chat is a real, registered agent — Appendix A's 16th row, not a bypass of the agent model — and this ADR should attempt a genuinely reduced version now rather than deferring to Phase 2.

**What "reduced" turned out to mean, found while grounding this against real code, not assumed from the PRD's own fuller description:**

1. **No agent named "chat" exists anywhere.** `05_AGENTS.md`'s Appendix A — the normative 15-agent catalog ADR-040 D4 completed — has no chat row. The only "chat" mention there is as an *invocation-trigger class* ("User-initiated (sync)"), not a registered definition. This ADR adds the row itself, in the same PR as the code (CLAUDE.md §6).
2. **No cognitive-agent executor exists.** ADR-041 built `run_mechanical_agent` — mechanical only, and it structurally refuses `kind="cognitive"`. Nothing runs a cognitive agent's own primary action (a model call) today.
3. **`Router`/`AnthropicProvider` are built, tested, and wired into nothing.** ADR-038 shipped the Router fully tested against a fake; ADR-039 shipped the real Anthropic adapter, explicitly noting "nothing calls this adapter with a schema yet (the Router isn't wired into `Core` at all)." `Core` has no Router today.
4. **"Today's plan" has no query operation.** `02_PRD §10.13`'s "context-aware conversation (knows... today's plan)" implies reading it — but the API registry has only `plan.generate` (a command, computes/persists a NEW plan) and no `plan.get`/`plan.today` query. Re-deriving "the plan" server-side inside chat's own handler would mean either triggering `plan.generate`'s own side effect just to read a value (wrong — a read must never carry a write's effect) or reaching into `PlanService`/`task_store` directly from an API handler, duplicating logic ADR-027's own "unscoped reads" precedent didn't need to invent because a real query already existed for its case. Neither is honest "basic" scope.
5. **`ModelProvider.call()`'s prompt is one flat string** — no separate system/user channel at the port level (confirmed reading `AnthropicProvider.call()`: `messages=[{"role": "user", "content": prompt}]`, once). A cognitive agent's own persona (`prompt_file`, the same field `critic`/`planner` already carry, unread by any code until now) has to be composed into that one string by whatever executor calls it.

**Finding 4 resolves cleanly against something already decided, not invented here:** `09_UI_DESIGN.md:89` already describes the Chat domain's own real contract — "the current context (today's plan, active entity) is visible as removable chips — Kang always sees what KANG sees." The chips are already the UI's own job: it queries whatever it needs to render them, and Kang can remove one before sending. **Decided here (D4): "basic context" is exactly those chips, supplied by the client in the request, never re-derived server-side.** This needs no new query operation, triggers no side effect, and is what the UI's own already-written contract already implies — not a new mechanism, a narrower reading of an existing one.

## Decision

### D1 — `chat` joins Appendix A as agent #16 (cognitive, zero tools, zero escalation)

```
id: "chat"
kind: "cognitive"
mandate: "Converse with Kang using client-supplied context chips; no
          tool access or specialist escalation yet."
triggers: ["kang"]                 # User-initiated (sync) ONLY — never
                                    # scheduled, never chained
tools: []                          # AG-005's zero-tools case, critic's
                                    # own precedent — no tool-loop exists
                                    # to use a non-empty allowlist yet
scopes: []                         # calls no operation itself this slice
timeout_s: 60                      # one real model call's own budget
retry: 0                           # a generation isn't safely re-run
                                    # (matches researcher's own retry=0)
degradation: "Chat is unavailable — <the real ProviderUnavailable/
              NoProviderAvailable reason>, never an invented reply"
recipe: null                       # Phase-2 concept (06_MEMORY's own
                                    # "Chat (general)" row) — captured,
                                    # not resolved, same restraint every
                                    # other definition already uses
pipelines: []
prompt_file: "prompts/system.md"   # first draft, matching critic/
                                    # planner's own "not tuned" precedent
escalation: null
```

Ships under `agents/definitions/chat/chat.toml` + `agents/definitions/chat/prompts/system.md`, loaded by the existing, unmodified `agent_definitions_loader.py`/`build_checked_registry` — no schema change to `AgentDefinition` itself; this is data, matching ADR-040 D4's own remaining-agents shape.

### D2 — A cognitive-agent executor, mirroring ADR-041's mechanical one

`agents/runtime/executor.py` gains `run_cognitive_agent(agent, message, context_chips, deps) -> AgentRunResult`:

- Refuses (new `MechanicalAgentNotSupported`) if `agent.kind != "cognitive"` — the exact mirror of `run_mechanical_agent`'s own `CognitiveAgentNotSupported`, before any model call.
- Refuses (new `CognitiveToolLoopNotSupported`) if `agent.tools` is non-empty — no tool-calling loop exists yet (AG-005's allowlist has nothing to enforce against without one); a future agent declaring tools needs that loop built first, not a silent ignore of its own declared capability.
- Reads `agent.prompt_file`'s contents (the persona) + formats `context_chips` into a labeled block + appends `message` — one flat string, because that is what `ModelProvider.call()` actually accepts (Finding 5).
- Calls `Router.route(TaskSpec(task_class="deep_reasoning", privacy_tier="normal", context_size=len(prompt)//4, latency_tolerance="interactive"), prompt)`. `task_class="deep_reasoning"`: chat's own honest-pushback persona (PRD §10.13: "Kang gets pushback when ideas are weak") needs a capable model, not the cheap classification tier. `privacy_tier="normal"` always, this slice — a known simplification, named: nothing classifies message sensitivity yet (that's Phase 2/3 territory); worth revisiting once anything does.
- On `ProviderUnavailable`/`NoProviderAvailable`: returns `agent.degradation`'s own text with a `degraded=True` flag (AGP-8 — never an invented reply). On `ProviderRefused`: propagates — a malformed request or bad credential is a real bug/config problem, not a degradable runtime condition (mirrors the Router's own retry/refusal split).
- Mints a session for principal `agent:chat`, `first_party=False` — **no special case**: an earlier draft of this ADR considered running chat as Kang's own first-party session (reasoning: "it's Kang's own conversation"), and that was wrong, caught before being written into code. `agent:chat` stays a normal, bounded agent principal exactly like every other one (SEC-003/ADR-002) — PRD's "consequential proposals inside chat MUST break out into the §7 dialog" is satisfied by *that* mechanism (a held action / live confirmation token needing Kang's own real first-party approval) once chat ever proposes one, not by chat quietly inheriting Kang's own wildcard `*` grant. Moot for zero tools today, load-bearing the moment chat gets its first one.

### D3 — `chat.send`: a new, `first_party_only`, unscoped command

```
"chat.send": command, scope=None, idempotent=false,
  channel=OperationChannel(first_party_only=True),
  request: {message: str (non-empty), context_chips: list[str] = []}
  response: {reply: str, degraded: bool}
```

`first_party_only=True`: matches 05_AGENTS's own "User-initiated (sync)" framing — chat is triggered by Kang's own hand, never scheduled, never chained (ADR-002's own channel-control field, checked independently of scope). `scope=None`: chat.send calls no capability-gated operation itself — it calls the Router, which is not in the operations registry at all (`ModelCall`'s own ledger row carries no principal/scope, confirmed reading `router.py`) — the same "a decision, not a default" posture ADR-027 already established for unscoped reads, applied here to an unscoped *conversation*. `idempotent=false`: two identical messages may legitimately get two different (model-generated) replies; nothing here is safely re-playable by key the way a deterministic domain write is.

### D4 — "Basic context" is exactly the client's own chips (see Finding 4/Context above)

No server-side context assembly this slice. `context_chips: list[str]` arrives verbatim from the request, is formatted into the prompt (labeled, not silently merged into `message` where it could be mistaken for Kang's own words), and nothing else. Explicitly **not** `06_MEMORY`'s "Chat (general)" recipe (Phase 2, blocked on Memory, per ADR-040's own already-established restraint) — that recipe becomes the real mechanism later; this is a deliberately narrower stand-in, named as such so it is never mistaken for the real thing.

### D5 — `Router` wired into `Core` for the first time, fail-open (unlike `AgentRegistry`'s fail-closed boot)

`composition.py` builds: `KeyringCredentialStore()` → `AnthropicProvider(credentials)`; `providers_loader.load_providers_config(kang_home / "config" / "providers.toml")`; `SqliteModelCallStore(kang)`; `Router(config, {"anthropic": AnthropicProvider(...)}, calls, clock)` — exposed as `Core.router`.

**Fail-open, not fail-closed, and deliberately the opposite of ADR-043 D1's posture for `AgentRegistry`:** `providers.toml` is a live, hand-editable, `%KANG_HOME%`-scoped file (D003) — Kang might genuinely edit or typo it, and ADR-038 D5 already decided its own fail-closed shape *for the Router's own routing decisions* ("an absent/invalid file yields the empty `ProvidersConfig`... every task class routes to nothing... never a default-open try-everything") — composition wiring reuses that existing loader behavior verbatim rather than bricking boot over it, the same `_load_grants`-style reasoning ADR-043 D1 argued in the other direction for code-shipped, never-hand-edited agent definitions. Constructing `KeyringCredentialStore`/`AnthropicProvider` never touches the network or the keychain itself (confirmed: `keyring.get_password` is called lazily, inside `.call()`, never at construction) — so this wiring is safe to always build, whether or not Kang has ever set a real credential.

### D6 — A narrow, argued, timeout-bounded exception to API-007's "blocking long calls MUST NOT exist"

**Named honestly, not slipped past quietly.** API-007: "Any operation that cannot reliably complete in < 3 s... MUST be modeled as: command → returns `invocation_id` immediately → progress via the event channel... Chat streaming is this same mechanism with a text-chunk stream." `chat.send` violates the letter of this today: it blocks synchronously for the duration of one real model call (bounded by the chat agent's own `timeout_s=60`), returning the full reply in one response — no `invocation_id`-then-poll, no streaming.

**Why this is the honest scope, not a shortcut:** the general async invocation-resource mechanism API-007 describes (return now, progress later) has never been built for *any* operation in this codebase — every operation today, `deadline.sweep` included, already executes synchronously within one `dispatch()` call, just off the request's own event-loop thread via the write-executor (ADR-036). Building the real return-now/poll-later mechanism generically is separate, larger work API-007 itself anticipates as its own future need (pipelines, long research runs) — not something to bolt on as a side effect of chat's own first cognitive call, and not something Kang asked for when this session's own reduced-scope framing (his own words: "non-streaming, sync-only, no cancellation") was put to him. **This ADR's own boundary:** `chat.send` blocks, bounded by a real, already-established timeout mechanism (matching every agent's own `timeout_s`), never unboundedly. The general async mechanism stays named, explicit future work — not this ADR's job, and not silently assumed solved.

## Consequences

- **Chat becomes real and callable** — the first cognitive agent, the first real (non-fake) model call anywhere in the running system, the first time `AgentDefinition.prompt_file` is ever actually read into a call.
- **A genuine, documented departure from API-007's letter**, argued above (D6) rather than hidden — `12_API.md` gets a dated note citing this ADR, not a silent contradiction for a future session to puzzle over.
- **Zero persistence of conversation history this slice.** Each `chat.send` call is stateless server-side; multi-turn continuity is the client's own job (resending prior turns inside `message` itself) until a real `history`/`conversation` mechanism is designed — named, not built blind.
- **Zero tool-calling, zero specialist escalation.** `06_MEMORY`'s own "Chat (general)... escalates to a specialist recipe when routed (D011)" stays exactly that — a future capability, not this slice's.
- **`privacy_tier` is always `"normal"`** — a named simplification; nothing classifies message sensitivity yet.

## Verification

**Implemented and verified (2026-09-16), same day as acceptance.** What landed: `agents/definitions/chat/{chat.toml,prompts/system.md}` (agent #16); `run_cognitive_agent`/`CognitiveExecutorDeps`/`RouterRoute` + `MechanicalAgentNotSupported`/`CognitiveToolLoopNotSupported` (`agents/runtime/executor.py`, `domain/ports/agent_definition.py`); `api/schemas/chat.py` (`ChatSendRequest`/`ChatSendResponse`) + `api/operations/chat_ops.py` (`make_chat_send_handler`, a plain `ChatRun` callable — `api` may not import `kang.agents`); the `chat.send` registry entry (`scope=None`, `first_party_only=True`, `idempotent=False`, per D3); a new `kernel/runtime/model_wiring.py` (`build_router`, `make_chat_run`) — split out of `composition.py` when this slice's own Router/chat wiring pushed that file's line count past the size lint's hard limit, the same ADR-023/037 trigger, needing its own `tools/importlinter.toml` entries (adapters+agents) mirroring the other three composition-root files.

Two hard size-lint violations turned up mid-implementation (composition.py's own 800-line file limit, and `_build_core_locked`'s 80-line function limit) — both split, never bumped: the model-wiring split handled the file limit; a new `_build_dispatcher_deps` helper handled the function limit.

**05_AGENTS.md Appendix A and 12_API.md updated in the same PR** (CLAUDE.md §6): a new `chat` row in Appendix A's table; a dated note under API-007 citing this ADR's D6 exception, so the departure is documented at its source, not only in the ADR.

Proven, not assumed: `unit/kang/agents/runtime/test_executor.py` (7 new test functions, 8 test items with one parametrized): refuses a mechanical agent or a non-empty `tools` allowlist before any route call; composes persona+chips+message into one flat prompt, provably (a fake `RouterRoute` capturing the call); returns the real reply on success; degrades to `agent.degradation` text with `degraded=True` on both `ProviderUnavailable` and `NoProviderAvailable`, never inventing a reply; propagates `ProviderRefused` uncaught; mints a non-first-party `agent:chat` session, no special case. `unit/kang/api/test_chat_operations.py` (3 tests): the handler passes `message`/`context_chips` through verbatim, defaults missing chips to `[]`, and returns the injected callable's response unmodified. `unit/kang/api/registry/test_registry.py` (1 new test: `chat.send`'s own `scope`/`first_party_only`/`idempotency` shape; the unscoped-operations set test now covers four operations, not three). `unit/kang/adapters/config/test_agent_definitions_loader.py` and the pipeline-registry/agent-registry tests updated for the real 16-agent count.

Live-verified beyond pytest, as a real throwaway `%KANG_HOME%` with the real shipped `providers.toml`/`permissions.toml`/`kang.toml`, a real `build_core()`, no real credential set (confirmed empty on this machine before this ADR was written, and still empty after): `Core.agent_registry` holds all 16 real agents including `chat`; `Core.router` is real; a real `chat.send` dispatch through the real dispatcher degrades honestly (`{"reply": <the agent's own degradation text>, "degraded": true}`, never a fabricated reply); the real `invocation` row for `chat.send` records principal `kang` (the actual caller); a session for `kernel:scheduler` (non-first-party) attempting `chat.send` is genuinely refused (`first_party_required`); a blank `message` is genuinely refused by the schema (`invalid_request`, `field_errors`) — proving the whole chain end to end without a real network call or any Anthropic spend. Throwaway home deleted after.

Full suite: **1050 passed** (up from 1038 — 12 new test items, no silent coverage loss). Full lint suite: 0 hard violations (both violations named above fixed, not bumped). Import contracts: 8/8 kept, two new ignore-imports entries added and justified inline (`model_wiring.py -> adapters/agents`). Zero network, zero model calls anywhere in the automated suite (13_TESTING §1) — the one real Anthropic call this ADR could have made never happened, by construction (no credential exists).
