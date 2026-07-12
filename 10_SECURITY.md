# KANG — Security Constitution

**Document:** 10_SECURITY.md
**Version:** 0.1
**Author:** Kang, with Claude (Founding Architect)
**Status:** Normative — RFC-2119 throughout; changes require an ADR; RESERVED items carry activation triggers
**Last updated:** 2026-07-11
**Upstream (binding):** `00_VISION.md`, `01_PRINCIPLES.md` (S1–S7), `02_PRODUCT_REQUIREMENTS.md`, `04_ARCHITECTURE.md` (D013), `05_AGENTS.md` (§8, §9, §15), `06_MEMORY.md` (Part IV, XII), `07_DATABASE.md` (Part 11, 12, 15), `08_PLUGIN_SYSTEM.md` (§3, §9), `09_UI_DESIGN.md` (§7)
**Role:** This document does not replace the security content of upstream documents — it is their constitution: the unifying model, the threat honesty, and the decisions that bind every future security choice.

---

## 1. Security Philosophy

KANG's security exists to protect one thing above all: **a decade of earned trust between one human and his system.** From that, nine commitments:

1. **Honesty over security theater.** Every protection is described with its real strength and its real limits. A guard that is tamper-evident is called tamper-evident, never tamper-proof (08_PLUGIN §8). Theater costs complexity and buys lies; lies compound into misplaced reliance, which is the actual vulnerability.
2. **Local-first assumptions.** The perimeter is Kang's machine (P8). There are no accounts to breach, no server to attack, no tenant isolation to fail. Most of the industry's threat surface is absent *by architecture*, and this document refuses to import defenses for threats the architecture removed.
3. **Integrity before secrecy.** The catastrophic failure is not someone *reading* Kang's task list — it is KANG *believing something false*: a fabricated memory, a tampered deadline, a silently corrupted database. Resources flow to integrity first (provenance, gates, checksums, audit), secrecy second (encryption where it earns its place: private records, future sync).
4. **Explainability before automation.** An action KANG cannot explain is an action KANG must not take (P5). Explanation infrastructure (manifests, correlation ids, audit) is security infrastructure — it is how compromise, confusion, and bugs are *detected*.
5. **Deliberate authority.** Authority in KANG is never ambient. It is granted (scopes), scoped (least privilege), checked at use (tool executor), and — for consequences — confirmed live by the human (S1). Nothing possesses authority by being clever, persistent, or insistent.
6. **Least privilege, structurally.** Not a policy aspiration: pairing constraints, read/act separation, and closed allowlists make over-privilege a *lint failure*, not a judgment call (05_AGENTS §8).
7. **Fail visibly (DB-P7 generalized).** Every security mechanism prefers loud failure over silent bypass or silent block. A denied action is surfaced; a corrupted store freezes; a confused agent quarantines.
8. **Recovery over prevention.** Prevention will eventually fail — a bug, an injection, a mistake by Kang himself. The system's real resilience is that any state can be explained (audit), contained (quarantine), and restored (verified backups, tombstones, revision history). Security that cannot recover is brittleness with a padlock icon.
9. **Trust boundaries are few and explicit.** Every boundary in §3 is a place where enforcement code exists. Anything not on that list is *not* a boundary and MUST NOT be treated as one in design discussions.

---

## 2. Threat Model

### 2.1 In scope (defended)

