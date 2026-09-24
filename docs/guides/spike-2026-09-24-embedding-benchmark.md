# Spike — the embedding model benchmark on Kang's real vault

**Written:** 2026-09-24.
**Question (verbatim, 04_ARCHITECTURE §20.1):** "Embedding model choice (local-first candidate vs. API quality) — needs a small evaluation on Kang's real vault before v0.2. Decision by benchmark, not vibes."
**Governed by:** 18_IMPLEMENTATION_MASTER_PLAN §8.5 (IM-005) — this is a spike: bounded, never merged, output is a decision input (this document), not code. Step 21 of 18 §10 places it here, after v0.1, before the synthetic corpus generator and the memory schema build.
**Status:** spike complete. **This document is not an ADR and does not decide anything** — per the task, Kang's architect session drafts the ADR from these findings.
**Zero vault content appears below.** Every number is an aggregate statistic (a count, a percentage, a millisecond, a byte count) computed over Kang's vault at `C:\Kang`; no note text, heading, filename-derived phrase, or excerpt was copied, quoted, or paraphrased into this document, the spike's own scripts, or anywhere in the repository.

---

## 1. Method, stated with its limits up front

There is no labelled relevance set for this vault — none exists, and building one by hand was out of scope for a "small evaluation." This spike builds a **proxy**: a self-supervised retrieval task constructed from the vault's own structure, not from human relevance judgments. Treat every number below as directional evidence, not ground truth.

