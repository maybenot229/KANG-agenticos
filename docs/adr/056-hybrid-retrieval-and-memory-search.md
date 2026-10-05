# ADR-056 — Hybrid retrieval, first cut: Kang-facing `memory.search`, the 06 §5.2 scorer as a pure function, the fetch shape measured, and query embedding pinned to the active model

**Status:** accepted (2026-10-06) — **under Kang's delegated acceptance, not his own read** (2026-10-05: "accept everything by urself" for a bounded working window, his review to follow). Drafted, accepted and implemented by the architect session the same night. The sixth Phase 2 slice (18 §4: … embeddings → **hybrid retrieval** → Context Assembler + manifests …). Decides what ADR-054 D5 left to "the retrieval slice": the hybrid fetch's shape.
**Date:** 2026-10-06
**Supersedes:** none. **Amends** ADR-055 D1 (accepted 2026-10-05): `Router.embed` gains an optional `model` pin (D6) — a dated note is appended to ADR-055, its text untouched.
**Affected documents:** `06_MEMORY.md` Part X (dated note — what is built), §5.2 (dated note — each term as built); `12_API.md` §10 (dated note — `memory.search`); `03_ROADMAP.md` §8 (dated note — the Vector DB server trigger, now measured, still not fired); ADR-054 D5 (dated note — decided here); ADR-055 D1 (dated note — amended by D6); `config/defaults/memory.toml` (`[scoring]`, `[search]`, D3); the operation registry (`memory.search`, D7); `tests/suites/CLAIMS.md`.
**Cites:** 06_MEMORY §5.1 (two regimes), §5.2 (the formula, the weights, filters before scoring, per-term logging), §7.1 (which classes are permanent), §12.1/§12.3 (sensitivity; every sensitive access audited), Part X (default/deep/structured; zero-hit honesty; < 1 s), Appendix A (`[scoring]`), §13.2 (hybrid relevance < 300 ms); 07_DATABASE Part XIV (`docs/07_DATABASE.md:848`, hybrid candidate fetch < 250 ms on the 10-year corpus), §6.1 (FTS5, `porter unicode61`); 13_TESTING §2.2 (property tests required for scoring math), §2.8 (no fabrication: store-verbatim content + ids), §4 gate 6 (no budget above 90% utilization without a filed issue); 12_API §8 (queries are side-effect-free), §10 (`memory.search` modes); D010 (privacy tiers: `private` routes local-only or fails closed); DB-004 (one space per version, never mixed); ADR-054 D5; ADR-055 D1/D5/D6.

---

## Context

ADR-054 D5 declined to read the spike's latency numbers as the "Vector DB server" trigger firing, because two things were untested: `sqlite-vec`'s quantized modes, and the fetch's own shape. This slice owns both. Four findings, all measured on Kang's machine on 2026-10-05/06:

**Finding 1 — memory search fits the budget with exact vectors, barely, at the 10-year ceiling.** The year-10 synthetic corpus holds 45,000 memory records, 39,687 of them embeddable. Exact float kNN (k=64, 768 dims, cosine) over all of them: **217–239 ms warm**. FTS k=64 and hydration of the union: under 1 ms. That is inside 07 Part XIV's 250 ms hybrid-fetch budget, at roughly 93% utilization. Quantized `int8` kNN over the same vectors: **~90 ms**. Binary (`bit[768]`) kNN: ~15 ms over 60k random vectors — but re-ranking its candidates through `vec0` point lookups cost 0.8–1.0 s, so binary-then-rerank is not usable in that form. Exact kNN is linear: ~86 ms at 15k, ~175 ms at 30k, ~342 ms at 60k (random vectors). The spike's alarming numbers were about **vault chunks** (500,000 at the ceiling) — a different table, and a different slice.

**Finding 2 — a query must be embedded by the model of the version it searches, and the Router cannot say which.** During a model migration (DB-004) `providers.toml` serves the new model to the embedding worker, while queries must keep reading the `active` space — embedded by the *old* model. ADR-055's `Router.embed` takes no model, so a query during a migration would be embedded in the wrong space. Vectors are model-bound data; the caller of an embedding is the one party that knows which space it needs.

