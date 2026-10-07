# ADR-058 — The Context Assembler, first cut: a kernel-owned, deterministic, scope-enforced assembly for chat, with a content-free manifest on the invocation row

**Status:** accepted (2026-10-07) — **under Kang's delegated acceptance, not his own read** (2026-10-07: "continue with the next slice, i give u 3 hours, dont ask me anything", following the 2026-10-05 delegation "accept everything by urself"; his review to follow). Drafted, accepted and implemented by the architect session. The seventh Phase 2 slice — 18 §4's order puts the Context Assembler + manifests directly after hybrid retrieval, and its byte-identical manifest proof is a named Phase 2 gate (03 §3, 18 §4).
**Date:** 2026-10-07
**Supersedes:** none. Extends ADR-044/046 (chat): chat's prompt gains memory context; `ChatRun` gains the correlation id.
**Affected documents:** 06_MEMORY §5.4 and Part XI (dated notes — what is built); 05_AGENTS AG-009 (dated note); 12_API §12 (dated note — `explain.invocation` now returns a real manifest for chat); `config/defaults/memory.toml` (`[assembly]`); `config/defaults/permissions.toml` (`agent:chat` gains `memory.read:chat-view`); `src/kang/agents/assembly/` (new data directory: recipes); `src/kang/agents/definitions/chat/chat.toml` (`recipe`); the chat prompt; `tests/suites/CLAIMS.md`.
**Cites:** 06 §5.1 (two regimes), §5.2 (the scorer), §5.4 (the manifest: "logged with the invocation's correlation id"; agent-facing format `[MEM:id] content — source, date, tier`), §12.1/§12.2 (sensitivity, `memory.read:{view}` grants, default-deny), Part XI (recipes are config, versioned, logged; P0–P4 budget model; unused budget cascades downward; truncation bottom-up, always recorded; P0 never truncated), Appendix A (`[assembly] budget_shares`); 05 §3 phase 3 ("built per the agent's recipe; logged before the first model call. No agent constructs its own context"), AG-009 (deterministic given recipe version, query, snapshot; filter order; score desc then id asc), AGP-5 (small context), §16 Context suite; 13 §2.6 ("same store snapshot + same recipe ⇒ byte-identical context manifest"), §2.16 (manifest completeness); ADR-056 (the scorer and search halves, reused); 17 §4.3 (composition root).

---

## Context

Every piece the assembler needs now exists — the scorer, both retrieval halves, the int8 index, an invocation row with an empty `manifest` column (migration 0004), and `explain.invocation`, which already returns that column. What does not exist is the component that decides what an agent sees. Chat, the one cognitive agent, still receives only Kang's chips and the last 20 messages (ADR-046's named simplification, "Phase-2 Context-Assembler territory"). Four findings shaped the cut:

**Finding 1 — the manifest can be content-free, and should be.** 06 §5.4's manifest fields are ids, score terms, tiers and token counts; 06 §12.1 requires sensitive records "redacted in logs/manifests (ids only)". Storing no content at all makes the 180-day "content→ids-only" pruning unnecessary for these manifests and keeps Kang's words out of the invocation table — the query is recorded by hash, the records by id.

**Finding 2 — chat holds no memory grant.** `agent:chat` has `scopes = []`. 06 §12.2 makes memory reads default-deny per principal and view. An assembler that read memory for chat without a grant would be the "agent exceeds its scopes" failure AG-009 exists to prevent — so chat gets an explicit, reviewable grant, and the assembler checks it.

**Finding 3 — the correlation id does not reach chat's closure.** The dispatcher starts the invocation row before the handler runs, keyed by correlation id, but `ChatRun` is `(message, chips, conversation_id)`. The manifest must land on *that* row (05 §14: trigger → manifest → calls → outcome under one id).

**Finding 4 — of the five priority classes, two have something to put in them.** P1 (rules, pinned, profile/preference) and P2 (scored semantic) are fed by memory records. P0's deterministic queries per recipe, P3 vault excerpts and P4 episodes have no producer yet.

---

## Options

**1 — Where the assembler lives.** **1A — `kernel/context/` (its constitutional home, already a placeholder), with the budgeting and manifest construction as pure domain functions. (Recommended.)** *For:* 05 §3 says "kernel infrastructure… not an agent"; the pure core makes determinism testable without a database. **1B — inside the agent runtime.** *Against:* agents may not construct their own context (05 §3), and `agents/` may not import `kernel/`.

