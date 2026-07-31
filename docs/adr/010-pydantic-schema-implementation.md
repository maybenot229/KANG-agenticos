# ADR-010 — Pydantic schema implementation: layout, attachment, null-schema contract, validation-error mapping

**Status:** proposed
**Date:** 2026-07-31
**Decides:** implementation details of ADR-009 Part B (Pydantic adopted; this ADR specifies how, not whether)
**Affected documents:** 12_API.md §2/§16 (schema field semantics), 17_PROJECT_STRUCTURE.md (new `api/schemas/` package, if Ruling 1 is confirmed), `src/kang/api/registry/__init__.py`, `src/kang/api/dispatch.py`
**Cites:** ADR-009 (this ADR's parent decision), 11_CODING_STANDARDS.md §4 (size limits), 12_API API-005 (unknown-field tolerance), API-006 (one error model), ADR-002 (precedent for "declared registry property, enforced centrally")
**Author's note:** this ADR's four rulings are drafted as recommendations by Claude (Founding Architect role), not yet confirmed by Kang. Per this project's DECIDED/GAP/TENSION protocol, nothing here is binding until Kang reviews and accepts — this document is staged as `proposed`, matching that state honestly. Each ruling below names its recommended option; alternatives are given equal weight in the options list so rejection is a real edit, not rubber-stamping.

---

## 1. Context

ADR-009 decided that Pydantic models attach to registry entries (Part B, option B1). It did not decide:

1. Where the model definitions physically live (file layout).
2. How a model attaches to a registry entry (explicit declaration vs. naming convention).
3. What the registry's schema field looks like for the two operations that have no handler yet (`held_action.approve`, `held_action.cancel`) — type contract, and `registry_json()`'s serialization of the absent case.
4. Where Pydantic validation runs in the dispatch pipeline, and how a `ValidationError` maps to API-006's closed error envelope.

Each is small in isolation but load-bearing: the first operation implemented under ADR-009 sets the pattern the remaining thirteen copy. Deciding these four together, before any model is written, avoids the exact silent-precedent risk ADR-009 itself was created to correct (D002's undocumented reversal, 12_API's unverified claim).

---

## Ruling 1 — File layout

### Options

**1A — `api/schemas/` package, one file per domain area (recommended).**

Group by the domain prefixes already visible in the registry (`task.*`, `memory.*`, `held_action.*`, `explain.*`, etc.) — e.g. `api/schemas/task.py`, `api/schemas/memory.py`, `api/schemas/held_action.py`. Each file holds that domain's request/response pairs.

- *For:* matches 17_PROJECT_STRUCTURE's existing convention of grouping by domain concept, not technical type (§5's "one responsibility per module" applied here). Naturally stays under the 400-line soft limit per file as the operation count grows — 14 operations today, more later, but each domain area's growth is bounded by that domain's own complexity, not the whole registry's. A reviewer touching `task.*` operations only ever opens `schemas/task.py`.
- *Against:* more files to navigate for a small registry today (14 operations, could arguably fit one file at current size). Adds one more directory to 17's dependency-legality matrix (trivial addition — schemas are pure data, same import legality as any other `api/` module). Worth noting: 17_PROJECT_STRUCTURE §4.1's dependency diagram already shows `domain/ports --> stdlib + pinned pure libs (pydantic)`, anticipating Pydantic at the ports/domain layer. This ADR places wire-contract schemas in `api/schemas/` instead, deliberately — 12_API §2 treats the wire shape as the API layer's own concern, distinct from domain representations (§4's `sensitivity=private` filtering is an existing example of wire shape diverging from domain shape). The two are not in conflict: `api/` legally imports `domain/ports` per the matrix, so `api/schemas/` may reuse or reference ports-layer Pydantic primitives without violating either document.

**1B — Single `api/schemas.py`, all operations.**

- *For:* simplest possible structure for the current size; one place to look.
- *Against:* per 11_CODING_STANDARDS §4's hard limit (800 lines), a single file housing 14+ growing operation pairs is a near-certain future violation — not hypothetical, given the registry is explicitly expected to grow (ADR-009's own "14-and-counting operation set" framing). Choosing this now means choosing a forced split later, under time pressure, with git-blame history fragmented across the split. Rejected on the same "cheap now, brutal to retrofit" logic ADR-009 itself used for the ID-scheme/revision-column precedent (D009).