**Finding 3 — `memory.search` is a query that writes a ledger row.** 12 §8 makes queries side-effect-free, and `query_routing` sends query operations to the read pool. But embedding the query text goes through the Router, whose `model_call` ledger (AG-008: "every call logged") writes on the write connection, and SQLite connections are thread-confined. `system.health` is already a query wired on the write executor, for a comparable reason (its dependency needs a second database).

**Finding 4 — the vector half needs no prefilter for status or privacy, by construction.** ADR-055's triggers keep `vec_memory_v1` holding only retrievable (`active`/`under_review`), non-`private` records, so "filters before scoring" (06 §5.2) is already true of the vector half for those two filters. Type and tier facets cannot be pushed into `vec0` without metadata columns; they are applied to the hydrated rows.

---

## Options

### Option 1 — Fetch shape

**1A — Independent halves, exact: vector k=64 ∪ FTS k=64, hydrate the union, filter, score. (Recommended.)** *For:* 07 Part XIV's own literal shape; semantic recall without word overlap (the reason vectors exist — in the live check, "who helps the robotics team?" found "Dr. Lee mentors the robotics team" partly through meaning); measured inside budget at the 10-year profile. *Against:* ~93% utilization at the ceiling — 13 §4 gate 6 will require a filed issue at the v0.2 boundary.

**1B — FTS candidates re-ranked by vector (ADR-054 D5's alternative).** *For:* ~64 vector comparisons, trivially fast. *Against:* a record with no word in common with the query can never be found — it discards the half of retrieval that vectors exist for.

**1C — `int8` quantization now.** *For:* ~90 ms, comfortable headroom. *Against:* a second table per version, its own invalidation triggers, and an untested recall cost — complexity paid years before the record count needs it. Today's real store holds a few dozen records.

### Option 2 — Query embedding during a migration

**2A — `Router.embed(..., model=)` filters the chain to entries serving that model. (Recommended.)** *For:* the caller states the space it needs; provider choice, privacy filter, breaker and ledger stay the Router's. During a migration `providers.toml` lists both models; the worker (unpinned) takes the first, queries pin the active one. *Against:* D010's "callers declare intent, not models" now has one stated exception — for embeddings, the model *is* part of the intent, because the vectors are only meaningful inside it.

**2B — Degrade semantic search during every migration.** *Against:* a retrieval blackout of the semantic half for the whole re-embed (DB-004 promises none).

### Option 3 — Where `memory.search` runs

**3A — Kind `query`, wired on the write executor beside `system.health`. (Recommended.)** *For:* the ledger write lands on the connection that owns it; no new dispatch machinery. *Against:* a search holds the single writer for its duration (fetch ≤ ~250 ms plus the query embedding, ~50–700 ms when the model is warm). Kang-facing search is interactive and infrequent.

**3B — A new read-pool phase split for model-calling queries.** *Against:* new dispatch machinery for one operation; `knowledge.ask` and the Context Assembler will need the same thing and should shape it.

---

## Decision

### D1 — Independent halves, exact vectors (Option 1A); `int8` is the named remedy with a trigger

Default mode fetches the 64 nearest vectors in the `active` version and the 64 best FTS hits, hydrates their union in one read, applies the facets, and scores. **Trigger for `int8`:** the nightly `test_hybrid_fetch_on_corpus.py` going red, or 13 §4 gate 6 at the v0.2 boundary — whichever comes first. The "Vector DB server" trigger (03 §8) has **not** fired: exact `sqlite-vec` meets the memory budget at the ceiling, and a 2.5× remedy inside `sqlite-vec` is measured and available.

### D2 — The scorer is 06 §5.2, as a pure domain function, every term reported

`domain/memory/retrieval.py::score_candidates(candidates, now, config, use_semantic)`. Terms as built: `sim = clamp(1 − cosine distance, 0, 1)`, 0 without a vector hit; `bm25_n` min-max normalized over this query's lexical hits (best = 1; FTS5's more-negative-is-better inverted), 0 without a hit; recency `e^(−ln 2·Δt/half_life)` from `updated_at`, no decay at half-life 0; `imp = 1.0` when pinned, else the record's `importance`; `ctx = 0` (D9). Ties break by record id; the same inputs give the same ranking to the decimal. The response carries every term before weighting — 06 §5.2's "why was this included?" for Kang now, and the shape the manifests will log later.

