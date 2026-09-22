# Build brief — implementing ADR-052 (the gate merge and tier amendment)

**Written:** 2026-09-22, by the session that drafted ADR-052.
**For:** the coding session that implements it.
**Precondition — check before touching anything:** `docs/adr/052-gate-merge-and-tier-amendment.md` must say `**Status:** accepted`. If it still says `proposed`, stop, say so, and end your turn.
**Non-normative** (17 §12). ADR beats brief; a numbered document beats the ADR except where the ADR's "Affected documents" line names the amendment. A third disagreement: stop and surface it.

> This is a **small** slice that closes two holes in the write gate — the most safety-critical component in Phase 2. Small does not mean casual: CLAUDE.md §8.1 applies with full force. Every change here only ever makes the gate refuse *more*. If you find yourself writing something that lets the gate accept anything it does not accept today, stop and surface it.

---

## 0. What you are building

Three behavior changes, all inside code that already exists, plus the test that would have caught the first one and the four dated document notes. **No schema change, no migration, no new port, store method, operation, config key, or job** (ADR-052 D4).

## 1. Read first, in this order

1. `CLAUDE.md` (repo root) — §8 (especially §8.1) and §9.
2. `docs/adr/052-gate-merge-and-tier-amendment.md` — D1–D4. Its Options carry reasoning you will need for the doc notes; its Verification lists what must be proven.
3. `docs/adr/051-memory-write-gate.md` D4, D5, D6, D10 — what you are amending and the shape you are amending inside.
4. `docs/06_MEMORY.md` §4.2 (the flowchart you correct), §1.4 (the Tier-2 rule you enforce), §12.3 (gate decisions are audited), §2.1 (the tier column whose tension with §1.4 D3 deliberately leaves open).
5. The code: `src/kang/domain/memory/write_gate.py` (`decide`, the refusal helpers), `src/kang/api/operations/memory_ops.py` (`_merge`, `_reject`, the propose handler's outcome branches), `src/kang/api/schemas/memory.py`, `tests/suites/memory_integrity/test_no_code_path_to_active.py` (the sweep you extend), `tests/unit/kang/domain/memory/test_write_gate.py`.

## 2. The three changes

**D1 — the duplicate branch moves below the writer branch.** In `decide()`, an exact duplicate yields `merge` **only** when `writer.is_kang`; every other writer gets a rejection with code `duplicate`. The rejection message must name neither the incumbent's id nor its content (ADR-052 D1's side-channel narrowing). `merge_provenance` and `_merge` keep their current behavior and stay reachable on the Kang path only.

**D2 — one more refusal.** A proposal with `trust_tier == 2` from a writer that is not Kang is refused with code `tier_restricted`. Place it **with the other writer-class refusals, before the duplicate probe**, so a false sanction claim is refused whether or not the content duplicates something. Order matters and is testable.

**D3 — `memory.edit_approve` gains an optional `trust_tier`.** Present ⇒ the landed record carries it. Absent ⇒ the proposal's tier lands unchanged, exactly as today. This is the only path by which a non-Kang-originated record reaches Tier 2. Nothing else changes about `edit_approve`.

## 3. The sweep extension — the most important part of this slice

`tests/suites/memory_integrity/test_no_code_path_to_active.py` passed while both holes were open. ADR-052's Verification names **two independent reasons**, both confirmed in the test's own source; close both or the sweep will keep passing over this class of defect:

1. `_records()` selects `id, type, status, content, trust_tier, sensitivity, reason, created_by, source_kind` — it omits **every column the merge writes** (`source_detail`, `revision`, `updated_at`, `device_id`). Select every column of `memory_record` instead, so "the incumbent row is unchanged" means the whole row.
2. The adversarial params propose `AGENT_CONTENT`, which never equals the seeded Kang record's content, so the duplicate probe never fires anywhere in the sweep. Add an adversarial variant that proposes **the exact content of Kang's seeded record**, so the duplicate path is actually exercised under every non-Kang principal.

Be aware of a third fact the same source shows, so you do not misread a passing test: the sweep already proposes `trust_tier=2` from an agent and passes, because the proposal is *queued*, not admitted. The tier claim lands in the queue payload, which no record-table assertion can see. D2's proof therefore has to be a gate-level and handler-level test, not a sweep assertion.

## 4. Documents (same commit)

- `06_MEMORY.md` §4.2 — dated amendment correcting the flowchart's node order (writer-authorization precedes the merge; the merge edge is Kang-only). Bump "Last updated".
- `06_MEMORY.md` §1.4 — dated note: the Tier-2 rule is now enforced at the gate.
- `docs/adr/051-memory-write-gate.md` — a dated "Amended by ADR-052" note on **D5** and a dated "Extended by ADR-052" note on **D6**. Touch nothing else in ADR-051, including its Verification.
- `12_API.md` §10 — dated note: `memory.edit_approve` may set `trust_tier`.
- `docs/adr/INDEX.md` row; `tests/suites/CLAIMS.md` lines; ADR-052's Verification appended.

## 5. Verification protocol

1. `ruff format --check .` first, then `ruff check .`, `lint-imports`, `lint_sizes.py`, `lint_banned_patterns.py`, `lint_tree_hygiene.py`, `lint_doc_citations.py`, `build_root_docs.py --check`.
2. Both non-nightly halves with exact before/after counts. Before: **1051** and **357**. `-m nightly` before: **15**.
3. **Prove each fix would have caught its hole**, by reverting the fix and watching the new test go red, then restoring. Do this for D1 (the sweep extension must go red against the pre-D1 gate) and for D2. Report both, the way ADR-050's marker guard was proven.
4. Live-verify on a **throwaway** `%KANG_HOME%` (delete after; never the real one): an agent proposing the exact content of an existing Kang record is refused, and that record's `source_detail`, `revision`, `updated_at` and `device_id` are **byte-identical afterwards**; Kang proposing the same duplicate still merges and bumps revision; an agent proposing `trust_tier=2` is refused even when the content is novel; `edit_approve` with and without an explicit tier.
5. `composition.py` is at **799 of its 800-line hard limit**. This slice should not need to touch it. If you find you must, split it as ADR-023/037/044 did and say so — do not bump the limit.

## 6. Commit

One commit on `main`, local, never pushed, in `git log`'s established style. End with the attribution line your session's system reminder gives you. Do not accept, reopen, or re-decide any ADR. If reality contradicts ADR-052 anywhere near the gate's admission rules, stop and ask Kang.

## 7. Known traps

- The refusal **order** in `decide()` is part of D2, not an implementation detail: tier before duplicate.
- `merge_provenance` must stay reachable — this slice narrows who reaches it, it does not delete it.
- A gate rejection raises `ApiError` with the gate's own code and is audited as `memory.gate.rejected`; reuse that path rather than inventing a second rejection shape.
- Do not add the incumbent's id to the duplicate error "for debuggability". D1 narrows the side channel deliberately.
- Widening `_records()` to every column may surface unrelated churn (`updated_at` on rows other tests touch). If a previously-passing test goes red for that reason, that is a real finding about the sweep's isolation — report it, do not narrow the SELECT back.