| Threat | Primary defenses |
|---|---|
| Accidental bugs (Kang's own code — the #1 threat) | Types, constraints-in-schema, tests, transactions, fail-visible, backups |
| Prompt injection via web/email/notes | §5 — the complete model |
| Malicious/manipulative web content | UNTRUSTED tagging, read/act separation, domain scoping |
| Malicious or confused LLM outputs | Models-suggest-never-act (SEC-002), schema validation, gates |
| Hallucination reaching persistence | Memory write gate (M-003); no confidence bypass exists |
| Stale/contradictory memory | Lifecycle, staleness probes, contradiction surfacing (06_MEMORY) |
| Database/filesystem corruption | integrity_check, WAL, verified snapshots, derived-rebuildability (07_DATABASE Part 15) |
| Kang's own mistakes | Confirmations, 30-day deletion recovery, revision history, restore |
| Plugin bugs | Supervision, timeouts, quarantine, zero-hard-dependency core (PL-009) |
| Plugin over-reach (accidental) | Kernel-only doors, import guards (tamper-evident), scoped grants |
| Permission misconfiguration | Default-deny, pairing lints, grant UI with consequence lines, audit |
| Data tampering (casual/tooling-level) | Append-only audit, checksummed migrations, tamper-evident logs |
| Lost/stolen device | BitLocker requirement + sealed-box private content (DB-005) |
| Runaway automation / cost | Budgets, caps, kill-switch, rate limits (AG-008, D013) |

### 2.2 Explicitly out of scope (Phase 1 — stated, not hidden)

KANG does NOT attempt to defend against: nation-state or targeted professional attackers; OS/kernel compromise; malware already running as Kang (it owns everything KANG owns — S3's threat honesty); physical coercion; hardware implants; supply-chain compromise of Python/SQLite themselves; a malicious plugin Kang chose to install (PL-001: trust basis is authorship). Pretending otherwise would be theater (§1.1). The honest mitigations for these are outside KANG: OS updates, disk encryption, physical security, and Kang's judgment.

---

## 3. Trust Boundaries

The complete chain. Each boundary names its enforcement point and what legitimately crosses:

```
Kang (highest authority)
  │  crosses: intents, confirmations, grants, edits          [UI: unique confirm dialogs §9-UI-§7]
  ▼
UI (pure client, zero authority)
  │  crosses: API calls with session identity                [Local API: localhost-only, D002]
  ▼
Core kernel (Orchestrator · Scheduler · Bus)
  │  crosses: invocations with principal + correlation id    [Admission: registry, idempotency, budget]
  ▼
Permission Engine
  │  crosses: grant snapshots; scope checks per call         [grant_ table ⇄ permissions.toml; default-deny]
  ▼
Tool Executor  ←— the ONLY place words become actions
  │  crosses: validated tool calls; confirmation tokens      [per-call re-check; consequential gate; input hostility]
  ▼
┌───────────────┬──────────────────┬──────────────────┐
│ Memory Gate   │ Model Router     │ Adapters          │
│ [M-003: no    │ [TaskSpec only;  │ [minimum context; │
│  auto-commit] │  budgets; privacy│  keychain creds;  │
│               │  tiers]          │  UNTRUSTED wrap]  │
▼               ▼                  ▼
Stores          Models (zero       Filesystem/Vault ── External APIs ── Internet
(truth)         authority)         (scoped paths)      (allowlisted)    (hostile by default)

Plugins: enter ONLY at the SDK doors (08_PLUGIN §8) → same Permission Engine → same Tool Executor.
```

Rules: authority only flows **downward** and *attenuates* at every boundary (a component can never hand a callee more scope than it holds); data flows upward gain UNTRUSTED tags at the internet/filesystem/model edges and *keep them* (§5); no component may tunnel past a boundary "for efficiency" — a bypass is a severity-1 defect even when benign.

---

## 4. Constitutional Security Decisions

Format: Decision / Why / Alternatives / Trade-offs. (Scaling implications where non-obvious.)

### SEC-001 — Every external input is UNTRUSTED, transitively

**Decision.** Content from the internet, email, files not authored in-session, model outputs derived from such content, and plugin-fetched data is tagged UNTRUSTED at ingress and the tag propagates through every derivation (a summary of an untrusted page is untrusted). Tags are stripped only by Kang's explicit sanction (Tier-2 promotion through the memory gate).
**Why.** Provenance-based trust is the only injection defense that survives model improvement and attacker creativity — content-based filtering is an arms race KANG refuses to enter.
**Alternatives.** Injection classifiers/filters (rejected as primary: probabilistic defense for a deterministic problem; MAY exist later as telemetry, never as authority). Trusting "safe" domains (rejected: any domain can serve hostile content).
**Trade-offs.** Some friction: even excellent web findings must pass the gate to become memory. Correct — that *is* the gate working.

### SEC-002 — Models possess zero authority

**Decision.** Model output is always a proposal: text, a structured suggestion, or a *request* for a tool call. Authority lives exclusively in the deterministic chain (grants → executor → confirmations). No model output can grant, escalate, confirm, or persist anything by itself.
**Why.** A1/A2 made structural. Models are brilliant, confident, and unaccountable — the exact profile you never give signing power.
**Alternatives.** "Trusted model" tiers for well-behaved providers (rejected: trust in a stochastic system is a category error); constitutional prompts as enforcement (rejected: prompts shape, kernels bound — 05_AGENTS §15).
**Trade-offs.** Every model-initiated action pays a mediation cost. That cost *is* the architecture.

### SEC-003 — Consequences require live human confirmation

**Decision.** The closed consequential list (05_AGENTS Appendix D) requires per-action, out-of-band (UI-only), unbatchable confirmation. No standing approvals, no trusted mode, no expiry longer than the invocation, no text-channel confirmation.
**Why.** One unauthorized irreversible action costs more trust than a thousand confirmations (P6's recorded trade-off). Out-of-band is what makes injection *unable* to self-approve (§5).
**Alternatives.** Risk-scored auto-approval (rejected: the scorer becomes the attack surface); batch approvals (rejected: trains blind clicking).

### SEC-004 — Capabilities are the only authority model

**Decision.** All authority is expressed as capability scopes granted to principals, default-deny, checked at the executor. There is no role system, no admin flag, no ambient authority, no code path exempt from scopes except Kang acting through the UI as `kang`.
**Why.** One model, one enforcement point, one audit vocabulary (D013). Every additional authority mechanism is a gap between mechanisms.
**Alternatives.** RBAC (roles for a one-person system is ceremony); per-feature ad-hoc checks (rejected: drift, gaps).

### SEC-005 — No hidden execution

**Decision.** Every autonomous execution originates from a registered definition (agents, jobs, pipelines, hooks, subscriptions — all static manifests/registries), is admitted by the Orchestrator, and is visible in the invocation history. Dynamic code paths (eval of generated code, self-modifying definitions, runtime-registered triggers) MUST NOT exist.
**Why.** AG-004/PL-003 unified: "what can KANG do?" MUST be answerable by reading files; "what did KANG do?" by reading tables. Hidden execution breaks both questions at once.
**Alternatives.** Sanctioned dynamic tasks with logging (rejected: logging what unreviewable code did is archaeology, not control).

### SEC-006 — Every important action is attributable

**Decision.** Every write to truth, every tool call, every model call, every grant change, every lifecycle transition carries: principal, correlation id, timestamp, and (where applicable) reasoning — persisted in audit/invocation/ledger stores. Anonymous action is architecturally impossible: the executor and gate refuse calls without a principal.
**Why.** Attribution is detection, forensics, and honesty in one mechanism (S5). It is also what makes quarantine *targeted* rather than system-wide.
**Alternatives.** Sampling/log-level-based attribution (rejected: the un-logged action is always the one you needed).

### SEC-007 — Integrity outranks availability

**Decision.** On detected integrity failure (corruption, provenance violation, grant-store inconsistency), KANG freezes the affected write path and degrades — up to full read-only mode — rather than continuing on suspect state. The Planner's deterministic plan (05_AGENTS §10) keeps the secretary minimally alive during freezes; but a KANG that is up and lying loses to a KANG that is down and honest.
**Why.** R9: trust collapse comes from wrongness, not absence. Availability is recoverable in minutes (restore); believed-corruption is recoverable never.
**Alternatives.** Self-healing/auto-repair (rejected: silent repair is silent corruption with better PR — repairs happen through the visible restore protocol).

### SEC-008 — No automatic privilege escalation, no delegation amplification

**Decision.** No mechanism exists for a principal to gain scopes at runtime: no elevation API, no sudo-mode, no plugin requesting mid-run, no pipeline step inheriting a sibling's grants (each step runs under its own agent's snapshot). Grant changes are Kang-only, consequential, and apply from the *next* invocation (05_AGENTS §3.2).
**Why.** Elevation mechanisms become elevation attacks under injection (05_AGENTS §8). The absence of the mechanism is the defense — you cannot exploit a door that was never built.
**Alternatives.** Time-boxed elevation with confirmation (rejected: it exists already in the only safe form — Kang doing the thing himself as `kang`).

### SEC-009 — Security failures degrade visibly and specifically

**Decision.** Every security-relevant failure (denial, quarantine, integrity freeze, budget halt, guard trip) produces: a typed event, an audit entry, a health-panel state, and — per the ladder — a notification. The UI renders degraded/denied states honestly (09_UI §13); nothing is dressed as success or hidden as silence.
**Why.** §1.7. Invisible security failures train false confidence; specific visible ones train correct mental models.
**Alternatives.** Quiet-by-default security (rejected: quiet is for *successes*).

### SEC-010 — Explanations are mandatory for authority

**Decision.** Any component exercising authority MUST be able to explain it from persisted data: which grant, which trigger, which manifest, which confirmation. `kang explain` covering any correlation id within 180 days is a CI-enforced requirement (05_AGENTS §14). An unexplainable action is treated as a security incident even if harmless.
**Why.** Explanation is the audit of *reasoning*, and reasoning is where injection and confusion live.

### SEC-011 — Secrets never leave the credential boundary

**Decision.** Raw secrets exist in exactly one place (OS keychain) and transit exactly one component (adapter-internal credential injection). They MUST NOT appear in: prompts, manifests, logs, memory, config files, `plugin_kv`, exports, backups, error messages, or the database. A scrubber provides defense-in-depth on all log/audit paths; scrubber hits are themselves incidents (something tried). Plugins never see raw credentials — RESERVED `credential:{name}` injection (08_PLUGIN §9.5).
**Why.** S7, unified. Secrets are the one data class where a single leak is unrecoverable by restore.
**Alternatives.** Encrypted secrets in config (rejected: the key management recursion lands in the keychain anyway — skip the middle step).

### SEC-012 — Recovery is a security requirement, tested

**Decision.** The security posture includes, as MUSTs: verified daily snapshots, monthly restore drills, 30-day deletion recovery, revision history on memory, tombstone coherence, and the documented full-restore protocol (07_DATABASE Part 12). A protection without a tested recovery path is classified as incomplete.
**Why.** §1.8. The question is never *whether* something will go wrong in ten years.

### SEC-013 — The audit log is evidence-grade within its honesty limits

**Decision.** Audit files are append-only JSONL, monthly-rotated, hash-chained per file (each record carries the previous record's hash; the chain head is included in the daily backup). This makes *modification tamper-evident* to any later inspection. Honesty limit, stated: an attacker with full machine control can rewrite everything including chains — the chain defends against casual/tooling/partial tampering and accidental edits, and that is all it claims (§2.2).
**Why.** Integrity-before-secrecy applied to the system's own history; cheap (a hash per record) relative to its forensic value.
**Alternatives.** External anchoring (timestamping services — rejected Phase 1: network dependency for marginal gain; RESERVED, trigger: sync era, where a second device becomes a natural witness).

---

## 5. Prompt Injection Defense (the complete model)

Injection is assumed **permanent, and eventually successful at influencing text**. The design goal is therefore *not* "no influence" but: **influenced text still cannot act** (05_AGENTS §15, elevated here to the governing statement).

The six independent layers — each sufficient to stop authority, all present:

1. **UNTRUSTED propagation (SEC-001).** Hostile content is data with a warning label, at ingress and through every derivation. Prompts render it inside explicit data framing; instruction hierarchy places it below everything (system > definition > Kang > data).
2. **Read/act separation.** Principals holding Tier-0-input tools (`web.fetch`, email read) hold no consequential scopes and no sensitive-memory reads — *linted at grant time* across each plugin's principal union (05_AGENTS §8; 08_PLUGIN PL-002). The agent that reads the hostile page is structurally unable to act on its instructions; the agent that can act never reads hostile pages.
3. **Tool gating.** Every tool call is scope-checked per-call against the invocation's grant snapshot; tools validate inputs as hostile regardless of caller (05_AGENTS §15).
4. **Out-of-band confirmation (SEC-003).** Consequences require the UI dialog. No token in any text channel — model output, tool result, memory content, plugin data — is a confirmation. Injected text can *ask*; only Kang's hand can *approve*, with the full what/who/why in front of him (09_UI §7).
5. **Memory write gate (M-003).** Injected content cannot persist itself: AI proposals queue for Kang, Tier-0 cannot promote itself, `rule`/`profile` are Kang-only. The long-game injection (poison memory now, harvest authority later) dies here.
6. **Detection.** Denial-spike quarantine (an influenced agent probing its boundaries gets benched, 05_AGENTS §8); citation requirements make injected "facts" traceable to their hostile source on inspection (§11-UI); scrubber hits and guard trips are audited.

`web.fetch` behavior (normative): allowlisted domains per grant; response size caps; content rendered as quoted data with source URL; no fetched content ever interpolated into system/definition prompt positions; redirects re-checked against the allowlist; fetched URLs audited.

**Why injection never grants authority:** authority requires a grant (SEC-004) + a live confirmation for consequences (SEC-003) + a principal (SEC-006). Text possesses none of these and cannot mint them (SEC-008, SEC-005). The layers make this a property of the architecture's *shape*, not of any filter's cleverness.

---

## 6. Permission Enforcement

Cross-reference: the model is D013 + 05_AGENTS §8; this section adds the constitutional consolidations. Principals (`kang`, `agent:*`, `plugin:*`, `rule:*`) · capability scopes with qualifiers · default-deny · `permissions.toml` as truth with `grant_` as loaded state (drift: file wins, reported) · per-call executor checks against per-invocation snapshots · pairing lints at load and install · denials: typed result, audited, never silent, never retried, spike ⇒ quarantine · wildcard scopes: `kang` only · grant mutation: Kang-only consequential action, visible in the System permission screen answering "what can KANG touch?" in under a minute.

---

## 7. Secret Management

- **Ownership:** every credential belongs to Kang; KANG is a custodian with exactly one vault (Windows Credential Manager / OS keychain) and one master key for sealed-box content (DB-005).
- **Rotation:** `kang rotate-key` (private-content master key, DB-005 protocol); provider API keys rotated by Kang in provider consoles + keychain update — KANG detects auth failures and prompts, it never stores fallback copies.
- **Access pattern:** adapters request credentials by *name* from the credential subsystem at call time; credentials live in memory only for the duration of the call; no caching in any KANG store.
- **Model behavior:** prompts are constructed from manifests + task content, neither of which can contain secrets by construction (SEC-011 storage prohibitions) + scrubber defense-in-depth.
- **Plugins:** no keychain door exists in the SDK (08_PLUGIN §8); RESERVED `credential:{name}` scope activates core-side injection when the first credentialed integration ships.
- **Logging:** scrubber on all log/audit/export paths; a scrubber hit = incident event (something attempted to write a secret) — investigated, not just redacted.
- **RESERVED:** external credential managers / hardware keys as keychain backends — trigger: real need; the credential subsystem is already the single seam.

---

## 8. Data Integrity

Cross-reference: 07_DATABASE Parts 12, 13, 15 are the mechanics. Constitutional additions:

- **The integrity chain:** schema constraints (first validator) → transactional writes → daily full `integrity_check` before snapshots → monthly restore drills → migration checksums → hash-chained audit (SEC-013) → derived-layer parity scans. Each link detects a different failure class; the chain is only as honest as its most recently *exercised* link — hence every link is scheduled, not aspirational.
- **Integrity incidents** are a permanent counter (07_DATABASE Part 17: resettable by no one) and a first-class event class: any detection (F1, F6, F7, F8, scrubber hit, chain break, provenance violation) creates one, with freeze/degrade behavior per SEC-007 and the failure tables of 07_DATABASE Part 15 / 06_MEMORY Part XIV.
- **Tamper evidence honesty:** checksums and chains prove *change*, not *innocence* — they cannot identify who, and they fall to full machine control (§2.2). Stated so that future-Kang never over-trusts them.

---

## 9. Plugin Security

Cross-reference: 08_PLUGIN §1.3 (constitutional rules), §3 (PL-001/002/009/010), §8–§9. Consolidated here as constitution: plugins are ordinary principals with extraordinary honesty — kernel doors only; no raw DB/filesystem/network; blessed imports with tamper-*evident* guards; grants at install with consequence lines and pairing lints across the plugin's principal union; supervised execution; quarantine on failure or denial spikes; zero-hard-dependency core (CI-proven); complete removal with export. **RESERVED:** sidecar isolation — the transport that turns the trust-basis from authorship into an OS boundary; trigger unchanged (first non-Kang plugin or non-blessed dependency need).

---

## 10. Model Security

Cross-reference: D010, 05_AGENTS §12, §15. Constitution: models are reached only through the Router (no SDKs in agent/plugin space); TaskSpec declares class/privacy — `private` routes local-or-fail-closed (06_MEMORY §12.1); budgets enforce at admission and per-call with the emergency reserve's two-purpose rule (AG-008); outputs are suggestions (SEC-002) validated by schema before machine consumption; hallucination containment = gate (persistence) + citations (claims) + attribution spot-checks (detection) + correction flow (learning from being wrong, 06_MEMORY XIV-7); provider isolation = adapters with minimum-necessary context and capability flags, so a provider compromise leaks at most what one call carried.

---

## 11. Human Authority

The constitution's apex, made explicit:

- **Kang is the root of all authority.** Every scope traces to a grant Kang made; every consequence traces to a confirmation Kang gave; every memory Tier-2 traces to Kang's word. There is no authority above, beside, or independent of him — no vendor override, no "safety" backdoor, no automatic anything that he cannot see, veto, or reverse.
- **Mechanisms:** unique unmimicable confirmation dialogs (09_UI §7) · approval queues where silence is veto (06_MEMORY §4.3) · one-screen permission management · the kill-switch (one command pauses all automation, D013) · reversibility everywhere it is physically possible (revisions, tombstones, 30-day recovery, restore) · total visibility (audit, explain, activity views with no edit affordances).
- **Why the human stays highest:** not sentiment — architecture. KANG's purpose is Kang's growth (Vision); a system that can overrule its principal has inverted its purpose. And practically: every failure mode in §2 is survivable *if* final authority sits with the one component that cannot be prompt-injected, budget-exhausted, or version-skewed. Kang is the trusted computing base.
- The corollary KANG accepts: **Kang can hurt himself** (bad grants, careless installs, ill-advised confirmations). KANG's duty is to make consequences visible *before* the click and recoverable after — never to seize the wheel (P6; anti-principle: never manipulate, even "for his own good").

---

## 12. Failure Modes (security posture per class)

| Class | Posture |
|---|---|
| Permission/grant uncertainty | **Fail closed** — unresolvable = denied (07_DATABASE F8) |
| Private-tier routing with no local model | **Fail closed** — never falls back to cloud (D010) |
| Integrity detection | **Freeze affected writes**, degrade to read-only as needed (SEC-007) |
| Model/provider outage | **Fail open into degradation** — deterministic paths, visible markers (A9; the secretary shows up) |
| Plugin failure | **Contain + quarantine**; core unaffected (PL-009) |
| Agent boundary-probing | **Quarantine** on denial spikes |
| Budget exhaustion | **Degrade by ladder**; reserve for deadlines only (AG-008) |
| Crash/power loss | WAL rollback; event-log replay of acknowledged Tier-1; report the window (07_DATABASE F2/F3) |
| Unexplainable action detected | **Incident** even if harmless (SEC-010); investigated before the code path re-enables |
| Everything else unknown | Default posture: **stop the write, keep the read, tell Kang** |

Recovery priority order (when multiple things are broken): 1) truth-store integrity → 2) deadline-critical function (deterministic plan + sweep) → 3) audit/attribution capability → 4) full cognitive function → 5) conveniences. Written down so triage at 2 a.m. is a lookup, not a judgment call.

