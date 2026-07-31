# ADR-009 — HTTP transport ratified as stdlib `http.server`; Pydantic adopted for operation schemas

**Status:** accepted
**Date:** 2026-07-31
**Decides:** `04_ARCHITECTURE.md` Decision 002 (Core transport half only — the UI/Tauri and CLI portions of D002 are unaffected and unchanged)
**Affected documents:** 04_ARCHITECTURE.md D002, 12_API.md §2/§16, 17_PROJECT_STRUCTURE.md §4.2 (legality matrix's "api may import FastAPI et al." row — same stale claim this ADR corrects elsewhere, now found in a second document), pyproject.toml (new runtime dependency: Pydantic)
**Cites:** API-002 (12_API §3 — contract transport-independence), 04_ARCHITECTURE D010 (Pydantic *named* for model-output validation — verified unimplemented, see Part B), E10 (01_PRINCIPLES — boring tech, justify every dependency), ADR-006 (precedent for this ADR's Part A / Part B structure)
**Related:** RESERVED registry row, 03_ROADMAP.md §8 ("Registry→TypeScript API client generator") — this ADR scopes Ruling A and B of that row; the generator itself (Ruling C) remains RESERVED, now triggered by "Ruling B's schemas exist in code."

---

## 1. Context

Scoping M6's generated TypeScript client (`18_IMPLEMENTATION_MASTER_PLAN.md` §7.3) surfaced two facts that needed ruling before the generator could be scoped at all:

**1. `04_ARCHITECTURE.md` Decision 002 names FastAPI; the shipped code uses stdlib `http.server`, and no ADR was ever filed for the switch.**

Decision 002's FastAPI line was written 2026-07-12 (`62fd5c8`) and has not been touched since (`git blame -L 130,130`). `src/kang/api/http_binding.py` was created three days later, 2026-07-15 (`c4f210e`), implementing stdlib `http.server` instead — its own docstring cites 17 §4.2 to justify the choice, but no ADR exists (`docs/adr/` grepped for `FastAPI|http_binding|transport|stdlib`, no substantive hits). This was a silent, undocumented architectural reversal.

**2. `12_API.md` §2 and §16 assert the Operation Registry carries "request/response schemas." It never has.**

`registry_json()`'s actual output — confirmed by reading `src/kang/api/registry/__init__.py` — is a flat dict per operation: `{name, kind, scope, idempotency, version_introduced, deprecated, summary, first_party_only, commit_mode}`. Zero schema field, across all 14 registered operations, since the file's first commit. This is independent of transport: no schema-generation mechanism exists anywhere in `src/` (zero Pydantic imports, zero TypedDict/JSON-Schema in `api/`; every handler in `operations.py` takes `(context, params: dict[str, Any]) -> dict[str, Any]` with hand-written `.get()`/`if` validation inside the body — nothing introspectable).

These two facts are entangled: whichever transport is ratified determines which schema-authoring mechanism is cheap. They are decided together here, following the precedent set by ADR-006's Part A / Part B structure for exactly this kind of coupled decision.

**pyproject.toml today declares `dependencies = []`** — zero runtime dependencies, project-wide. This is load-bearing context for both parts below.

**A third fact, verified for this revision, that changes Part B's argument:** `04_ARCHITECTURE.md` Decision 010 (§11) names Pydantic for a *different* subsystem — "all machine-consumed outputs are schema-validated (Pydantic)." That subsystem does not exist. `grep -r "pydantic\|BaseModel" src/` returns zero hits anywhere in the codebase. The two files that would house it — `src/kang/kernel/router/__init__.py` and `src/kang/adapters/openai/__init__.py` — are empty stubs whose own docstrings say "built at M7" and "built when routed — Phase 3" respectively: future milestones, not current state. D010's Pydantic clause is aspirational text, not a proven pattern, and Part B below does not treat it as one.

---

## Part A — HTTP transport

### A. Options

**A1 — Ratify stdlib `http.server` as the real decision (recommended).**

- *For:* it is already shipped, already correctly serving all 14 operations through `Dispatcher`. `pyproject.toml`'s zero-runtime-dependency state is a deliberate, visible E10 posture — FastAPI would be the *first* runtime dependency this codebase has ever added, for a binding that is a single route (`POST /op`) dispatching to logic that already lives entirely in `Dispatcher`. Framework routing, path/query binding, and dependency injection — FastAPI's actual value proposition — are not exercised by a one-endpoint JSON-RPC-shaped binding. API-002 already declares the contract transport-independent; a correct stdlib binding is *evidence for* that declaration holding, not a workaround of it.
- *Against:* `http.server` has no WebSocket support, and the event channel (12_API §6, streaming) will eventually need one. Not disqualifying: `http_binding.py`'s own docstring already defers the event channel to a later, separate binding ("needs the bus subscription surface exposed to clients — M5+"), and API-002 treats the operation channel and event channel as distinct bindings by design. The event-channel binding is free to pick its own transport (a small WebSocket library, or FastAPI/Starlette if by then justified) without requiring the operation channel's binding to be re-litigated or replaced.

**A2 — Adopt FastAPI now, while the surface is small.**

- *For:* the surface really is small (14 operations, mostly unwired, one route) — this is the cheapest moment to switch if switching is ever going to happen. FastAPI + Pydantic route signatures would give OpenAPI generation close to free, feeding directly into Ruling C.
- *Against:* this is the argument for adopting FastAPI *for its schema/OpenAPI machinery*, not for its transport merits — the transport itself buys nothing here. It also creates a real coupling risk: if schemas are authored as FastAPI route-decorator signatures, schema authorship becomes tied to the HTTP binding, which is exactly what API-002 forbids ("Contract semantics MUST NOT depend on transport features"). A future sidecar IPC binding (already a RESERVED extension point) would then need its own, separately-maintained copy of the same shapes — two representations of one concept, the anti-pattern this handbook names directly (§5, §10). **Rejected** — not because FastAPI is bad technology, but because its natural usage pattern here would violate the contract's own transport-independence rule.

### A. Decision

Adopt **A1**. `04_ARCHITECTURE.md` Decision 002 is corrected: the Core transport is stdlib `http.server` (`asyncio` remains accurate elsewhere in D002 and is unaffected — Python's async runtime, not the HTTP framework, is the D002 clause in question). `04`'s text is amended to cite this ADR, per the pattern ADR-007 used for §20.2.

**Tripwire (normative).** This ruling is scoped to the operation channel only. If the M5 event-channel binding (12_API §6, streaming) requires more than a minimal WebSocket library, transport choice for BOTH channels MUST be reopened together at that time — not decided piecemeal, and not silently carried forward by whichever library the event-channel binding happens to pull in. A future contributor reaching for FastAPI "since we're already adding a dependency for the event channel" is the exact silent-reversal failure mode this ADR exists to correct; naming the condition now closes that path.

---

## Part B — Schema authority

### B. Options

**B1 — Pydantic models, defined in `api/`, attached to registry entries independent of transport (recommended).**

- *For:* Request/response models live in `api/` (not `domain/`) because 12_API §2 is explicit that the wire contract is the API layer's concern, and it may deliberately differ from internal domain representations (a memory record's provenance fields vs. what a client is allowed to see, per §4's `sensitivity=private` rule, is one existing example of wire shape ≠ domain shape). Each `_op(...)` entry in `registry/__init__.py` gains schema fields the same way it already gained `OperationChannel` (first_party_only/commit_mode) — extending an established pattern, not inventing a parallel one. `.model_json_schema()` gives JSON Schema output directly, feeding Ruling C without a second translation step. **Correction from an earlier draft of this ADR:** the case for B1 does *not* rest on D010 as proven precedent. D010 names Pydantic for model-output validation, but that subsystem is unimplemented — `grep -r "pydantic" src/` is empty, and the two files that would house it (`kernel/router/`, `adapters/openai/`) are stub modules explicitly deferred to M7/Phase 3. Citing D010 as "existing precedent" would repeat, inside this ADR, the exact defect this ADR exists to correct: treating a document's claim as settled fact without checking the implementation. What D010 *does* establish honestly is that Pydantic is not a foreign choice for this codebase's future shape — Kang and a prior session already judged it the right tool for a related problem (validating machine-consumed structured output) — but that is a design-taste data point, not a load-bearing precedent, and this ADR does not lean its weight on it.
- *Against:* a new runtime dependency, full stop — `pyproject.toml` moves off `dependencies = []`, and this would in fact be the **first real implementation** of a Pydantic dependency in the codebase (D010's mention is text, not an import). Accepted on its own merits per E10's test ("earns its place with a written justification"), standing alone: 12_API §2/§16 already claims schema-backed registry entries as a constitutional fact that has never been true, and hand-writing/hand-maintaining parallel JSON Schema by hand for a growing, 14-and-counting operation set is the "content duplicated in two places disagrees in two places" failure mode this handbook names directly (§14.5, generalized beyond the vault) — the Python handler's `.get()`/`if` validation and a hand-written schema file would be two unsynchronized descriptions of one shape. This dependency is being paid for here, once, not reused from a payment D010 never actually made.

**B2 — Hand-written JSON Schema per operation, no new dependency.**

- *For:* zero dependencies added; fully transport-independent by construction (no library involved at all).
- *Against:* hand-authored schema and hand-written Python validation (`.get()`/`if` in each handler) are now two independent representations of the same operation shape, authored separately, with nothing enforcing they agree — a machine-checkable contract that is itself not machine-checked against its own implementation. This is arguably less "boring" than Pydantic in practice: it reinvents, by hand, a solved problem Pydantic already solves. **Rejected.**

**B3 — TypedDict / dataclass + a lightweight JSON-Schema-from-dataclass tool.**

- *For:* smaller footprint than Pydantic; dataclasses are already the pattern used in `domain/` (see `TaskDraft`, `DeadlineDraft`); avoids committing the codebase's first-ever runtime dependency to a request that could, in principle, be solved without one.
- *Against:* no dataclass-to-JSON-Schema tool in this ecosystem is remotely as boring, proven, or maintained as Pydantic — E10 asks for the boring choice, and on that axis this is the worse option, not the more conservative one. It would also risk becoming a second schema-authoring mechanism later if D010's structured-output work (M7/Phase 3) is ever actually built and reaches for Pydantic on its own merits at that time — two tools solving the same category of problem, arrived at independently, is worse than committing to one now. **Rejected** — not because a dataclass-based approach is unreasonable in isolation, but because it's a worse E10 trade than B1, on its own terms, independent of D010's (unimplemented) status.

### B. Decision

Adopt **B1**. Pydantic request/response models, one pair per operation, defined in `api/` and attached to `OPERATIONS` registry entries. Operations without a live handler (`held_action.approve`, `held_action.cancel`) register with `schema: None` until their handlers are wired — consistent with the existing precedent in `registry/__init__.py` for those same two entries ("these entries register the contract shape ahead of that wiring"). This is not a gap this ADR introduces; the held-action handler wiring is separately tracked and out of this ADR's scope.

---

## Consequences

- **New runtime dependency:** Pydantic, added to `pyproject.toml`'s `dependencies`. This is the **first runtime dependency the codebase will actually import** — D010 named Pydantic in prose eleven-plus months before any code did, and this ADR is that first real usage, not a second one. E10-justified per Part B above on its own merits, not by appeal to D010 as precedent. Worth naming for whoever reads this ADR later: if D010's structured-output subsystem is ever built at M7/Phase 3 and independently reaches for Pydantic, that will be confirmation the earlier judgment was sound — but it is not yet, and this ADR does not pretend otherwise.
- **04_ARCHITECTURE.md Decision 002** is corrected in-place (transport clause only) and cites this ADR, matching the ADR-007 pattern for `04`'s open-question closure.
- **12_API.md §2 and §16** are corrected in the same edit that files this ADR — they asserted schema-backed registry entries before any mechanism existed. This is flagged as its own document-integrity finding, not merely "fixed by" this ADR: the claim was false independent of which way A/B ruled.
- **03_ROADMAP.md §8's RESERVED row** ("Registry→TypeScript API client generator") is updated: Rulings A and B are now scoped by this ADR; the generator itself (Ruling C) remains RESERVED, retriggered as "Pydantic schemas exist in `registry_json()` output" rather than "the generator itself does not exist yet, unscoped."
- **Explicitly NOT decided here** (flagged, not guessed):
  - **Ruling C — the actual TS-generation tool/pipeline.** Depends on B's real output shape once implemented, and touches `ui/`'s own toolchain (npm/Node), which this session did not read. Its own ADR, once B lands in code.
  - **`held_action.approve`'s missing handler.** Pre-existing gap (registry comment already names it), unaffected by this ADR; its params/response shape is deferred along with the handler itself.
  - **The event channel's transport binding.** Deferred as a separate binding under API-002; may or may not revisit FastAPI/Starlette at that point on its own merits (streaming ergonomics), independently of this ADR's operation-channel ruling.

---

*When code and this document disagree, one of them is wrong on purpose — file the ADR.*