**2 — Manifest content.** **2A — ids, scores, tiers, tokens, query hash; no content. (Recommended — Finding 1.)** **2B — 06 §5.4's shape plus record content for 180 days.** *Against:* duplicates memory content into a second table that deletion would then have to chase (06 §1.5 covenant 3).

**3 — Unbuilt classes.** **3A — build P1 and P2 now; P0/P3/P4 recorded as empty with their reason. (Recommended.)** **3B — wait for vault and episodes.** *Against:* blocks the Phase 2 determinism gate on two unrelated slices.

---

## Decision

### D1 — A kernel Context Assembler over a pure core (Option 1A)

`kernel/context/assembler.py::ContextAssembler.assemble(request)` gathers candidates through ports and returns an `Assembly` (rendered context + manifest). `domain/memory/assembly.py` holds the pure parts: filter order, budget allocation with downward cascade, truncation records, manifest construction, rendering. Agents receive the assembler as an injected callable (17 §4.2: `agents/` never imports `kernel/`).

### D2 — Recipes: shipped, versioned TOML in `src/kang/agents/assembly/`

A recipe names its `id`, `version`, `view` (the `memory.read:{view}` scope it needs), `types` (the memory types it may see), `clearance` (`normal` | `sensitive`), `tier_floor`, `confidence_floor`, `budget_tokens`, `k` (P2 candidates), and optional `weights` overrides of 06 §5.2. Shipped beside the agent definitions, never hand-edited (context is behaviour — AG-009 "behaviour changes get reviewed"); loaded at boot and validated like them. A definition's `recipe` is resolved at assembly time; definitions whose recipes do not exist yet stay unresolved, as before. First recipe: `chat-general` (06 Part XI "Chat (general): broad but shallow… defaults").

### D3 — Filters, classes, budget (AG-009 order; 06 Part XI)

Filters in AG-009's order: `status` (`active`, plus `under_review` ⚠-tagged) → sensitivity ≤ clearance (`private` never; `sensitive` only with clearance `sensitive`, which itself needs a `memory.read:sensitive` grant) → type ∈ recipe types → tier ≥ floor → confidence ≥ floor → scoring → budget. Suppressions are counted by reason in the manifest. **P1** standing context: every admissible `rule` (always), then pinned records, then `profile`/`preference`, each group ordered by id. **P2**: ADR-056's two halves and scorer with the recipe's weight overrides, score desc then id asc (AG-009's total order), excluding anything already in P1. **P0/P3/P4**: empty, each with a recorded reason (`not_built`). Budget: `budget_tokens × [assembly] budget_shares` per class (06 App A, read from `memory.toml`); unused budget cascades to the next class down; items beyond a class's allowance are truncated from the bottom and recorded. Tokens are estimated deterministically (`len(rendered line) // 4 + 1`).

### D4 — Scope enforcement before any read

The assembler asks the permission engine whether the agent's principal holds `memory.read:{recipe.view}` (and `memory.read:sensitive` if the recipe's clearance is `sensitive`). Without it, no memory is read: the assembly is empty, the manifest records `refused: "scope"`, and the agent runs on the rest of its context — a declared degradation, not a crash. `agent:chat` is granted `memory.read:chat-view` (Finding 2); the pairing lint still holds (chat has no `web.fetch`).

### D5 — The manifest: canonical, content-free, on the invocation row, before the model call (Option 2A)

Canonical JSON (sorted keys, fixed separators): `schema`, `invocation` (correlation id), `agent`, `recipe {id, version}`, `assembled_at`, `query_sha256`, `budget {tokens, by_class}`, `standing[]`, `relevance[]` (`id`, `score`, `terms`, `tier`, `tokens`), `deterministic`/`vault`/`episodic` (empty + reason), `truncated[]`, `suppressed {reason: count}`, `semantic` (`ok` | `unavailable`), `refused` (null | reason). Same recipe version, query, store snapshot, `now` and correlation id ⇒ byte-identical bytes (13 §2.6). It is written to the invocation row (`InvocationStore.attach_manifest`) before the model is called (05 §3 phase 3), so a degraded or failed turn still has one, and `explain.invocation` returns it.

### D6 — Rendering and attribution