### D3 — `[scoring]` and `[search]` in `memory.toml`, failing closed for search only

Weights as 06 Appendix A. Half-lives must name all eight types (the taxonomy is closed): `fact` 180 and `lesson`/`rule`/`profile` 0 are 06 §5.2's own; `preference`, `relationship`, `reflection` 0 (06 §7.1 calls them permanent) and `observation` 30 (a 180-day pre-pattern signal) are this ADR's hypotheses. 06 §5.2's `episode = 30` is not shipped: episodes are not searched yet, and a key without a reader is not shipped (ADR-051's rule). Parsed separately from `[gate]`: an existing install whose `memory.toml` predates this ADR keeps its gate, and `memory.search` refuses with an error naming the fix — it never defaults.

### D4 — A match needs a lexical hit or enough similarity; everything else is at most a labeled nearest miss

`match_min_similarity = 0.5` (`[search]`), a weak, early hypothesis: in the 2026-10-05 live check related facts sat at similarity 0.61–0.75 and unrelated ones at 0.33–0.35 — four records, not a calibration. With no matches, up to three nearest misses are returned in a separate field; results are never padded (06 Part X).

### D5 — Default and deep modes; structured mode not built

Default: `active` + `under_review` (06 Part III: contested but retrievable), non-`private`, hybrid. Deep: adds `archived` + `superseded`, lexical only — semantic weight 0, and only lexical hits match (06 Part X: "exact recall over semantic vibes"; archived rows hold no vector anyway). The query text is never embedded in deep mode. Structured mode (exact filters over projects/tasks) is refused as `invalid_request`, named.

### D6 — Query embedding is model-pinned and local-only (Option 2A; amends ADR-055 D1)

`Router.embed(spec, texts, model=None)`: a given `model` keeps only chain entries serving it. Search pins the `active` version's model, checks the echoed model and the vector's dimension, and embeds under `privacy_tier="private"` — Kang's own words go only to a `local_only` provider, structurally, whatever `providers.toml` later grows. Any failure of the semantic half (no provider, provider down, wrong space) returns lexical results with `degraded: "semantic_unavailable"` (A9).

### D7 — `memory.search`: a first-party query on the write executor (Option 3A)

Scope `memory.read` (06 §12.2's vocabulary, bare form — the agents' qualified view grants do not cover it), `first_party_only`, kind `query`, wired in `memory_wiring.memory_handlers` so the composition root's dispatch sends it to the writer, as it does `system.health`. **Trigger to revisit:** `knowledge.ask` or the Context Assembler — the first consumer that makes model calls on a read path designs the read-pool split for all of them.

### D8 — Audit: sensitive results only

A search that returns a `sensitive` record (as a match or a nearest miss) is audited — `memory.read.sensitive`, ids only, never content (06 §12.3). Routine `normal` reads are not. `private` records are never searchable (ciphertext only, excluded from FTS by trigger and from vectors by ADR-055).

### D9 — What this slice does not do

No context manifests, no Context Assembler, no `memory.explain_retrieval`, no `knowledge.ask`. `ctx` is 0 until the link layer exists. No access-frequency term (it would need writes on the read path). No episodes or vault chunks. No UI. No near-duplicate probe at the gate. No `int8`.

---

## Consequences

**What becomes possible.** Kang can search his memory by meaning and by words, see why each result ranked where it did, and get an honest "nothing matches" instead of padding. The scorer that the Context Assembler will reuse exists, property-tested. A model migration no longer threatens query correctness.

**What becomes harder, or costs something.** Each search holds the single writer for its duration. The 10-year fetch sits at ~93% of its budget — a known release-gate item, not a surprise. `memory.toml` grows two tables an existing install must copy in before search works. D010's "callers declare intent, not models" carries one stated exception, for embeddings.

**Named, not decided:** `int8` (trigger in D1); the read-pool split for model-calling queries (trigger in D7); calibrating `match_min_similarity` and the hypothetical half-lives on real data; the access-frequency component of `imp`.

## Verification

Implemented 2026-10-06, same session — see the slice's commit message and the dated notes it carries; this section is filled in at commit with what was actually run.