---

## 13. Future Compatibility (justified reservations only)

| RESERVED | Seam already built | Trigger |
|---|---|---|
| Credential managers / hardware keys | Single credential subsystem (§7) | Real need |
| Sidecar plugin isolation | SDK doors + Plugin Protocol (PL-001) | First non-Kang plugin / non-blessed dep |
| Sync security (E2E encryption, peer auth, merged audit views) | Change-log + tombstones + device ids (D009); audit chain heads | 16_SYNC (v0.5) |
| Encrypted vault option (vault-at-rest beyond BitLocker) | Vault adapter boundary (M7 keeps vault plain-files; any encryption must preserve Obsidian usability — hard constraint) | Kang requests it with eyes open |
| External audit anchoring | Hash chains (SEC-013) | Sync era (second-device witness) |
| Remote execution | **Deliberately NOT reserved.** No seam is built for KANG executing off-machine; that would be a Vision-level change first. Recording the refusal is the reservation. | Vision amendment |

---

## Appendix — Security tables

**A. Trust levels (data)** — from 06_MEMORY §1.4: Tier 0 UNTRUSTED (external; cite, never assert) · Tier 1 OBSERVED (machine-verifiable) · Tier 2 SANCTIONED (Kang; sole source).

**B. Authority levels (actors)** — Kang: root, unlimited via UI, cannot be overruled · Core kernel: enforces, holds no discretionary authority · Agents/plugins: granted scopes only, attenuating, snapshot-frozen per invocation · Models: **zero** · External content: **zero, permanently**.

**C. Input classification at ingress** — Kang-typed (Tier 2 candidate) · KANG-observed (Tier 1) · vault content (Kang-authored: Tier 2 source; imported/clipped: Tier 0 until sanctioned) · web/email/API responses (Tier 0) · model output (untrusted computationally; trust derives only from its *cited* inputs) · plugin data (Tier 0 unless derived from higher-tier via kernel doors).

**D. Boundary → enforcement point** — Human→UI: confirmation dialogs · UI→Core: local API auth · Core→execution: Orchestrator admission · execution→capability: Permission Engine · capability→world: Tool Executor · anything→persistence: Memory Gate / domain services · anything→models: Router · plugins→everything: SDK doors.

**E. Recovery priorities** — §12 order: integrity → deadlines → attribution → cognition → convenience.

---

## Constitutional summary

KANG's security is the shape of its architecture, not a layer on top of it: few boundaries, all enforced; authority that is granted, attenuating, confirmed, and attributable; hostile text that can speak but never act; memory that cannot be written by anything that cannot be held to account; failures that announce themselves; and a recovery path from everything except dishonesty. The human is the root of trust and the point of the exercise.

*When code and this document disagree, one of them is wrong on purpose — file the ADR.*