**1C — One file per operation (28 files: request+response separated, or 14 if paired).**

- *For:* maximal isolation; a single operation's schema change touches exactly one file.
- *Against:* 14+ tiny files for what are often 10–20 line model pairs is ceremony without benefit at this scale — the opposite failure mode from 1B, and against E10's "boring, not maximal" spirit. Rejected — over-engineered for the current operation count; revisit only if a single domain area (e.g. `memory.*`) itself grows past ~10 operations and 1A's per-domain file gets unwieldy.

### Recommendation

**1A.** Domain-grouped package, matching existing conventions, sized to grow without a forced future split.

---

## Ruling 2 — Attachment mechanism

### Options

**2A — Explicit `OperationSchemas` dataclass parameter on `_op(...)` entries (recommended).**

A new dataclass, `OperationSchemas(request: type[BaseModel] | None, response: type[BaseModel] | None)`, defined alongside `OperationChannel` in the registry module. Each `_op(...)` call gains one new optional parameter, `schemas: OperationSchemas | None = None`, bringing the signature to 7 parameters — over the 6-parameter soft/hard threshold by one, same category of exception `OperationChannel` itself already required and documented (11 §4: "hard-limit exceptions require an inline justification comment naming the ADR or reason").

- *For:* directly matches the *actual* `OperationChannel` precedent this ruling cites — bundling into a dataclass specifically to avoid bare-parameter growth, per the registry module's own docstring ("bundled to keep `_op` under the size lint's parameter limit"). Kept as a distinct type from `OperationChannel` rather than added as fields on it, because `OperationChannel` is ADR-002's precisely-named concept for channel control (first_party_only, commit_mode) — schemas are a different concern, and conflating them would blur a boundary ADR-002 was deliberate about. Still requires the same inline hard-limit-exception comment `OperationChannel`'s own addition required, naming this ADR.
- *Against:* one dataclass more than strictly minimal (vs. bolting onto `OperationChannel`). Accepted — a wrong bundling now is harder to unwind later than one extra small type.