**Chunking** (06_MEMORY §5.3's own shape): each note's frontmatter stripped, then windowed at 200–400 words (word count stands in for "tokens" — a deliberate approximation; different models tokenize differently, and 06 §5.3's own target is itself approximate guidance, not a byte-exact spec) with 15% overlap between windows. A short tail window merges into its predecessor rather than surviving as its own fragment — which is why the *measured* max chunk size (589 words) slightly exceeds the 400-word target in practice; a production chunker would make the same trade-off rather than emit orphan fragments.

**Proxy query construction:** for every chunk belonging to a note that produced ≥ 2 chunks, that chunk's own leading ~25 words become a query; the candidate pool for that query is every *other* chunk in the corpus (the query's own source chunk is excluded, so the test cannot pass by trivial near-duplicate match); a hit is any chunk from the **same note** appearing in the ranked results. This generalizes the task brief's own suggestion ("a note's own heading or first line as the query, its other chunks as the target") from one query per note to one query per eligible chunk, to get more than a handful of data points out of a small vault.

**Where this proxy is weak — named plainly, per the task's own instruction:**

1. **"Same note" is a noisy stand-in for "actually relevant."** A long note can cover several genuinely different subjects across its sections; the proxy would count a hit for a chunk that merely shares a file with the query, not a *topic* with it. This inflates scores for any model that picks up on document-level style/vocabulary consistency rather than semantic content — and every candidate is inflated by roughly the same amount, so it degrades the proxy's *absolute* meaning more than it distorts the *relative* comparison between candidates.
2. **The corpus is small.** See §2 — 46 chunks, 33 proxy queries. At n=33, the 95% confidence interval on a recall@1 estimate is roughly **±15–16 percentage points** (computed below, §4). The full spread observed across all five working candidates' recall@1 (0.636–0.758, a 12.2-point range) is *narrower* than that single-candidate confidence interval. **None of the quality differences in §4 are statistically distinguishable at this sample size.** This is the single most important caveat in this document.
3. **The query text is drawn from inside a chunk that also appears (whole) elsewhere in the same note's chunk set** in some cases (overlapping windows), which can make a hit slightly easier to find than a genuinely independent query would.
4. **No true negatives are held out.** Everything not from the source note is treated as "not relevant," including chunks that might, in a real relevance judgment, actually be topically related (e.g., two different notes both about the same subject). This likely *undercounts* true positives slightly, in the opposite direction from finding (1).
5. **Multilingual/code-switching coverage is present but not isolated.** 78.3% of the 46 chunks contain at least one non-ASCII character (§2) — but this figure is dominated by ordinary Markdown typography (curly quotes, em dashes) rather than necessarily language-switched text, and this spike did not run language identification to separate the two. The candidate set includes two natively multilingual models (bge-m3, multilingual-e5-base) specifically so the axis is represented, but this spike cannot report a clean "how much better on Malay/English code-switching" number — that needs either a language-ID pass or a hand-picked multilingual query subset, neither of which fit "a small evaluation."

**What was measured instead of estimated, per the task's own rule:** anything this spike could not run for real on this machine is reported as a finding (gte-base, §4), never as a guessed number. Two numbers *are* stated as extrapolations rather than direct measurements (§5); both are labeled as such at the point they're used, and the extrapolation is calibrated from a real measurement at the target scale for one dimension, not assumed.

---

## 2. The vault, in aggregate only

- `C:\Kang` contains **30 Markdown files**.
- After skipping `.trash/`, `.obsidian/`, `attatchments/`, `Canvas/` (attachments, not notes), the template stub, and files under 15 words: **19 notes** entered the chunker.
- Chunking produced **46 chunks** total; **6 notes** produced 2 or more chunks (the rest are single-chunk, too short to windowed-split at the 200–400 word target).
- Chunk word count: min 22, max 589, mean 344.6 (the >400 max is the documented tail-merge trade-off above).
- Proxy query set: **33 queries** (one per chunk belonging to a multi-chunk note).
- Non-ASCII-containing chunks: **36 of 46 (78.3%)** — see the caveat in §1.4 above.

This is a genuinely small vault by any standard, and that is itself a finding: **the proxy evaluation's statistical power is bounded by the vault's current size, not only by the proxy method's own design.** Re-running this exact spike once the vault holds materially more content would tighten every confidence interval below without changing any of the method.

---

## 3. Runtime environment found on this machine

This was checked first, per the task, because it decides what could even be tried.

- **Ollama 0.34.3** is installed (`C:\Users\meime\AppData\Local\Programs\Ollama\ollama`), but **had zero models pulled** before this spike — its presence with an empty model store is itself worth recording: the runtime exists, nothing was provisioned into it yet.
- **No NVIDIA GPU** is exposed (`nvidia-smi` not found); `torch.cuda.is_available()` returns `False`. Every measurement below is **CPU-only** inference.
- The system Python (3.12.5, `C:\Users\meime\AppData\Local\Programs\Python\Python312`) already has `torch` 2.10.0 installed — pre-existing on this machine, **not part of KANG's own `pyproject.toml`** (confirmed by grep: zero hits) and not something this spike added there.
- Per 17_PROJECT_STRUCTURE §9 ("model weights are not KANG's to store"), nothing this spike downloaded belongs to the repository or to `%KANG_HOME%`: Ollama's three pulled models (`nomic-embed-text`, `all-minilm`, `bge-m3` — 1.5 GB combined) live in Ollama's own model store, and the three HuggingFace models pulled via `sentence-transformers` live in `~/.cache/huggingface/hub`. Kang can remove either cache at will; neither was written by, or is referenced by, any file under `C:\KANG - Agentic OS`.
- All spike-only Python dependencies (`sentence-transformers`, `sqlite-vec`, `numpy`, `requests`, and their own transitive `torch`/`transformers`) were installed into a **throwaway venv** created for this spike alone, never into the repository's own environment and never added to `pyproject.toml`.

---

## 4. Candidate results

Six candidates, chosen to cover: the current 07_DATABASE DB-004 default's dimension class (768), a cheap floor (384), one 1024-dim option so the dimension question is actually tested, and the multilingual axis explicitly (D010 names `embedding` as a task class the Model Router routes local-preferred; A7/P8 rule out a hard cloud dependency).

| Candidate | Backend | Dim | Recall@1 | Recall@5 | Recall@10 | MRR | Throughput (chunks/s, CPU) | Bytes/vector (f32) |
|---|---|---|---|---|---|---|---|---|
| **nomic-embed-text** | Ollama | 768 | 0.697 | 0.879 | 0.970 | 0.783 | 1.24 | 3072 |
| **all-MiniLM-L6-v2** | Ollama | 384 | 0.727 | 0.818 | 0.970 | 0.778 | **10.07** | **1536** |
| **bge-m3** | Ollama | 1024 | **0.758** | **0.909** | 0.939 | **0.822** | 0.44 | 4096 |
| **bge-base-en-v1.5** | sentence-transformers (HF) | 768 | 0.636 | 0.758 | 0.939 | 0.707 | 2.21 | 3072 |
| **gte-base** | sentence-transformers (HF) | — | *did not complete* | | | | | |
| **multilingual-e5-base** | sentence-transformers (HF) | 768 | 0.697 | 0.879 | 0.939 | 0.769 | 2.24 | 3072 |

n = 33 proxy queries for every row that ran. **95% CI on recall@1 at this n is approximately ±15–16 percentage points** (normal approximation, `sqrt(p(1-p)/n) × 1.96`, computed per-candidate: 0.636→±16.4pp, 0.697→±15.7pp, 0.727→±15.2pp, 0.758→±14.6pp). The entire observed recall@1 spread across all five working candidates (12.2 points) is narrower than any one candidate's own confidence interval. **Read the quality columns as "statistically indistinguishable at this vault size," not as a ranking.**

**gte-base did not complete.** Its weights downloaded and loaded normally (209 MB, same `sentence-transformers` pipeline as bge-base and multilingual-e5-base), but embedding the same 79 short texts (46 chunks + 33 queries) that bge-base finished in 35 seconds did not finish after **more than 20 minutes of wall-clock time** on this CPU, with CPU-time growing only slowly and non-monotonically (consistent with the process being blocked rather than crashed). It was terminated rather than left to run indefinitely. This is reported as a measured throughput finding, not an estimate — no recall/MRR/throughput number is claimed for it. Whether this is intrinsic to `thenlper/gte-base`'s architecture on CPU-only PyTorch, or an artifact of this specific machine/PyTorch build, is not something this spike can distinguish; worth a second attempt on different hardware before ruling it out entirely.

---

## 5. What else was measured, because the dimension decision depends on it

### 5.1 Index size (measured directly, not estimated — size scales exactly linearly with row count, unlike latency)

Real `sqlite-vec` `vec0` virtual tables were built and their on-disk byte size measured directly (this includes `vec0`'s own per-row overhead, not just `dim × 4` bytes):

| Dim | Measured bytes/row | Naive `dim×4` | Overhead | Size at 10-yr ceiling (500,000 rows, per 07_DATABASE Part XIV) |
|---|---|---|---|---|
| 384 | 1566.1 | 1536 | +30 | **782 MB** |
| 768 | 3109.5 | 3072 | +37 | **1.55 GB** |
| 1024 | 4137.6 | 4096 | +42 | **2.07 GB** |

The 768-dim figure (1.55 GB) lands almost exactly on 07_DATABASE DB-004's own stated estimate ("≈1.5 GB at the 10-year 500k-chunk ceiling") — a useful cross-check that this spike's methodology is measuring the right thing.

### 5.2 Query latency — the largest finding in this spike, and it is *not* primarily about which model to choose

07_DATABASE Part XIV's latency budget: **"Hybrid candidate fetch (vec k=64 + FTS k=64 + prefilter) < 250 ms."** This spike measured the `vec` half of that alone, via real `sqlite-vec` `vec0` tables (the exact mechanism 07_DATABASE names), `k=64`, on this machine:

| Dim | Rows | p50 | p95 | Measured or extrapolated |
|---|---|---|---|---|
| 384 | 100,000 | 282 ms | 296 ms | **measured** |
| 384 | 500,000 (10-yr ceiling) | **1,544 ms** | 1,821 ms | **measured** |
| 768 | 100,000 | 567 ms | 586 ms | **measured** |
| 768 | 500,000 | 3,109 ms | 3,210 ms | extrapolated (see below) |
| 1024 | 100,000 | 754 ms | 761 ms | **measured** |
| 1024 | 500,000 | 4,132 ms | 4,170 ms | extrapolated |

The 500,000-row extrapolations for 768/1024-dim are **calibrated, not assumed-linear**: 384-dim was measured for real at both 100k and 500k rows, giving an observed 100k→500k scaling factor of **5.48×** (row count grew 5×; latency grew 5.48× — mildly super-linear, plausibly because the working set outgrows some cache tier between the two sizes on this machine). That same *measured* factor, not a theoretical assumption, was applied to the 768/1024-dim 100k-row measurements to produce their 500k-row figures.

**Every dimension tested, at every row count from 100,000 upward, already exceeds the 250 ms budget** — 384-dim at 100,000 rows (282 ms) is already over, and by the 10-year ceiling every dimension is 6–17× over budget. This is measured with `sqlite-vec`'s default `vec0` behavior, which is an exact brute-force scan (no approximate-nearest-neighbor index structure) — the cost is linear in row count × dimension, independent of the vector *values*, which is why synthetic random vectors measure the same latency real ones would.

**This finding is independent of which embedding model wins on quality.** Even the cheapest dimension tested (384) blows the budget by 6× at scale. Whatever this spike's recommendation is, it does not resolve this — it is named here because the task asked this spike to measure query latency against 07 Part XIV's budgets, and the honest answer is that the budget, as currently specified against `vec0`'s default brute-force mode, does not appear reachable at 07_DATABASE's own stated 10-year scale, regardless of embedding choice. **This is a finding for Kang's architect session to weigh, not something this spike is positioned to fix or decide** — it may call for an approximate index mode, a smaller effective `k`, a pre-filter that runs before the vector scan rather than after, or a re-examination of the budget itself.

### 5.3 Embedding throughput at scale — the background re-embed window, not the rebuild-indexes budget

07_DATABASE Part XIV's "full index rebuild (`kang rebuild-indexes`) < 15 min" budget is **not** what these throughput numbers bound — 06_MEMORY's own text says the embedding cache (`cache/embeddings.db`, content-hash → vector) "survives re-index (not re-model)," meaning an index rebuild restores `vec0`/FTS5 structures from already-computed vectors, no model inference required. What these throughput numbers *do* bound is DB-004's **model upgrade protocol** — "create v{n+1} tables → background re-embed in mtime/priority order" — the one scenario where the *entire* corpus genuinely needs re-embedding from scratch, e.g. if Kang changes embedding models later. At the measured chunks/second (§4) and the 10-year ceiling of 500,000 chunks:

| Candidate | Chunks/s | Time to re-embed 500,000 chunks (background window) |
|---|---|---|
| all-MiniLM-L6-v2 | 10.07 | ≈ 13.8 hours |
| bge-base-en-v1.5 | 2.21 | ≈ 2.6 days |
| multilingual-e5-base | 2.24 | ≈ 2.6 days |
| nomic-embed-text | 1.24 | ≈ 4.7 days |
| bge-m3 | 0.44 | ≈ 13.2 days |

All of these are background, non-blocking, hot-rows-first per DB-004's own protocol — not user-facing latency — but the spread is enormous (a 23× difference between the fastest and slowest candidate), and even the fastest local CPU option takes over half a day to fully re-embed a decade of vault content. This is a real, decision-relevant cost of any future model-version change, worth stating plainly rather than assuming "it's a background job" makes the number not matter.

---

## 6. Ranked recommendation

Given §4's central finding — **no candidate's proxy recall/MRR is statistically distinguishable from any other's at this vault's current size** — this recommendation is driven primarily by the resource measurements in §5, which *are* solidly measured, not by the quality columns, which are not yet conclusive either way.

1. **all-MiniLM-L6-v2, 384-dim** — the resource-optimal choice on current evidence. Fastest to embed by a wide margin (10.07 chunks/s vs. 0.44–2.24 for everything else that completed), smallest index footprint at the 10-year ceiling (782 MB vs. 1.55–2.07 GB), and lowest (though still over-budget) query latency — with **no measured quality penalty** relative to any other candidate at this sample size. Named caveat: it is a small, general-domain, mostly-English-trained model; 07_DATABASE DB-004's own "Alternatives" note already flags 384-dim as "cheaper, meaningfully worse on technical text" as a general expectation from outside this benchmark — this spike's own proxy is not powered to confirm or refute that on Kang's specific vault.
2. **multilingual-e5-base, 768-dim** — the recommended alternative if the multilingual/code-switching axis is judged more important than this spike's thin evidence can settle on its own. It is purpose-trained for cross-lingual retrieval (unlike all-MiniLM, which has minimal non-English training exposure), sits in the same dimension class as 07_DATABASE's current default, and its resource cost (2.24 chunks/s, 3072 bytes/vector) is real but far short of bge-m3's.
3. **bge-m3, 1024-dim** — recommended *against* as the default, despite having the best point-estimate MRR (0.822) and recall@5 (0.909): the advantage is not statistically distinguishable from the pack (§4), and it pays the steepest cost on every resource axis measured (slowest embedding at 0.44 chunks/s, largest index at 2.07 GB, worst extrapolated query latency at 4.1 s). If a larger future benchmark shows a real, reproducible quality edge for bge-m3 specifically on Kang's vault, that would be the point to reconsider it — not now.
4. **bge-base-en-v1.5** and **nomic-embed-text** — no measured advantage over the above on this vault; nomic-embed-text in particular is markedly slower to embed (1.24 chunks/s) than the sentence-transformers-backed 768-dim options despite being the same dimension class, for reasons this spike did not investigate (plausibly Ollama's own per-call overhead vs. sentence-transformers' batched CPU inference).
5. **gte-base** — cannot be recommended or ruled out; it did not complete on this machine (§4). Worth a second attempt elsewhere before being dropped from consideration.

**On the dimension question specifically** (the part 07_DATABASE DB-004 explicitly asked this spike to answer): the evidence here does not support moving *up* from the current 768-dim default to 1024-dim — the measured cost is real and the measured benefit is not statistically established. It mildly favors *down*, to 384-dim, on resource grounds alone, with the multilingual caveat named above as the reason a 768-dim multilingual-native model is a defensible alternative rather than a strictly worse choice.

**Independent of the model/dimension decision:** §5.2's `sqlite-vec` brute-force latency finding is, in this spike's own judgment, more architecturally urgent than the model choice itself, since it affects every candidate tested. It is named here as a finding, not resolved — that decision belongs to the ADR this document feeds, or a follow-up spike of its own.

---

## 7. Things worth flagging for Kang's review (nothing here blocked this spike; no cloud API was considered or needed)

- The vault's current size (19 usable notes, 46 chunks) limits this spike's statistical power more than the proxy method's own design does. Re-running this exact spike once the vault has grown would meaningfully tighten every confidence interval above without changing anything else.
- gte-base's non-completion may be a property of this specific machine/PyTorch CPU build rather than the model itself — worth a retry on different hardware, or via Ollama if it becomes available there, before treating it as ruled out.
- The `sqlite-vec` brute-force latency finding (§5.2) applies regardless of which model is chosen and, in this spike's reading, deserves attention before Phase 2 ships — named here for the architect session to weigh, not decided by this spike.
- The 78.3% non-ASCII figure (§2) is too coarse to answer "how much of the vault is genuinely Malay/English code-switched" — a real answer would need language-ID tooling this spike did not build, kept out deliberately to stay within "a small evaluation."
