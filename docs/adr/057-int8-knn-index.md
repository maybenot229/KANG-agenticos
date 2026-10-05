# ADR-057 — The int8 kNN index: ADR-056 D1's trigger fired before its own commit; a scaled int8 companion table serves search, the float table stays each version's lossless store

**Status:** accepted (2026-10-06) — **under Kang's delegated acceptance, not his own read** (2026-10-05: "accept everything by urself" for a bounded working window, his review to follow). Drafted, accepted and implemented by the architect session the same night, inside the ADR-056 slice, before that slice's implementation was committed.
**Date:** 2026-10-06
**Supersedes:** none. **Fires** ADR-056 D1's named remedy (its trigger: "the nightly `test_hybrid_fetch_on_corpus.py` going red"). **Amends** ADR-055 D4/D6 (each version gains a companion int8 table; the index writes both) and ADR-056 D1 (search reads the int8 table) — dated notes on both, their text untouched.
**Affected documents:** `migrations/0023_embedding_v1_int8_index.sql` (new); `src/kang/adapters/sqlite/embedding_index.py`; 07_DATABASE DB-004 and §6.2 (dated notes); ADR-055 D4, ADR-056 D1 (dated notes); `tests/suites/CLAIMS.md`.
**Cites:** 07 Part XIV (`docs/07_DATABASE.md:848`, hybrid candidate fetch < 250 ms on the 10-year corpus; "Exceeding a budget in CI is a failing build, not a warning"), DB-004 (768/float32 the v1 default; "quantized int8 (MAY adopt later via a new version — the protocol handles it)"), 04 §19 / 03 §8 (Vector DB server trigger); ADR-055 D4/D5/D6; ADR-056 D1; 11_CODING §25 (no new dependency — `sqlite-vec` already ships int8).

---

## Context

ADR-056 D1 chose exact float vectors because the bare kNN measured 217–239 ms on the year-10 corpus. Its own nightly test then measured the **whole** fetch through the real stores — kNN plus FTS plus the joins plus hydration — at **258–288 ms warm** against the 250 ms budget, before the slice was committed. The premise was wrong by the overhead it did not include, and the remedy it named had already been measured. Three more findings, all on Kang's machine, 2026-10-06:

**Finding 1 — plain int8 is not enough for real embeddings; per-vector scaling is.** `nomic-embed-text` vectors from Ollama are unit-norm, with every component within ±0.17. `vec_quantize_int8(v, 'unit')` spreads [−1, 1] over 256 levels, so a real vector uses ~43 of them. On 2,000 real vectors (synthetic-corpus sentences embedded by the local Ollama, 50 queries), recall@64 against exact: plain int8 **0.933** mean (min 0.875); int8 after dividing each vector by its own largest absolute component **0.989** mean (min 0.953). Cosine distance is invariant to that per-vector scaling, so nothing else changes.

**Finding 2 — int8 meets the budget with room.** On the year-10 vectors: int8 cosine kNN ~150–180 ms with the machine loaded by a concurrent Ollama job (exact: 276–349 ms under the same load), ~90 ms quiet over 60k vectors. Distance error on shared hits ≤ 0.0014 — far below anything the scorer or the 0.5 match floor can feel.

**Finding 3 — the cheaper-looking alternative does not work here.** Binary coarse kNN then an exact float kNN restricted to those rowids: `vec0` still scans the whole float table for the restricted query (~195–260 ms), and binary recall was 0.39–0.86. Rejected on measurement.

---

## Options

**A — A companion `vec_memory_v{n}_i8` table per version: int8, per-vector max-abs scaled, cosine; search reads it; the float table stays. (Recommended.)** *For:* meets the budget with headroom; recall 0.989 on real vectors; DB-004's float32 commitment intact — the float table is still the version's lossless store, from which the int8 index can always be rebuilt in SQL (migration `0023` does exactly that, no re-embedding); invalidation stays mechanical (more triggers, same rule). *Against:* +768 bytes per row (+25%); two tables per version to keep in step (the index writes both in one transaction; the triggers delete both).

**B — Make int8 the version itself (DB-004's "via a new version").** *For:* the protocol's own words. *Against:* loses the lossless vectors that exact re-ranking, re-quantization or a future better index would need, and `embedding_version` has no column saying a version is quantized. A version is a model space; the index over it is a separate concern.

**C — Relax the budget.** *Against:* relaxing a declared budget is exactly what 14 §11 names as a forbidden shortcut, and a 2× remedy inside the existing dependency is measured and available.

---

## Decision

### D1 — Option A: each version's float table gains a scaled int8 companion, and kNN reads it

`vec_memory_v1_i8 USING vec0(record_rowid INTEGER PRIMARY KEY, embedding int8[768] distance_metric=cosine)`. A stored vector is divided by its largest absolute component (1 if all are zero) and quantized with `vec_quantize_int8(·, 'unit')`; a query vector is scaled and quantized the same way. `nearest_memory` reads the int8 table; its distances are int8 cosine distances. Pending, coverage and cutover still read the float table — it is the version's truth of derivation.

### D2 — Written together, invalidated together

`store_memory_vectors` inserts the int8 row in the same transaction as the float row, and only when the guarded float insert succeeded. Migration `0023` adds triggers on `memory_record` mirroring `0022`'s for the int8 table (delete on row delete, on content/sensitivity change, on leaving the retrievable statuses), and backfills the int8 table from every existing float vector in pure SQL (`vec_each` → scaled → `vec_f32` → quantized), verified equal to the Python path. Nothing is re-embedded.

### D3 — The protocol extends, not changes

A future model-change migration creates `vec_memory_v{n+1}_i8` and its triggers beside `vec_memory_v{n+1}`. Episodes and vault chunks have no producer yet; their int8 tables arrive with their slices, which must measure their own scale (500,000 vault chunks is a different budget question).

### D4 — What this does not do

No change to the scorer, the match floor, the fetch's candidate counts, or `embedding_version`. No exact re-rank (distance error ≤ 0.0014 does not warrant one). No binary index.

---

## Consequences

**What becomes possible.** The 10-year hybrid fetch fits its budget with headroom on Kang's machine, and the Vector DB server trigger moves further from firing.

**What becomes harder, or costs something.** Each embedded row costs 3,840 bytes instead of 3,072. Two tables per version must stay in step; the index, the triggers, and a SQLite-only test hold them there. Search ranks by an approximation — recall 0.989 on real vectors means roughly one in a hundred of the true top 64 is swapped for a near neighbour. The nightly CI runner may be slower than Kang's laptop (07 Part XIV states its hardware assumption); the printed numbers will show it.

**Named, not decided:** calibrating recall on Kang's real vault once it has a few thousand records; int8 for episodes and vault chunks (their slices).

## Verification

Filled in at the implementation commit with what was actually run.
