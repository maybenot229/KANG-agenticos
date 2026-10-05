# ADR-055 — The embeddings slice: one port, through the Router; `sqlite-vec` loaded at open; vectors invalidated by trigger, created by a worker; the dual-index protocol made mechanical

**Status:** accepted (2026-10-05) — **under Kang's delegated acceptance, not his own read** (2026-10-05: "accept everything by urself" for a bounded working window, his review to follow). Drafted and accepted by the architect session the same day; Options 1A / 2A / 3A as recommended, D1–D9 as written. The fifth Phase 2 slice (18 §4's order: schema → corpus → gate → **embeddings + dual-index versioning** → hybrid retrieval). Implements ADR-054 and makes the one decision ADR-054 D2 left to this slice: which port carries an embedding call. Implemented in the same session (no separate coding session this time — Kang's direction was "do everything").
**Date:** 2026-10-05
**Supersedes:** none. Amends by dated note: 07_DATABASE DB-004 (D5 — `embedding_ver` is not written; vector presence is the truth), 07 §6.2 (D4 — invalidation by trigger, creation by worker, read precisely). Carries out ADR-054's own listed dated notes (04 §20.1, DB-004, `providers.toml`, the Ollama adapter docstring, 03 §8's two rows, ADR-038).
**Affected documents (if accepted):** `pyproject.toml` (new dependency `sqlite-vec`, D3); `migrations/0022_embedding_v1.sql` (new, D4); `src/kang/domain/ports/model_provider.py` (`embed`, `EmbeddingResult`, D1); `src/kang/kernel/router/router.py` (`Router.embed`, D1); `src/kang/adapters/ollama/` (the adapter, D2); `src/kang/adapters/anthropic/provider.py` (`embed` refuses, D1); `src/kang/domain/ports/embedding_index.py` + `adapters/sqlite/embedding_index.py` + `adapters/fakes/embedding_index.py` (new, D6/D8); `src/kang/domain/memory/embedding.py` (the worker's policy, D7); `src/kang/adapters/sqlite/connection.py` (extension load + verify, D3); `config/defaults/providers.toml` (the embedding chain, D2); `config/defaults/permissions.toml` (`memory.embed` to `kernel:scheduler`, D7); the operation registry (`memory.embed`, D7); `scheduler_wiring.py` (the `memory_embed` job, D7); `07_DATABASE.md` DB-004 + §6.2 (dated notes); `12_API.md` §10 (dated note); `15`-free (no new event type, D7); `tests/suites/CLAIMS.md`.
**Cites:** ADR-054 D1/D2/D4/D5/D7; 04_ARCHITECTURE D010 (*"a kernel-level Model Router behind a single `ModelProvider` port"*; `embedding` one of its five classes; *"every call logged"*); 07_DATABASE §1.3 (sqlite-vec chosen over every vector store), §6.2 (*"maintained by the embedding worker (async, batched), not by triggers — embedding is I/O, and triggers doing I/O is forbidden"*), DB-003's dated clarification (the rowid alias is storage-local; vec tables bind to it), DB-004 (versioned tables, never mixed; the upgrade protocol); 06_MEMORY Part III (`candidate → active`: *"Embedding computed"*; `active/superseded → archived`: *"Removed from default retrieval + vector index"*; `under_review`: *"still retrievable"*), §1.5 covenant 3 (*"Delete removes the record, its embedding…"*), §12.1 (`private` excluded from all retrieval); 13_TESTING §2.8 (deletion covenant includes the embedding), §2.3 (fake and real run the same contract suite); 07 Part XVI ("Vector correctness: kNN sanity fixtures; version-migration protocol end-to-end"); 03_ROADMAP §3 (*"dual-index protocol tested before first real embedding"*); 18 §4 (same); 11_CODING §25/E10 (dependency justification); 17 §4.3 (composition root).

---

## Context

ADR-054 chose the model and runtime and named, without deciding, the port. Reading the code to decide it surfaced five findings, three of which change the slice's shape.

**Finding 1 — D010 already answers the port question, if read literally.** D010's decision is *"a kernel-level Model Router behind a **single** `ModelProvider` port"*, and its own diagram routes `class: embedding` through that Router. A separate embedding port would be a second door to a provider — which 05 §9 forbids for text calls (*"direct provider SDK access is architecturally absent"*) and which would lose, for embeddings, everything the Router enforces for every other class: the `privacy_tier` fail-closed filter, the fallback chain and circuit breaker, and the `model_call` ledger (AG-008: *"every call logged"*). ADR-054 D2 was right that `ModelResult` cannot carry a vector; the honest consequence is a second *method* on the one port, not a second port.

**Finding 2 — the only loadable vector engine is not installed, and nothing in the code opens a connection with it.** `sqlite-vec` is the constitution's chosen engine (07 §1.3) but has never been a dependency (`pyproject.toml`), and `adapters/sqlite/connection.py::open_connection` is the single place every `kang.db` connection is opened (`composition.py:556`, the corpus generator, every integration test). Probed on this machine 2026-10-05: `sqlite-vec` 0.1.9 loads under CPython 3.12.5's own `sqlite3` (3.45.3); `vec0` cosine kNN, rowid point-lookup and delete all work; and — load-bearing for backups — `PRAGMA integrity_check`, `VACUUM INTO` and `ATTACH` all succeed on a database containing `vec0` tables from a connection **without** the extension loaded (only touching a `vec0` table needs it). The backup paths that deliberately open snapshots with a plain `sqlite3.connect(...mode=ro)` (`backup_service.py:174`) are therefore unaffected.

**Finding 3 — 07 §6.2's "not by triggers" sentence has a reason, and the reason covers creation only.** Its stated reason is *"embedding is I/O, and triggers doing I/O is forbidden."* Computing a vector is I/O; *removing* one is a single-row delete in the same file, exactly what `fts_memory`'s triggers already do for the FTS index. And invalidation has more paths than any store method can see: `memory.update`, `memory.archive`, `memory.delete`, the recovery applier's replay of `memory.updated` (`recovery.py:450-470`, a raw `UPDATE memory_record SET …` of every field), and every future janitor transition. A trigger catches all of them; a store-method convention catches the ones its author remembered. The deletion covenant (06 §1.5: delete removes *"its embedding"*) is too important to rest on memory.

**Finding 4 — writing `memory_record.embedding_ver` would make a derived fact look like a truth mutation.** DB-004 says *"every embedded row carries `embedding_ver`."* But migration `0020`'s change-capture trigger lists `embedding_ver` among the captured columns (`0020:138-141`), so every embed would emit a `change_log` row — sync-plane noise for derived data (07 Appendix A: `vec_*` is the rebuildable set). Worse, keeping the column true would need every invalidation path above to also null it, which from inside an `AFTER UPDATE` trigger is a second, nested update with its own capture row. Two representations of "has a current vector" — the column and the vec table — is a drift waiting to happen. The vec table's own row is the fact; the column is a second copy of it.

**Finding 5 — every scheduled job runs on the single write executor, and an embedding call is slow.** `_tick_forever` submits `Scheduler.tick()` to the `WriteExecutor` (`scheduler_wiring.py:493-513`); a job's operation runs on the one writer thread. ADR-054 Finding 3 measured `nomic-embed-text` at 1.24 chunks/s on this CPU. An unbounded backfill run would hold the writer for minutes. `chat.send` already runs its model call on the same thread (ADR-044), so this is not a new class of cost — but it must be **bounded**, and the bound stated.

---

## Options

### Option 1 — Which port carries the embedding call

**1A — A second method on `ModelProvider`, `embed()`, routed by a `Router.embed()` sharing the chain, breaker, privacy filter and ledger. (Recommended.)** *For:* D010's "single port" read literally; every protection the Router gives text calls applies to embeddings for free; one provider map, one `providers.toml`. *Against:* every adapter must answer `embed()` — Anthropic has no embedding endpoint, so its answer is a typed refusal; a Protocol with two methods is wider than one.

**1B — A separate `EmbeddingProvider` port, called directly by the worker.** *For:* the narrowest interface. *Against:* a second door to a provider, outside the Router — no privacy fail-closed, no fallback, no `model_call` row; an amendment to D010's "single port" that buys nothing but a smaller Protocol.

**1C — A separate port, but the Router holds both kinds of provider.** *For:* keeps the ledger. *Against:* two provider maps and two lookups for one router — the second concept 1A avoids, for no gain.

### Option 2 — How vectors stay consistent with their rows

**2A — Invalidate by trigger (delete the vector when content, sensitivity, or retrievability changes, or the row is deleted); create by the worker. (Recommended.)** *For:* Finding 3 — every path is covered, including replay and future janitor transitions; 07 §6.2's reason is honored exactly (no I/O in a trigger). *Against:* every connection that writes `memory_record` must have `vec0` loaded (D3 makes that a property of `open_connection`).

**2B — Invalidate in each store method.** *For:* no triggers on a virtual table. *Against:* misses `recovery.py`'s replay today and any future writer tomorrow; the deletion covenant would be a convention.

### Option 3 — `memory_record.embedding_ver`

**3A — Do not write it; vector presence in `vec_memory_v{n}` is the single truth. (Recommended.)** *For:* Finding 4 — no sync noise for derived data, no second representation. *Against:* a dated deviation from DB-004's sentence; the column stays NULL and unused until a reader needs it.

**3B — Write it on embed and null it on invalidation.** *Against:* a change-captured write per embed and a nested trigger update per invalidation, to maintain a copy of a fact the vec table already holds.

---

## Decision

### D1 — Embeddings go through the Router, on the one `ModelProvider` port (Option 1A)

`ModelProvider` gains `embed(spec, model, texts) -> EmbeddingResult` (`vectors`, `model`, `tokens_in`, `cost_usd`, `latency_ms`). `Router.embed(spec, texts)` requires `spec.task_class == "embedding"` and reuses `route()`'s chain, privacy filter (`privacy_tier="private"` → `local_only` providers only, or `NoProviderAvailable`), circuit breaker and `model_call` logging (`tokens_out = 0`). The adapter echoes the `model` it served so the caller can verify it (D6). `AnthropicProvider.embed` raises `ProviderRefused` — a chain that routes `embedding` to it is a configuration bug and must not advance silently. ADR-054 D2 is thereby resolved; D010 needs no amendment.

### D2 — `OllamaProvider`: embedding only; text generation stays RESERVED

`adapters/ollama/provider.py` implements `embed` against Ollama's local `/api/embed` over stdlib `urllib` (the Router is synchronous; no new HTTP dependency), at `http://127.0.0.1:11434`. Its `call()` raises `ProviderRefused`: `private`/`routine` text generation through Ollama remains exactly as RESERVED as ADR-054 D7 left it. Unreachable server, timeout, 5xx, or a model Ollama has not pulled → `ProviderUnavailable` (this provider cannot serve now; the chain may). Other 4xx → `ProviderRefused`. The HTTP call is injected (a `post` callable) so the adapter's contract is tested without a network, per 13 §2.3. `providers.toml`'s `[task_class.embedding]` chain becomes `[{ name = "ollama", model = "nomic-embed-text", local_only = true }]`; the composition root wires `"ollama"` beside `"anthropic"`. Ollama absent is a degraded state (D7), not a crash — ADR-054 D2's consequence, built.

### D3 — New dependency: `sqlite-vec` (E10), loaded and verified at open

`sqlite-vec>=0.1.9,<0.2` (Alex Garcia's SQLite extension; MIT/Apache-2.0; prebuilt Windows wheels; no transitive dependencies; the engine 07 §1.3 already chose, so this is the paperwork, not the choice). `open_connection` loads it and verifies `vec_version()` — DB-001's own standard: a connection that cannot see `vec0` is a startup failure, never a silent degradation. *Alternatives:* a plain BLOB table with cosine in Python (no dependency; a full scan per query in an interpreted loop, ~two orders slower — and 07 §1.3 already ruled); a vector server (04 §19, rejected).

### D4 — Migration `0022`: version 1 registered, three `v1` tables, invalidation triggers (Option 2A)

- `INSERT INTO embedding_version VALUES (1, 'nomic-embed-text', 768, <now>, 'active')` — DB-004's first row; the migration, not configuration, is where a version comes into existence, so a model change is always a reviewed migration.
- `vec_memory_v1`, `vec_episode_v1`, `vec_chunk_v1`: `vec0(record_rowid INTEGER PRIMARY KEY, embedding float[768] distance_metric=cosine)` — all three together, the precedent ADR-048 D3 set for `fts_*` (no one-off shape). Only `vec_memory_v1` has a producer in this slice; episodes and vault chunks have none yet.
- Triggers delete a vector when its row is deleted; when `memory_record.content` or `.sensitivity` changes; when `memory_record.status` leaves the retrievable set (`active`, `under_review` — 06 Part III keeps `under_review` retrievable); and when `episode.content` or `vault_chunk.content` changes. No trigger creates a vector.

### D5 — `memory_record.embedding_ver` is not written; vector presence is the truth (Option 3A)

"Has a current vector in version *n*" means "has a row in `vec_memory_v{n}`". The column stays NULL. DB-004 gets a dated note naming this deviation and its reason (Finding 4). Revisit if a reader ever needs it on the row itself — none does today.

### D6 — The `EmbeddingIndex` port: versions, pending rows, guarded writes, coverage, cutover, nearest

A new port (`domain/ports/embedding_index.py`, fake + SQLite adapter, one contract suite for both) owns every `vec_*` and `embedding_version` statement. Rowids never cross it (DB-003's clarification). It exposes: the versions to fill (`active`, then `migrating`); up to *n* pending memory records for a version (retrievable, not `private`, no vector yet — newest `updated_at` first, DB-004's "hot rows first"); a **guarded** write (a vector is stored only if the row is still at the revision, status and sensitivity it was read at — a record edited mid-embed is skipped, not stored stale); coverage of a version; cutover; and `nearest_memory(version, vector, k)` for the retrieval slice and 07 Part XVI's kNN fixtures. Before storing, the worker checks the adapter-echoed `model` and every vector's length against the version row; a mismatch stores nothing and is audited (`memory.embed.mismatch`) — DB-004's "mixing versions in one vec table is forbidden", made mechanical.

### D7 — The embedding worker: `memory.embed`, bounded, run by `kernel:scheduler`

- The policy lives in the domain (`domain/memory/embedding.py`): fill each version in order, in batches, through an injected `embed` callable (`Router.embed`), with the record's own sensitivity as `privacy_tier` (`private` rows are never selected — 06 §12.1, DB-005).
- Operation `memory.embed` (command, scope `memory.embed`, granted to `kernel:scheduler` only; `kang` holds `*`). Job `memory_embed`, `every:300`, `run_once_latest`, dispatched directly under `kernel:scheduler` — it is 07 §6.2's kernel "embedding worker", not an agent mandate in 05 Appendix A, so it is not routed through an agent envelope (the precedent `held_action_expire` already set).
- **Bounded (Finding 5):** at most `EMBED_BATCH_SIZE = 8` records per run — about seven seconds of writer time at the spike's measured rate, every five minutes, only while a backlog exists. A module constant, not `memory.toml`: `memory.toml` fails closed for the gate (ADR-051 D8), and a new required key would brick an existing install's gate on upgrade. DEBT-shaped trade, stated: the writer is held during the HTTP call, as `chat.send` already does. Trigger to revisit: interactive write latency measurably suffering, or the retrieval slice needing query embeddings on the hot path.
- **Degradation, declared (A9):** `NoProviderAvailable`/`ProviderUnavailable` → the run returns `{"embedded": 0, "degraded": "provider_unavailable"}` with a warning log — an explicit marker, not an empty success, and not a job failure that would quarantine the job after a day of Ollama being closed. FTS carries retrieval meanwhile (06 XIV-6).
- No event type: vectors are derived (07 Appendix A); `kang rebuild-indexes`, not replay, is their recovery path.

### D8 — The dual-index protocol, made mechanical and tested on the corpus

The worker fills `active` first (new rows must become searchable), then any `migrating` version. When a `migrating` version's coverage reaches 100% of currently-embeddable rows, the worker cuts over in one transaction (`migrating → active`, previous `active → retired`), audited (`memory.embed.cutover`). Queries read only the `active` version, so during a migration every row is served by the old space until the new one is complete — DB-004's "no retrieval blackout". Dropping `retired` tables is a later migration's job. Creating `v2` is a migration (D4's rule); this slice proves the protocol by applying a `v2` shape in a test, on the `year1` synthetic corpus, before any real embedding — 03 §3's precondition.

### D9 — What this slice does not do

No retrieval, scoring, or query embedding (hybrid retrieval slice). No near-duplicate cosine probe at the gate (06 §4.2 — now buildable, its own slice). No episode/vault-chunk producers. No embedding cache (`cache/embeddings.db`, DB-004) — RESERVED until re-index churn makes it pay. No nomic task prefixes (`search_document:`/`search_query:`): the spike measured without them, and the decision rests on that measurement; a change is a new `embedding_version`. No health-panel surface for the degraded state (named for the health slice). No change to the gate.

---

## Consequences

**What becomes possible.** Every admitted, non-private record gains a vector within minutes when Ollama is running; the retrieval slice has a tested `nearest_memory` to score against; a model change is a migration plus background work, proven on the corpus. The deletion covenant extends to the embedding mechanically.

**What becomes harder, or costs something.** Every `kang.db` connection now loads a native extension (a startup failure if it is missing — by design). Embedding holds the single writer for up to ~7 s per run while a backlog exists. `composition.py` reaches its 800-line hard limit with this slice's one added line; the next slice that touches it must split first (ADR-053 D8's pattern). `memory_record.embedding_ver` is a named, unused column.

**Named, not decided:** the embedding cache; prefixes; the health surface for "embeddings degraded"; dropping `retired` version tables; moving the HTTP call off the writer thread.

## Verification

To be filled in by the implementing session with what was actually run.
