# ADR-011 — Registry→TypeScript client generator: json-schema-to-typescript

**Status:** proposed
**Date:** 2026-08-01
**Decides:** the RESERVED item in `03_ROADMAP.md` §8 ("Registry→TypeScript API client generator... only the generator/pipeline itself remains RESERVED") — Ruling C, deferred by ADR-009 pending ADR-010's schemas actually existing in code.
**Affected documents:** `03_ROADMAP.md` §8 (RESERVED row retired), `17_PROJECT_STRUCTURE.md` §2 (new `tools/generate_ts_client/` or equivalent, and `ui/src/generated/` as the client's home), `18_IMPLEMENTATION_MASTER_PLAN.md` §3 M6 ("UI on the generated client only")
**Cites:** ADR-009 Part B (Pydantic schema authority), ADR-010 (schema implementation, now landed for 7 operations across `task.*`, `deadline.*`, `plan.generate`, `notification.ack`, `explain.invocation`), 12_API §16 (`registry.get`/`registry_json()` as the contract's served source of truth), 17_PROJECT_STRUCTURE §4.3 rule 10 (`ui/` imports nothing but the generated client — reimplementing core logic in TS is the review-fatal equivalent), 11_CODING_STANDARDS §25 (E10 dependency justification)
**Related:** `docs/guides/session-2026-07-31-adr010-rollout.md` (confirms `registry_json()` now serves real JSON Schema for the operations this generator will consume)

**Author's note:** drafted by Claude (Founding Architect role) per Kang's 2026-08-01 decision to proceed with "ADR + `json-schema-to-typescript`" for M6's hard dependency. Per this project's DECIDED/GAP/TENSION protocol, this document is staged `proposed` until Kang reviews it; implementation proceeds in parallel per his explicit go-ahead for M6 work, and this ADR is reviewable independently of that code landing.

---

## 1. Context

`registry_json()` now serves real JSON Schema for `request_schema`/`response_schema` on 7 of KANG's 14 registered operations (ADR-010, landed 2026-08-01) — the schemas for `task.create`, `task.get`, `deadline.create`, `deadline.sweep`, `plan.generate`, `notification.ack`, and `explain.invocation`. `held_action.*` and four `explain.*` stub operations correctly still serve `null` (no handler yet, or no live subject yet).

M6 ("Kang can see it") gates on the UI being built "on the generated client only... zero non-client imports" (18 §3). No generator exists. `ui/` currently has no `package.json` anywhere — only `ui/shell/` (a Tauri/Rust project: `Cargo.toml`, `Cargo.lock`, no npm) and `ui/src/index.html` (a 170-byte static stub, no build tooling). This ADR's implementation is sequenced *after* `ui/src/`'s Vite+React+TypeScript scaffold lands (a separate piece of M6 work, this same session) — the generator's devDependency needs a real npm project to attach to, not a placeholder.

`03_ROADMAP.md` §8's RESERVED row for this item already records its own trigger condition as satisfied: *"Pydantic schemas exist in `registry_json()` output (i.e. ADR-009 Part B implemented in code, not merely decided)."* That condition is now true. This ADR is the ruling the row has been waiting for.

---

## Ruling — the generator toolchain

### Options

**A — `json-schema-to-typescript` (recommended).**

A mature, single-purpose npm package (`bcherny/json-schema-to-typescript`) that converts JSON Schema documents into TypeScript type declarations. Widely used, MIT-licensed, no runtime footprint (dev-time codegen only — nothing it produces depends on it at runtime).

- *For:* does exactly one thing, well — JSON Schema → TS types, nothing else. `registry_json()` already serves standard JSON Schema (via Pydantic's `.model_json_schema()`, itself a standard, spec-compliant emitter — ADR-010's own implementation notes this). No custom parsing to write or maintain; the E10 cost is bounded to "one small, focused, widely-used devDependency" rather than an ongoing maintenance burden. Directly satisfies the boring-tech bar: converting schema-to-types is a solved problem with an established, stable tool — writing a bespoke converter would be re-solving it worse.
- *Against:* a real new devDependency (this project's first Node-side one, since `ui/` has had none at all until this session's Vite scaffold). Node/npm supply-chain surface, however dev-time-only and however narrow the package's own dependency tree.

**B — Hand-written thin converter (no new dependency).**

A small Python or Node script that walks `registry_json()`'s `properties`/`required`/`type` fields directly and emits matching `interface` declarations.

- *For:* zero new dependency, of any kind, ever. Total control over the exact output shape.
- *Against:* JSON Schema is a real specification with real edge cases this project's schemas already exercise or will soon — `anyOf` (every `Optional[...]` field, e.g. `plan_date: str | None`), `$ref`/`$defs` (nested models, e.g. `ExplainInvocationResponse.chain: list[AuditChainEntry]`, which Pydantic emits as a `$ref` to a `$defs` entry), enums, `default` values, `additionalProperties`. A hand-written converter either reimplements a real spec (the "boring tech" argument turned backwards — this is the *harder*, not easier, path once nested models exist, and `ExplainInvocationResponse` already has one today) or silently mishandles a case until someone notices the generated `.ts` file is wrong. That failure mode — a client type that quietly doesn't match the schema it claims to describe — is exactly the kind of self-contradicting-document defect this whole engagement has spent multiple sessions finding and correcting elsewhere in this project. Rejected: cheaper now, worse later, on a spec that already has real complexity in this codebase's own schemas.

**C — A heavier, opinionated client generator (e.g. `openapi-generator`, full OpenAPI toolchains).**

- *For:* generates a complete typed client (not just types) with request/response wiring built in.
- *Against:* KANG's registry isn't OpenAPI — `registry_json()` is a bespoke, simpler document (12_API §16's own format, deliberately not OpenAPI: one flat operation list, not path-based routing). Adopting an OpenAPI-shaped tool would mean either fabricating an OpenAPI document as an intermediate step (a second schema representation to keep in sync — the exact anti-pattern 14.5's "content in two places disagrees in two places" names) or fighting the tool's assumptions the whole way. Heavier dependency, worse fit. Rejected.

### Decision

**Adopt A — `json-schema-to-typescript`.** Types only, generated into `ui/src/generated/`; the thin request/response *calling* code (the actual `fetch`/session-token/correlation-id plumbing to KANG's stdlib `http.server` binding, per ADR-009) is hand-written once, directly, using those generated types — not generated itself, since that plumbing is a handful of lines against a single `POST /op` endpoint (`http_binding.py`), not a per-operation routing table an OpenAPI-style generator would earn its keep on.

**Pipeline, concretely:**
1. `registry_json()` (Python, existing) → written to a build-time artifact (a JSON file, or piped directly).
2. `json-schema-to-typescript`'s Node API (not just its CLI, since KANG's registry isn't literally one schema file — it's an array of operations each carrying a named schema, `TaskCreateRequest` etc.) is called once per non-null `request_schema`/`response_schema`, keyed by the schema's own `title` (already present in Pydantic's output — see the example in §1 above: `"title": "TaskCreateRequest"`), and interfaces are emitted into one generated file (or one file per operation prefix, mirroring `api/schemas/`'s own layout for the same reason ADR-010 Ruling 1 gave — grouped by domain, bounded growth).
3. Output lands at `ui/src/generated/` — read-only by convention, rebuilt by the tool, never hand-edited (12_API §16: "generated from truth, never hand-written"; matches `docs/generated/`'s existing rule for the same reason, 17 §12).
4. The generator script itself lives under `tools/` (Node, since it drives an npm package — `tools/` is dev-only and "never imported by src/," language-agnostic per its own rule) OR as an `npm run generate` script inside `ui/`'s own `package.json`, whichever the Vite scaffold's actual project shape makes more natural — **left to implementation, not a design fork**, since both satisfy every constitutional rule this ADR cites identically (dev-only, not imported by src/, output is the only thing `ui/` consumes).

---

## Consequences

- **First Node-side dependency of the project.** `json-schema-to-typescript` (a devDependency) joins whatever `ui/`'s Vite+React+TypeScript scaffold already requires. E10-justified above, on its own merits.
- **`03_ROADMAP.md` §8's RESERVED row is retired** — its trigger is satisfied and this ADR is the ruling it was waiting for.
- **`ui/src/generated/` becomes a real, generated-only directory** — hand-editing it is a defect, same discipline as `docs/generated/` and root `CLAUDE.md`.
- **Only operations with a non-null schema get generated types.** `held_action.approve`/`.cancel` and the four `explain.*` stubs currently produce no client type — correct, since they have no real contract yet (ADR-010 Ruling 3). The generator MUST NOT fabricate a placeholder type for a `null` schema; a client screen needing one of these operations before its schema lands is itself a signal that operation isn't ready for UI consumption yet, not a gap to paper over.
- **Explicitly NOT decided here:**
  - Whether the generator runs as a manual `npm run generate` step or is wired into the build pipeline automatically (CI-checked freshness, à la `tools/build_root_docs.py --check` for `CLAUDE.md`) — a real question, deferred to implementation, where the actual dev workflow friction can be felt rather than guessed at.
  - The exact file-per-operation vs. file-per-prefix vs. one-big-file layout inside `ui/src/generated/` — implementation detail, not a decision with constitutional weight (unlike `api/schemas/`'s layout, which ADR-010 Ruling 1 spent real reasoning on because it affects hand-written code humans read and extend; generated output is read by nobody, only imported).

---

*When code and this document disagree, one of them is wrong on purpose — file the ADR.*
