# ADR-038 — The Model Router and `TaskSpec`: D010, actually decided

**Status:** accepted (2026-09-14)
**Date:** 2026-09-14
**Supersedes:** none — D010 (04_ARCHITECTURE §11) is cited everywhere as M7's constitutional home for this but has never itself been expanded into an implementable design; this ADR is that expansion, not a reversal
**Affected documents:** none yet — this ADR is the design; `04_ARCHITECTURE.md`, `05_AGENTS.md` §12 (AG-008), `07_DATABASE.md` §5.5 (`model_call`), `08_PLUGIN_SYSTEM.md` (`sdk.models`) all already describe the destination and need no correction, only implementation
**Cites:** 04_ARCHITECTURE D010 (`docs/04_ARCHITECTURE.md:464-491`, the Model Router decision), AG-008 (`docs/05_AGENTS.md:323-335`, hierarchical budgets — already accepted, this ADR must not contradict it), 07_DATABASE §5.5 (`model_call` table, `docs/07_DATABASE.md:520-528`), 10_SECURITY SEC-011 (`docs/10_SECURITY.md:157-161`, secrets stay in the OS keychain), ADR-028 (M7 foundations — this is the first slice of its "in any order" list, Kang's own choice), ADR-035 (the precedent for adding a dependency via ADR alongside its first real use)
**Related:** [[028-m7-foundations.md]] — this is the first of that ADR's sequenced-but-unordered M7 slices

---

## Context

`kernel/router/__init__.py` has said `"""Model router, TaskSpec mapping, budget ledger. Constitutional home: 04_ARCHITECTURE D010 (built at M7 — 18 §3)."""` with `__all__: list[str] = []` since the file was scaffolded. Three adapter stubs — `adapters/anthropic/`, `adapters/openai/`, `adapters/ollama/` — each cite D010 too, each empty. D010 itself, read in full (`04_ARCHITECTURE.md` §11), is a real, detailed decision — a `TaskSpec`-driven router behind a `ModelProvider` port, fallback chains, a usage ledger, structured-output discipline — but it has never been converted into a design with actual types, an actual port signature, or an actual first caller. That conversion is this ADR's whole job.

**What is already decided and must not be re-litigated here:**
- **D010** (`04_ARCHITECTURE.md:466-491`): the Router shape, `TaskSpec`'s four dimensions, fallback chains + circuit breakers, structured-output discipline, `providers.toml` as the routing config's home.
- **AG-008** (`05_AGENTS.md:323-335`, already accepted): the budget hierarchy (monthly → per-task-class → per-invocation caps), the escalation policy, the three-threshold degradation ladder (80%/95%/100% + emergency reserve), all "in `providers.toml`," all "enforced by the Model Router."
- **`model_call`'s schema** (`07_DATABASE.md:520-528`, already written, not yet migrated): `provider, model, task_class, tokens_in, tokens_out, cost_usd, latency_ms, outcome, at`, optionally linked to `agent_invocation` (also not yet migrated — M7's own table, out of this ADR's scope).
- **SEC-011** (already accepted): raw provider API keys live in exactly one place, the OS keychain; adapters request them by name at call time; no caching, no config-file storage.

**What is genuinely new ground, investigated for this ADR:**
- No `ModelProvider` port exists (`domain/ports/` has 21 files, none of them this).
- No `providers.toml` exists — not even a stub, unlike `kang.toml`/`permissions.toml`.
- **No credential subsystem exists at all.** SEC-011 names the destination (OS keychain, request-by-name, in-memory-only) but zero code reads from Windows Credential Manager today. A *real* Anthropic adapter — one that can make a real API call — needs this first, and it is its own genuine unit of work (Windows-specific, its own port + fake + real adapter, its own test discipline for "never logs a secret"), not a two-line addition to this ADR.
- No dependency on the `anthropic` Python SDK exists yet (`pyproject.toml`'s three runtime dependencies: `tzdata`, `pydantic`, `aiohttp`) — a new dependency, needing its own E10 paragraph (below), same discipline ADR-035 used for `aiohttp`.
- `TaskSpec`'s exact four fields are assembled from two sentences in two different documents, not one: `04_ARCHITECTURE.md:479` gives *"task class (`deep_reasoning | routine | classification | embedding | private`), context size, latency tolerance, privacy tier"* — four items, but `private` already appears as a `task_class` enum value, and a *separate* `privacy_tier` is also named. Read in isolation this looks redundant. It is not: `06_MEMORY.md:239` and `07_DATABASE.md:220` already establish `sensitivity` (`normal | sensitive | private`) as memory's own content-sensitivity vocabulary, entirely independent of what *kind* of cognitive work is being requested — a `routine`-class classification call can still carry `sensitivity=private` content (classifying a prayer-journal entry, PRD §10.14's own extreme example). **Decided here:** `TaskSpec.privacy_tier` reuses that exact three-value `sensitivity` vocabulary, not a fifth invented one, and it is orthogonal to `task_class` — a caller may declare `task_class=routine, privacy_tier=private` and the router must honor both independently, never inferring one from the other.

---

## Decision

### D1 — Scope this slice: the port, the fake, and the router's own logic. The real Anthropic adapter and the credential subsystem are their own next slice, not folded in here

This is the load-bearing call this ADR makes, mirroring ADR-036 D1's own discipline (a real recommendation, not a punt):

Ship `domain/ports/model_provider.py` (the `ModelProvider` port), `adapters/fakes/model_provider.py` (a fake — CLAUDE.md §5: "ports before implementations; fakes with ports"), and `kernel/router/` (the actual routing/fallback/logging logic) — fully real, fully tested, with zero dependency on live credentials or a live model call. **Not** shipped this slice: `adapters/anthropic/`'s real implementation, and the credential subsystem SEC-011 requires it to use.

**Why not build the real adapter too.** Every other port in this codebase was proven against a fake before (often without) a real adapter existing in the same change — the stores, the startup lock, the audit log. The router's own correctness (does it pick the right provider for a `TaskSpec`, does it fail over on a provider error, does it fail closed on `privacy_tier=private` with no local provider configured, does it log every call) is fully provable against a fake `ModelProvider` that returns configured responses/errors on demand — a real network call proves nothing about this logic that a fake doesn't, and it adds two genuinely separate units of work (Windows Credential Manager access; the `anthropic` SDK's actual request/response shape) that each deserve their own scrutiny rather than riding along. The real adapter becomes ADR-028's list unblocked at zero cost — the port and the config schema are exactly what it will implement against, decided here, not re-litigated then.

**What this means concretely:** after this slice, the router is real, tested, and callable — by nothing yet, since no caller (executor, chat, orchestrator) exists either (both are separate ADR-028 list items). This is the same "lowest-risk first slice, dormant if the next one slips" shape ADR-036 D3 used for `WriteExecutor`/`ReadPool` before D4 had a caller for them.

### D2 — `TaskSpec`: the four fields, decided precisely

```
TaskSpec:
  task_class:     "deep_reasoning" | "routine" | "classification" | "embedding" | "private"
  privacy_tier:   "normal" | "sensitive" | "private"      # reuses `sensitivity`'s exact vocabulary (06_MEMORY §…, 07_DATABASE §5.1) — not invented
  context_size:   int                                      # approximate input tokens the caller intends to send; the router's own estimate, never a hard promise from the caller
  latency_tolerance: "interactive" | "background"           # interactive: user is waiting (chat, a confirmation dialog's content); background: a scheduled job, a monitor sweep
```

`task_class="private"` is reserved for work that has **no other honest class** — not a shortcut for "content happens to be sensitive" (that's `privacy_tier`). A caller with `task_class=routine, privacy_tier=private` is the common case (classify this private journal entry cheaply); `task_class=private` alone, with `privacy_tier=normal`, would be unusual but not forbidden (a task that must run local-only by its own nature, unrelated to content sensitivity — RESERVED for whatever Phase 5's Ten-Year Dream migration actually needs it for).

### D3 — The `ModelProvider` port: one call shape, structured-output discipline built in, typed failure

One method, matching D010's own "structured-output discipline: all machine-consumed outputs are schema-validated... invalid output → bounded retry → typed failure" verbatim:

```
ModelProvider.call(spec: TaskSpec, prompt: ..., response_schema: type[BaseModel] | None) -> ModelResult
```

- `response_schema=None` → the call is free-text (chat, a prose synthesis step); `ModelResult.text` carries the output.
- `response_schema=SomeModel` → the adapter is responsible for the bounded-retry-then-typed-failure contract itself (an adapter concern, not the router's — the router doesn't know or care whether a given call asked for structured output, only whether it succeeded or raised).
- `ModelResult` carries `text: str | None`, `structured: BaseModel | None`, `tokens_in`, `tokens_out`, `latency_ms` — everything `model_call`'s schema needs, produced once, not reconstructed later from a log line.
- Failure is a small closed set of typed exceptions (mirroring `ApiError`'s discipline, not `Exception`): `ProviderUnavailable` (network/5xx — fallback-chain-eligible), `ProviderRefused` (4xx, bad request shape — never retried, a caller bug), `StructuredOutputInvalid` (bounded retry exhausted). No bare `Exception` crosses the port boundary.

### D4 — The Router's own behavior: `providers.toml`-driven, fallback chains, circuit breakers, privacy enforcement, every call logged

- **Config-driven mapping**, per D010's own text: `providers.toml` (new file, `config/defaults/providers.toml` shipped, `%KANG_HOME%/config/providers.toml` the Kang-editable copy — same two-tier pattern as `kang.toml`/`permissions.toml`) maps each `task_class` to an ordered provider chain. Loaded once at `build_core` time by a new `providers_loader.py` (mirroring `permissions_loader.py`'s own shape: fail-closed semantics decided there, not invented fresh here — see D5).
- **Fallback chains + circuit breakers (D010's own "fallback chain… never a silent hang"):** the router tries a chain's providers in order; a `ProviderUnavailable` advances to the next; a provider that has failed recently is skipped for a cooldown window (the circuit breaker) rather than retried immediately — exact cooldown duration and failure-count threshold are implementation detail (D010 names the mechanism, not the constants), configured in `providers.toml`, not hardcoded. `ProviderRefused` does NOT advance the chain (a caller bug retrying against a different provider would just fail differently) and propagates immediately.
- **Privacy enforcement, fails closed:** `privacy_tier="private"` restricts the candidate chain to providers `providers.toml` marks `local_only = true`. Today, with no Ollama adapter built (Phase 5, RESERVED — 03_ROADMAP §8), that chain is empty by construction for every task class, so the router raises a typed `NoProviderAvailable` rather than silently routing to a cloud provider — the exact "fails closed" behavior D010 already names, provable now even though the mechanism it protects (a real local provider) doesn't exist yet.
- **Every call logged, regardless of outcome (AG-008's ledger half):** on `ok`, `error` (from `ProviderRefused`), `timeout`, or `fallback` (a chain advance), the router writes one `model_call` row via a new `ModelCallStore` port + SQLite adapter, mirroring every other store in this codebase. This satisfies AG-008's "every call lands in `model_call`" literally.
- **Budget *enforcement* (thresholds, degradation, the emergency reserve) is explicitly NOT this slice.** `providers.toml`'s schema includes the cap fields AG-008 already specifies (monthly global, per-task-class, per-invocation) so the config shape is right from the start, but the router does not read or act on them yet — every call proceeds regardless of spend. This is a real, named gap against an already-accepted decision (AG-008), not a silent partial implementation: **RESERVED, trigger = a real caller exists to generate real spend to threshold against** (the budget ledger is ADR-028's own separate sequencing item; enforcing caps with zero calls ever made to test the thresholds against would be designing blind, the same reasoning ADR-036 D1 used against pre-paying for interleaving nothing needs yet).

### D5 — `providers.toml` fails closed like `permissions.toml`, not open like `kang.toml`

`_load_grants`'s existing pattern (`composition.py`) treats an absent/invalid `permissions.toml` as `KANG_ONLY_GRANTS` — fail closed, because permissions are an authority surface. `providers.toml` is the same class of surface (it decides which provider a `privacy_tier=private` call may ever reach) — **decided here:** an absent or invalid `providers.toml` yields an empty provider chain for every task class, not a default-open "try everything" fallback. Every call fails with `NoProviderAvailable` until `providers.toml` is present and valid — the same fail-closed posture 07 F8 already establishes for grants, extended here because the risk (a misconfigured router silently sending `private`-tier content somewhere) is the same shape.

### D6 — New dependency: the `anthropic` Python SDK (E10 justification)

Not used by this slice's own code (D1 defers the real adapter) but declared now, alongside the port it will implement against, matching ADR-035's own "declare ahead of the code that uses it" precedent (`aiohttp` was added to `pyproject.toml` a full slice before `http_binding.py` actually used it).

**E10 justification.** Anthropic's own official Python SDK: actively maintained by the model vendor itself (not a third party), typed request/response models (matches D010's structured-output discipline directly — the SDK's own Pydantic-based response types are what `ModelResult` wraps, not reinvented), handles the vendor's own auth/retry/streaming semantics correctly by construction rather than by this project reimplementing an HTTP client against a moving target. Alternatives considered: hand-rolled `aiohttp` calls against Anthropic's REST API directly (rejected — ADR-011's own precedent: "reinvents a solved problem" for a vendor SDK that already exists and is free; this project already accepted `aiohttp` itself on the "don't hand-roll a solved problem" reasoning, this is the same call one layer up); LiteLLM/OpenRouter as a unifying abstraction (D010 itself already rejected this as the *port's* implementation — "the port stays ours" — but leaves room for an adapter to use one internally; not adopted here because the Anthropic SDK alone is sufficient for the one real adapter this ADR scopes toward, and adding a second abstraction layer under a port that already exists to be the abstraction is exactly the "framework gravity" D010 warns against).

---

## Consequences

- **D010 goes from cited-everywhere to actually implementable.** The port, `TaskSpec`, and the router's own decision logic exist and are tested; nothing downstream (the executor, chat, the budget ledger, the degradation ladder) is blocked on rediscovering what a `TaskSpec` is or what the port looks like.
- **AG-008's ledger half is real; its enforcement half is a named, scoped gap**, not a silent one — every call is logged to `model_call` from this slice forward, so the degradation-ladder slice inherits real data to threshold against instead of having to backfill it.
- **The real Anthropic adapter and the credential subsystem are explicitly deferred**, unblocked at zero cost (the port and `providers.toml`'s schema are exactly what they implement against) — named here so the next session doesn't rediscover the credential-subsystem gap from scratch.
- **`private`-tier calls fail closed today, by construction**, not by a runtime check that could be bypassed or forgotten — there is no cloud fallback path to accidentally take, because the empty local chain is what `providers.toml` actually contains until Ollama's adapter exists.
- **A new runtime dependency** (`anthropic`) lands with its E10 paragraph in this ADR, one slice ahead of its own first real use — same shape as `aiohttp`/ADR-035.

## Verification

Deferred to the implementation slice this ADR authorizes (a design ADR proves nothing by itself — 13_TESTING's own discipline). Expected proof, named now so the implementation is graded against it: `TaskSpec`/`ModelProvider`/`ModelResult` typed and covered by unit tests against the fake; the router's fallback-chain, circuit-breaker, and fail-closed-on-`private` behavior each provable deterministically (injected clock for cooldown timing, no real sleep, no network) against `FakeModelProvider`; `providers.toml`'s fail-closed loader tested the same way `permissions_loader`'s own fail-closed test already is; every call path (`ok`/`error`/`timeout`/`fallback`) verified to write exactly one `model_call` row via a new `ModelCallStore` fake; zero live network calls anywhere in the test suite (13_TESTING §1: "no network").