Each included record enters the prompt as `[MEM:{id}] {content} — {source_kind}, {created_at date}, tier {n}` (06 §5.4), `under_review` ones prefixed ⚠, under a "What KANG remembers" heading; an empty assembly renders "(nothing relevant in memory)". Chat's prompt gains the attribution contract: cite `[MEM:id]` for anything drawn from memory; never present memory as certain beyond its tier. The prompt change is unevaluated (no eval harness exists — 13 §7 reserves it); stated, not hidden.

### D7 — Wiring

`ChatRun` gains the correlation id (the handler has it). `run_chat_turn` takes an optional `assemble` callable; the composition root binds it to the kernel assembler for chat's recipe and to `InvocationStore.attach_manifest`. Chat's history cap (ADR-046's 20 messages) is unchanged — conversation history is not memory (06 §1.3).

### D8 — What this does not do

No P0 recipe queries, no vault or episode classes, no `ctx` term (link layer), no recipes for the other agents, no attribution spot-checker (05 §5.4's sampled runtime check), no `memory.explain_retrieval` operation (the manifest is reachable through `explain.invocation`), no manifest pruning job (nothing to prune — D5).

---

## Consequences

**What becomes possible.** Chat answers from Kang's memory with citations; every chat turn's context is reconstructible by id from its invocation; the Phase 2 manifest-determinism gate has its proof; the remaining agents need only a recipe file and a grant.

**What becomes harder, or costs something.** Every chat turn now embeds its query (one more local model call, ledgered) and holds the writer slightly longer. A new grant exists (`memory.read:chat-view`). Recipes are a new kind of shipped file to keep valid. The manifest omits content by design, so reconstructing *what the model saw* needs the records to still exist — a deleted record's manifest entry becomes an id with no content, which is the deletion covenant working, not a bug.

**Named, not decided:** P0 recipes per agent; vault/episode classes; the attribution spot-checker; whether `under_review` records belong in chat at all (06 Part XI leaves contested material to the Critic's view).

## Verification

**Implemented 2026-10-07, same session, under the same delegation** (the work spanned an interrupted session; the code was finished and verified on 2026-10-07 evening).

- Every CI gate in `ci.yml`'s order: `ruff format --check` and `ruff check` clean; import contracts **8 kept, 0 broken**; size lint 0 hard (`composition.py` 793/800 — two lines for chat's assembler and invocation store); banned patterns, tree hygiene, root docs clean. Commit tier **1247 passed** (1215 before), integration **424 passed** (419). That commit-tier run took 6 m 38 s, alongside a live Ollama check; the run before this slice took 4 m 43 s. 13 §3's < 5 min commit budget is now a real pressure — see Consequences, named here rather than hidden.
- **New suites:** the assembler (rules first, then pinned, then profile/preference; relevance from the hybrid search excluding standing records; no grant ⇒ `refused: scope` and nothing read; `sensitive` clearance needs its own grant; sensitive records suppressed and private never fetched; type/tier/confidence floors with reasons; content-free manifest; byte-identical manifests for the same inputs; unknown recipe is loud; lexical assembly when the embedder is down); the pure core (06 §5.4's line format, ⚠ for contested, cascade and bottom-up truncation, never over budget, always a prefix); `standing()` added to the `MemorySearchStore` contract on fake and real; `attach_manifest` on fake and real; the recipe loader; the executor's phase order (assemble before route; the memory section only when a recipe exists); a real-Core suite (a degraded `chat.send` still records a content-free manifest naming the rule and the relevant fact by id); and **the Phase 2 gate proof** on the year-1 corpus — two independently built assemblers over two copies of the same embedded snapshot write the same manifest bytes, and the manifest is not empty.
- **A defect found by the suite, fixed before commit:** a sensitive `rule` matched by both the standing read and the search was counted twice in `suppressed`; each record is now judged once.
- **Two pinned tests updated, citing this ADR:** `chat.send`'s handler tests (the `ChatRun` correlation id) and the shipped-`memory.toml` key set (`[assembly]`).
- **Live, by hand, through a real `Core` with the real local Ollama** (the chat model itself had no credential, so the turn degraded — the manifest is built before the model call): for "who can help me with the robotics deadline?" the manifest held the rule and the preference as standing context, and *Dr. Lee mentors the robotics team* (0.678) and the robotics submission deadline (0.513) as relevance; the unrelated birthday fact was left out; 119 of 1,200 tokens used; `semantic: ok`; 1,158 bytes, no record or query text.
