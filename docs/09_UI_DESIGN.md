# KANG — UI Architecture Specification

**Document:** 09_UI_DESIGN.md
**Version:** 0.1
**Author:** Kang, with Claude (Founding Architect)
**Status:** Normative — every screen, present and future, MUST conform; changes require an ADR
**Last updated:** 2026-07-11
**Upstream (binding):** `00_VISION.md`, `01_PRINCIPLES.md` (esp. U1–U7), `02_PRODUCT_REQUIREMENTS.md` (§10.12, §11), `04_ARCHITECTURE.md` (D002), `05_AGENTS.md` (§13), `06_MEMORY.md`, `07_DATABASE.md`, `08_PLUGIN_SYSTEM.md`
**Downstream:** `12_API.md` (the UI is a pure client of it), `03_ROADMAP.md`

> RFC-2119 language throughout. This is the architectural specification of the interface — screen responsibilities, hierarchy, contracts, and state behavior. It is implementation-independent: it binds any frontend built on any framework for the next decade. It contains no pixels.

---

## 1. UI Philosophy

### 1.1 What the UI is

The UI is **Mission Control for one human life**: a calm, glanceable, explainable surface over the KANG core. It is *not* the product — memory, agents, and automation are the product; the UI is the room they are visible in. Consequently:

- **UI-P1 — The UI is a pure client.** It speaks only the local API (D002). It holds no truth, computes no domain logic, and can be deleted and rebuilt without losing anything (AR8). Any behavior that would survive a UI rewrite belongs in the core; any that wouldn't belongs here. This single rule is what makes a decade of UI evolution safe.
- **UI-P2 — Calm is the default (U7).** The interface's resting state is quiet. Motion, color, and interruption are *spent*, not decorated with. An urgent-looking element for a non-urgent fact is a lie (P3).
- **UI-P3 — Glanceable first, deep on demand (U3).** Every surface answers its question in seconds; every detail is one deliberate step away, never forced into view.
- **UI-P4 — Explainable everywhere (P5).** Any fact, plan item, alert, or suggestion on screen MUST offer a path to *why* (§11). No dead-end assertions.
- **UI-P5 — Deterministic.** The same core state MUST render the same interface. No engagement mechanics, no algorithmic reshuffling of surfaces, no A/B behavior. Kang's muscle memory is an asset the UI protects.
- **UI-P6 — Keyboard-first, mouse-complete (U6).** Every operation reachable by keyboard; every operation also completable by pointer. Neither modality is second-class.
- **UI-P7 — Attention is the budget (U2).** Every element on screen serves one of the four dashboard questions (§4) or an active task. Decoration that serves neither is removed.

### 1.2 What the UI is NOT

Not a chat app with widgets (chat is one surface among several); not a dashboard of vanity metrics; not a notification firehose; not a place where plugins draw whatever they want (08_PLUGIN §6: data-only panels); not a second implementation of business rules.

---

## 2. Navigation Model

### Decision UI-001 — Hub-and-spoke with a global palette; no deep hierarchies

**Decision.** Navigation is a **hub (Dashboard) + seven spokes (domains) + one omnipresent palette (§10)**. Domains: **Plan · Projects · Competitions · Learn · Know (memory+vault) · System (health/audit/permissions/plugins) · Chat**. Maximum navigation depth anywhere: **3** (domain → entity → detail pane). Anything that seems to need depth 4 is a sign the information belongs in a detail pane, a palette action, or nowhere.

**Why.** A decade of accreted screens kills tools through navigational sprawl. A fixed, shallow topology keeps the mental map stable (UI-P5) and makes every location reachable in ≤ 2 keystrokes via the palette. Seven domains map 1:1 onto the capability tiers (PRD §10) — the navigation *is* the product structure, so it evolves only when the product structure does (ADR-gated).

**Alternatives.** Free-form workspace/tabs (rejected: unstable mental map); sidebar tree navigation (rejected: trees grow; growth is the disease); chat-as-navigation (rejected: conversational navigation is slow, non-glanceable, and non-deterministic).

**Rules.** Every screen MUST declare its domain + depth. Back MUST always return exactly one level. Deep links (`kang://domain/entity/detail`) MUST exist for every location (used by notifications, `kang explain`, and cross-references).

---

## 3. Global Layout

Persistent chrome, identical on every screen:

| Region | Contents | Rules |
|---|---|---|
| **Top bar** | Current domain + breadcrumb (≤3) · global search/palette affordance · product-state indicator (§14) · attention beacon (§9) | MUST never contain actions that change data |
| **Left rail** | The seven domains + quick capture | Fixed order; MUST NOT reorder or hide items contextually (UI-P5) |
| **Content area** | The screen | Single-purpose; split view allowed only as list+detail |
| **Status strip (bottom)** | Background tasks (§14) · sync status (RESERVED, trigger: 16_SYNC) · budget pulse (spend vs. cap, silent) | Informational only; MUST NOT notify |

- **Quick capture** MUST be reachable from every screen and from outside the app (global hotkey) and MUST complete in < 5 s end-to-end (NFR-011): invoke → type → enter → gone. It MUST NOT open the main window if invoked globally; it is an overlay, and focus returns to whatever Kang was doing (W2: focus unbroken).
- Modal dialogs are permitted for exactly two things: **consequential confirmations (§7)** and **destructive-action warnings**. Everything else is non-modal. A modal that is neither is a defect.

---

## 4. Dashboard Architecture

The Dashboard is the hub and the home. It MUST answer, in one glance, in this order (U1):

1. **What should I do?** — Today's Quests (3–5, from the Planner), current time block.
2. **What needs attention?** — deadline horizon (competitions first), approval queue count, health alerts.
3. **What changed?** — since last visit: completed/new items digest, overnight agent activity summary (one line + link to §12).
4. **What opportunities exist?** — filtered digest (competitions found, relevant findings), batched.

Contracts:

- The four questions are four fixed zones. Zones MUST keep stable positions (UI-P5). Within zones, content is data-driven; the zones themselves are constitutional.
- Zone 1 is largest and first in focus order. If the Planner ran in degraded mode, the plan MUST carry a visible "degraded" marker with a why-link (A9, 05_AGENTS §10).
- The Dashboard MUST render meaningfully with zero model availability and zero network (NFR-002): P0 data (tasks, deadlines, calendar cache) is always present.
- The faith panel (PRD §10.14) is a Zone-1-adjacent optional card, shown per config; its content previews nothing marked private without an explicit unlock action (06_MEMORY §12.1).
- Plugin cards appear only in the designated plugin region (§8), never inside the four zones.
- Empty states MUST be honest and quiet: "No deadlines in the next 14 days." — never motivational filler, never suggestions to "explore features" (anti-engagement, 05_AGENTS §13).

---

## 5. Agent Interaction Surfaces

Three surfaces, strictly distinguished:

1. **Chat (domain).** Conversational access to everything (PRD §10.13). Contracts: the current context (today's plan, active entity) is visible as removable chips — Kang always sees what KANG sees; memory-derived claims render with citation affordances (§11); uncertainty markers (`A3`) are rendered distinctly, never buried in prose; streaming output MUST be cancellable at any moment (AG-007); consequential proposals inside chat MUST break out into the §7 dialog — chat text itself can never confirm anything (05_AGENTS §15: out-of-band approvals).
2. **Task cards.** Async agent work (user-initiated async, pipelines) renders as cards in the status strip + a Tasks view: name, phase, elapsed, cancel affordance, outcome badge (`ok | degraded | failed | denied | cancelled` — the invocation outcomes, 07_DATABASE). A finished card links to its `kang explain` view (§11). Cards MUST NOT toast on success (silence is the default, §9).
3. **Inline agent output.** Where agent products belong to an entity (evaluation brief on a competition, critique on a project), they render *in that entity's detail*, attributed ("Competition Strategist · yesterday 02:01 · why?"), never as disembodied chat bubbles.

Agents MUST NOT have avatars, personalities-as-decoration, typing indicators for non-streaming work, or simulated human latency. They are instruments, not characters (honest-by-default extends to presentation).

---

## 6. Memory Review Interface (the Memory Browser)

Lives in **Know**. This is the UI half of the four covenants (06_MEMORY §1.5) — ownership is only real if the interface makes it effortless.

- **Browse:** filterable by type, status, tier, sensitivity, date, provenance kind (06_MEMORY Part X modes: default/deep/structured). Superseded and archived records are reachable (deep mode) and visibly badged.
- **Record view:** content · type · tier · confidence · full provenance (source, reason, creator, dates) · revision history · links (typed, navigable) · access stats. Every field of the six provenance questions (06_MEMORY §8.1) MUST be visible without extra clicks.
- **Actions:** edit (creates revision), pin, archive, restore, delete (the confirmation states both the 30-day single-record recovery window and the snapshot-retention persistence of deleted content, 06_MEMORY §7.2), "never propose this again."
- **Approval queue:** a dedicated tab, surfaced by count on the Dashboard (Zone 2) — never by interrupting notification (06_MEMORY §4.3). Each item MUST show: content, type, source, reason, confidence, and dup/conflict context side-by-side, with single-keystroke approve / edit-approve / reject.
- **Contested view:** records `under_review` with their contradictions displayed as pairs, resolution actions per the protocol (06_MEMORY §6.2.4).
- **The search here is Kang-facing search** (06_MEMORY Part X): zero-hit results say "nothing in memory matches" — the UI MUST NOT pad results (P3 applies to interfaces).

---

## 7. Permission & Confirmation Dialogs

The most safety-critical UI. Constitutional rules:

- **One action, one dialog.** Consequential actions (05_AGENTS Appendix D) get a per-action modal showing: *what* will happen (exact content — the event to be created, the note to be deleted), *who* asked (principal + correlation id), *why* (agent's stated reasoning, one paragraph max), and the reversibility statement. No batching, no "approve all," no remember-my-choice (S1).
- **Confirmations are visually unique.** The confirmation dialog style MUST NOT be reused by any other dialog, so it can never be reflex-clicked from habit. Its confirm control MUST NOT be the default-focused element (no Enter-through).
- **Denial is one keystroke** and never asks why.
- **Permission management (System domain):** every grant per principal, in the same scope language as `permissions.toml`, with plain-language consequence lines (08_PLUGIN Appendix B style); grant changes are themselves consequential actions. The screen MUST answer "what can KANG touch?" in under a minute (PRD §10.16 success criterion).
- **Plugin install** renders the normative approval screen of 08_PLUGIN Appendix B verbatim in structure.
- Held actions (awaiting_confirmation state, 05_AGENTS Appendix B) appear in Zone 2 with age; they expire visibly (24h), never silently.

---

## 8. Plugin Panels & Placement

- Plugins render **only** through the fixed card vocabulary (metric · list · text · chart) in **designated slots**: `dashboard.sidebar`, `domain.{name}.sidebar`, and a `Plugins` section of System (08_PLUGIN §6). Slots are finite; the manifest declares, Kang places and orders (placement is Kang's, not the plugin's).
- Plugin cards MUST be visibly attributed (`plugin.{id}`), MUST render a quarantined/stale state when their provider fails (never blank, never cached-as-fresh: staleness is shown with age), and MUST NOT emit sounds, toasts, or modals — their notification path is the granted `notify` scope through the core ladder (§9), like everyone else.
- A plugin card's actions are limited to: refresh, open its detail view (a core-rendered page of the same vocabulary), configure (its config section), disable. **RESERVED:** custom-rendered plugin surfaces — trigger: Phase-2 sandbox ADR (08_PLUGIN §11).

---

## 9. Notification System

The UI face of the interruption ladder (05_AGENTS §13). Bindings:

| Priority | UI behavior |
|---|---|
| `critical` | OS notification + attention beacon (top bar) that persists until acknowledged. The only priority allowed to interrupt Building; never fires in Sleeping — it *queues at the wake boundary* except for data-integrity incidents, which may break Sleeping (R9 territory) |
| `attention` | Attention beacon + Zone 2 entry; OS notification only in Idle/Planning/Reviewing (FR-074) |
| `digest` | Batched into Dashboard Zone 3/4 and the morning plan; never an OS notification |
| `silent` | Health panel / logs only |

Rules: the beacon is a single indicator with a count — never a badge-per-feature carnival; clicking it opens a unified attention list (each item deep-links); re-notification of an unchanged item within 24h is forbidden (core-enforced, UI MUST NOT synthesize its own repeats); **the UI MUST NOT create notifications of its own** — every notification originates from a core `notification.requested` event with a principal, or it doesn't exist (auditability).

---

## 10. Search & Command Palette

### Decision UI-002 — One palette, three registers

**Decision.** A single global palette (default hotkey, open from anywhere) with three registers resolved by prefix-free intent parsing: **navigate** ("competitions", entity names → deep links), **act** (registered commands: "complete task…", "new project…", "capture…" — each command maps 1:1 to an API operation and respects all gates), **find** (full search: the Kang-facing hybrid search across memory, vault, entities — 06_MEMORY Part X). Results are grouped by register, deterministically ordered.

**Why.** The palette is the keyboard-first covenant (UI-P6) made real: every location ≤ 2 keystrokes, every common action ≤ a few more. One surface, because three separate pickers is three hotkeys of cognitive tax.

**Rules.** Commands MUST be the same operations the API exposes — the palette invents no verbs; consequential commands still raise the §7 dialog; palette usage MUST work identically with zero network/models (navigate + act are P0-local; find degrades to FTS per 07_DATABASE F6 behavior).

---

## 11. Explainability Views — "Why?"

The UI contract for P5. Every one of the following MUST carry a why-affordance, and the affordance MUST resolve without leaving the app:

| Element | "Why?" resolves to |
|---|---|
| A plan item | Planner reasoning: source (deadline/goal/carry-over/repetition) + the lesson/preference records that shaped placement (manifest-backed) |
| An alert/notification | The originating event + principal + rule |
| A memory-derived claim (chat or brief) | The cited record(s): `[MEM:id]` → record view (§6) |
| An agent output | The full `kang explain` view: trigger → context manifest (ids, scores, truncations) → model/tool calls → outcome (05_AGENTS §14 reconstruction, rendered) |
| A surfaced opportunity | The monitor, the source URL (UNTRUSTED-marked), and the relevance-filter reasoning |
| A degraded banner | Which fallback fired, what was unavailable, what is missing from the output |

Rendering rules: the first level of "why" is one sentence in place (popover); the second level is the full view. Score internals (the §5.2 term breakdown) are available at the second level — hidden by default, never unavailable. If an explanation cannot be constructed from persisted data, the UI MUST say "explanation unavailable — this is a bug" and link to a pre-filled issue note; it MUST NOT fabricate a narrative (A4 applies to interfaces).

---

## 12. Audit & History Views (System domain)

- **Activity:** the human-readable audit stream (S5): time · principal · action · one-line reasoning · correlation link. Filterable by principal, action class, date. This view reads the append-only log; it MUST offer no edit or delete affordances whatsoever — not grayed-out, *absent* (the UI teaches the integrity model by its shape).
- **Invocations:** the agent run history (`invocation` table): outcome badges, durations, costs; each row opens `kang explain`.
- **Ledger:** model spend vs. budgets (D010): burn-down by task class, per-agent and per-plugin attribution, reserve status. Quiet numbers; alerts ride the normal ladder at threshold crossings (AG-008).
- **Health:** the metrics surface (D015 + 07_DATABASE Part 17): job statuses, backup age + last restore-verification result, index parity, integrity-incident counter (permanently visible, resettable by no one — the UI honors that clause literally).

---

## 13. Error Presentation

- Errors are **typed, honest, and actionable**: what failed · why (one sentence) · what KANG did about it (degradation taken) · what Kang can do. Never raw stack traces in primary UI (available behind a "details" disclosure); never blame-the-user phrasing; never "something went wrong" without a correlation id.
- **Degraded ≠ failed.** Degraded outputs render *with their content* plus the marker (§11); failures render the failure. The UI MUST NOT dress a failure as an empty success (DB-P7's spirit: nothing silently corrupts, including impressions).
- Permission denials to *Kang's own* palette commands display the constraint and where to change it (§7 permission screen) — one sentence, no lecture (05_AGENTS §13 refusal behavior).
- Error states MUST be dismissible and MUST recur only if the condition recurs.

---

## 14. Loading & Background Behavior

- **Product-state indicator** (top bar): the current state (PRD §11: Idle/Planning/Building/…) with a one-click override menu — KANG suggests, Kang controls (P6). State changes MUST never occur silently while the window is focused.
- **Loading:** P0 content renders immediately (it is local SQL); model-dependent content streams into place with skeletons that state *what* is loading ("critique generating…"). Skeletons MUST NOT shift settled content (no layout jank — calm includes visual calm). Anything > 3 s becomes a task card (§5.2) instead of an in-place spinner.
- **Background tasks:** visible in the status strip; count + oldest-age; clicking opens Tasks. The UI MUST make overnight autonomy *legible after the fact* (Zone 3 digest + Activity view), not noisy during.
- The UI MUST remain responsive during any core batch job (nightly maintenance never janks the frontend — they're separate processes talking over the API by construction, D002).

---

## 15. Accessibility

- Full keyboard operability (UI-P6) with visible focus states; logical focus order per the zone hierarchy (§4).
- All meaning conveyed by color MUST have a non-color channel (icon, text, position) — the cyberpunk palette is decoration, never semantics' only carrier (U5).
- Contrast: body text MUST meet WCAG 2.1 AA against all theme backgrounds; the theme system (§17) enforces this at token level, not per-screen goodwill.
- Reduced-motion setting MUST disable all non-essential animation globally.
- Screen-reader labeling on all interactive elements and live-region announcements for beacon changes. (One user today — but Kang at 2 a.m., exhausted, using the keyboard only, *is* an accessibility user; and NFR-010's spirit applies: no architectural blockers to broader needs.)
- Text scale MUST be adjustable globally without layout breakage (test at 130%).

---

## 16. Responsive Behavior

- Primary target: desktop, 1280px-width minimum, multi-monitor friendly (the dashboard MAY occupy a secondary display full-time — an explicitly supported mode).
- Layout adapts by **density, not by hiding**: below width thresholds, sidebars collapse to rails and zones stack in the fixed order 1→2→3→4. Content MUST NOT disappear responsively — reachability is constant, prominence adapts.
- **RESERVED:** mobile/companion layouts — trigger: mobile client (Ten-Year Dream / 16_SYNC era). The zone model and deep-link scheme are already the mobile information architecture; nothing here needs undoing.

---

## 17. Theme System

### Decision UI-003 — Token-based theming; two first-party themes; identity in the accent

**Decision.** All visual properties flow from a semantic token set (`color.surface`, `color.attention`, `color.critical`, `type.scale`, `space.unit`, `motion.duration` …). Screens MUST consume tokens, never literals. First-party themes: **KANG Dark** (default: the cyberpunk, dark-blue-accent identity — PRD §10.12) and **KANG Quiet** (reduced-chroma variant). Both MUST pass §15 contrast at the token level. `critical`/`attention` colors are *reserved tokens*: nothing else on screen may use them (an alert color used decoratively is a cried wolf).

**Why.** Tokens are what let the aesthetic evolve for ten years without screen-by-screen repainting, and what make the legibility-first rule (U5) enforceable by lint instead of vigilance.

**RESERVED:** user-defined themes (trigger: token schema stability, post-v1); per-plugin theming — never (plugins inherit tokens, full stop; PL-008's spirit).

---

## 18. Future UI Extension Points (all RESERVED)

| Extension | Trigger |
|---|---|
| Voice surface (push-to-talk overlay; same commands as the palette — voice is a palette input method, not a new UI) | Voice feature ADR (v0.5+) |
| Mobile companion (zones 1–2 read-mostly + capture) | 16_SYNC ships |
| Focus mode (single-quest full-screen) | Post-v0.2 demand |
| Customizable dashboard layouts (zone order stays constitutional; card arrangement within zones becomes user-arrangeable) | v0.4+ |
| Sync status surfaces | 16_SYNC |
| Plugin custom rendering | Phase-2 sandbox ADR |

---

## 19. Constitutional Rules (every future screen, forever)

1. Serves one of the four questions or an active task, or it doesn't ship (UI-P7).
2. Pure API client — no truth, no domain logic, no local persistence beyond view preferences (UI-P1).
3. Depth ≤ 3; reachable by palette; deep-linkable (UI-001).
4. Deterministic rendering of identical state (UI-P5).
5. Every assertion carries a why-path (§11); every agent product is attributed.
6. Consequential actions use the unique confirmation dialog; nothing else may imitate it (§7).
7. Notifications originate in the core, ride the ladder, and never repeat unchanged within 24h (§9).
8. Degrades visibly and usefully offline/model-less; P0 always renders (§4, §14).
9. Honest empty/error/degraded states; no fabricated explanations, no padded results, no motivational filler (P3).
10. Tokens only; reserved colors reserved (UI-003). Keyboard-complete; AA contrast; reduced-motion respected (§15).
11. Plugins render in slots, attributed, through the card vocabulary — never elsewhere, never otherwise (§8).
12. No engagement mechanics: no streaks, no guilt, no celebration inflation, no asking questions to seem helpful (anti-principles; 05_AGENTS §13). A quiet day looks quiet.

*When a screen and this document disagree, one of them is wrong on purpose — file the ADR.*