**2B — Naming-convention auto-resolution (`f"{operation_name.title()}Request"` looked up via `getattr` on the domain's schema module).**

- *For:* zero boilerplate at the registration site once the convention is established.
- *Against:* violates the exact principle ADR-002 established for channel controls — "a readable registry fact, not buried code." A convention-based lookup means the actual schema for an operation is not visible at its registration site; a reader must know the naming rule and go find the matching class in a different file. This is precisely the kind of implicit coupling 17_PROJECT_STRUCTURE's explicit-import discipline (§2, "cross-layer communication... never through... 'just this once' direct calls") exists to prevent, generalized to naming rather than imports. Rejected.

### Recommendation

**2A.** `OperationSchemas` dataclass parameter, correctly mirroring the ADR-002 bundling precedent (not the bare-parameter approach an earlier draft of this ruling mistakenly proposed).

---

## Ruling 3 — Null-schema contract for unimplemented operations

### Options

**3A — Typed `Optional`, explicit `null` in `registry_json()` output (recommended).**

`request_schema: type[BaseModel] | None = None` in the registry entry's type; `registry_json()` always emits the key, with value `null` when absent: `{"request_schema": null, ...}`.

- *For:* API-005 requires clients to tolerate unknown *response* fields (forward-compatibility), which doesn't by itself mandate handling absent ones — but an *explicit* `null` is a stronger, more honest signal than an *omitted* key regardless, and is consistent in spirit with API-005's general tolerance posture. A client checking `"request_schema" in entry` behaves identically either way, but a client naively doing `entry["request_schema"]` fails loudly (`KeyError`) under omission and fails informatively (gets `None`, can branch on it) under explicit null. Matches API-006's general house style: absence of a thing is stated, not implied (`degraded_result` is a marker, not a missing field, on the same philosophy).
- *Against:* marginally larger JSON payload per unimplemented operation (two keys × two currently-unimplemented ops — negligible).

**3B — Omit the schema keys entirely when absent.**

- *For:* smaller payload; "if it's not there, it doesn't exist" is arguably simpler.
- *Against:* pushes the null-check burden onto every client implicitly, rather than the registry stating the fact once, explicitly. Also inconsistent with how the registry already treats other optional-but-declared properties (`OperationChannel`'s fields are present with default values, not omitted, per the pattern already committed to in ADR-002's implementation). Rejected for consistency with existing registry conventions.

### Recommendation

**3A.** Explicit `null`, consistent with existing registry philosophy and with API-006's "state the absence" house style.

---

## Ruling 4 — Validation failure → error mapping

### Options

**4A — Validation runs in `Dispatcher._validate`, `ValidationError` maps to `invalid_request` with a sanitized `details` payload (recommended).**

Extend the existing `_validate(entry, request)` method (already present in `dispatch.py`, currently checking only idempotency-key presence for commands) to additionally parse `request.params` against `entry["request_schema"]` when present. A Pydantic `ValidationError` is caught at this single point and re-raised as `ApiError("invalid_request", ..., details={"field_errors": [...]})`, where `field_errors` is a sanitized list — field path + a short human message per error (Pydantic's `.errors()` output, stripped of `input` (raises leakage risk: could echo back e.g. a private-tier value verbatim) and `ctx` (internal, implementation-specific) — see below).

- *For:* single choke point (mirrors 11_CODING_STANDARDS §9's "every `except` block either re-raises enriched, translates to a typed error, or is a documented supervision point" — this makes `_validate` that documented point for schema failures specifically). Reuses the existing `invalid_request` code rather than inventing a new one — no change to API-006's closed enum required. Sanitization matters concretely: Pydantic's raw `.errors()` includes an `input` field echoing the exact value that failed validation, which for a `private`-tier field (e.g. a malformed prayer-journal entry payload, per D010/PRD §10.14) would put sensitive content into an error response and, downstream, into logs/audit at exactly the point 10_SECURITY's threat model tries hardest to avoid it leaking. The sanitized version keeps only field path + message type, never the offending value itself.
- *Against:* one extra transformation step per validation failure (stripping `input`/`ctx`). Accepted — this is the actual security-relevant work, not overhead to be trimmed.

**4B — Let `ValidationError` propagate to the existing bare-`Exception` handler, map to `internal`.**

- *For:* zero new code — `Dispatcher.dispatch`'s existing catch-all already turns any unexpected exception into `internal`.
- *Against:* wrong semantically — a validation failure is a client mistake (`invalid_request`, non-retryable-as-is, the client must fix its input), not a server fault (`internal`, API-006's `retryable: true` class). Collapsing the two would make every malformed request look like a KANG bug to the client and to audit, which actively misleads the exact "why did this fail" diagnosis API-006 exists to support. Rejected — repeats the "one error code doing two jobs" anti-pattern API-006 was written to prevent, applied to the new schema-validation case that didn't exist when API-006 was originally decided.

### Recommendation

**4A.** Single choke point in `_validate`, sanitized `field_errors`, no change to the closed error enum.

---

## Consequences (pending acceptance)

- `api/schemas/` package created (Ruling 1); `pyproject.toml` unaffected further (Pydantic dependency already added under ADR-009).
- `registry/__init__.py`'s `_op(...)` signature gains one new optional `OperationSchemas` parameter (Ruling 2, corrected); all 14 existing call sites require updating — a mechanical, template-able change once the pattern is set on the first 1–2 operations and confirmed correct, then applied to the remaining twelve.
- `registry_json()`'s output schema changes (Ruling 3) — any future TS-generation work (Ruling C, still RESERVED per 03_ROADMAP §8) must account for the explicit-null contract from the start, avoiding a second migration later.
- `dispatch.py`'s `_validate` method is extended, not replaced (Ruling 4) — the existing idempotency-key check and the new schema check both live there as the documented supervision point for command validation.
- Explicitly NOT decided here:
  - Which operation is implemented first (a real scheduling question, not an architecture question — deferred to whatever sequencing 18_IMPLEMENTATION_MASTER_PLAN or Kang's own judgment sets).
  - Whether `response_schema` validation applies to the Core's own outgoing responses (validate-on-the-way-out, catching a Core bug before a client sees a malformed response) or is purely documentation/generation-facing (Ruling C input only, no runtime enforcement). This is a real open question worth its own ruling once Ruling 1–4 are confirmed and the first operation is actually implemented — flagged, not guessed at.

---

*When code and this document disagree, one of them is wrong on purpose — file the ADR.*
