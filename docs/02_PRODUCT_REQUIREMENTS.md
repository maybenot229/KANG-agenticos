# KANG — Product Requirements

**Document:** 02_PRODUCT_REQUIREMENTS.md
**Version:** 0.2
**Author:** Kang, with Claude (Founding Architect)
**Status:** Living — this document evolves as capabilities are added
**Last updated:** 2026-07-11

---

## 1. Purpose

This document defines **what KANG must do**.

Unlike the Vision (`00_VISION.md`) and Principles (`01_PRINCIPLES.md`), this document is expected to evolve. New requirements will be added, priorities will shift, and versions will be re-scoped. What must not change: every requirement here must pass the Decision Framework in `01_PRINCIPLES.md §11`.

Requirements use stable IDs (`FR-###`, `NFR-###`) so that architecture documents, code, tests, and commits can reference them precisely. IDs are never reused, even after removal.

---

## 2. Product Philosophy

KANG is not a collection of AI features.

**It is an operating system for one human life.**

Every capability exists for one of three reasons:

1. It **reduces operational burden**, or
2. It **increases long-term capability**, or
3. It **compounds knowledge**.

Features do not exist independently. **Every feature should strengthen another feature.** A capture strengthens the vault. A completed project strengthens memory. A memory strengthens the next critique. A critique strengthens the next competition.

The consequence of this philosophy:

> **KANG should become more valuable every single day it is used.**

A feature that is merely useful in isolation — that connects to nothing and compounds into nothing — does not belong in KANG, no matter how impressive it is.

---

## 3. The Product Loop

Every great product has a core loop. This is KANG's heartbeat:

```
        ┌──────────────────────────────────────┐
        │                                      │
        ▼                                      │
    CAPTURE  ──►  ORGANIZE  ──►  PLAN          │
   (ideas,       (vault,        (quests,      │
    tasks,        projects,      schedule)     │
    finds)        memory)           │          │
                                    ▼          │
                                 EXECUTE       │
                                (build, study, │
                                 compete)      │
                                    │          │
                                    ▼          │
                                 REFLECT       │
                                (reviews,      │
                                 retrospectives)
                                    │          │
                                    ▼          │
                                  LEARN        │
                                (patterns,     │
                                 lessons)      │
                                    │          │
                                    ▼          │
                                 REMEMBER      │
                                (memory,       │
                                 knowledge)    │
                                    │          │
                                    ▼          │
                                 IMPROVE ──────┘
                                (better plans,
                                 sharper critiques,
                                 smarter surfacing)
```

**Capture → Organize → Plan → Execute → Reflect → Learn → Remember → Improve → Capture…**

Every capability in this document fits somewhere in this loop. When evaluating a feature, the first question is: **where does it sit in the loop, and what does it feed?** A feature that feeds nothing downstream breaks the loop — and the loop is the product.

---

## 4. Product Overview

KANG is an AI-native Personal Operating System that:

- **plans** — daily quests, schedules, priorities, long-term goals
- **remembers** — projects, deadlines, ideas, research, preferences, across years
- **researches** — papers, repositories, datasets, competitions, opportunities
- **critiques** — ideas, plans, reports, architectures, honestly and constructively
- **automates** — the operational work no human should waste attention on
- **teaches** — deep explanations, study plans, quizzes, spaced repetition

…for exactly one user.

It begins as a secretary, grows into a second brain, and becomes a lifelong thinking partner. It lives alongside existing tools (Obsidian, GitHub, VS Code, Chrome, Notion) and orchestrates them rather than replacing them.

---

## 5. Product Principles

How the product should *feel*. Distinct from the engineering principles in `01_PRINCIPLES.md` — these guide product decisions, not code.

- **The dashboard is home.** Every session starts there; every capability is reachable from there.
- **Memory compounds.** Day 500 must be meaningfully better than day 5, because of what KANG has learned.
- **Everything connects.** Notes link to projects, projects link to competitions, competitions link to lessons. No orphaned data.
- **Every feature saves time or builds capability.** Ideally both. Features that do neither get cut.
- **Every action is explainable.** "Why is this on my plan?" always has an answer (P5).
- **No dead ends.** Every workflow ends somewhere useful — a plan, a note, a memory, a next step. Never a shrug.
- **Calm by default.** KANG interrupts for what matters and is silent otherwise (U7).
- **Trust is the currency.** One fabricated memory or missed tracked deadline costs more than ten features earn.

---

## 6. Target User

### Primary user

**Kang.**

- High school student
- Developer (Python, VS Code, Claude Code, GitHub)
- AI competitor (competitions are the highest-priority domain)
- Researcher (physics, math, chemistry, AI, CV, ML, robotics)
- Creator (music production, video, writing)
- Christian (faith practices are part of daily life)
- Platform: Windows 11, Chrome, Obsidian, Notion

### Secondary users

**None.** Every design decision optimizes for the primary user without compromise.

### Future possibility

Other ambitious builders — students, researchers, indie hackers. This is explicitly *not* a current goal (see Non-Goals), but architecture should not make it impossible.

---

## 7. Goals

What KANG must be good at, in priority order:

1. **Daily planning** — the morning plan is the heartbeat of the product
2. **Deadline & competition management** — the highest-stakes secretary function
3. **Long-term memory** — the compounding asset
4. **Project management** — every project gets a tracked workspace
5. **Learning** — tutoring, study plans, spaced repetition
6. **Research** — papers, repos, datasets, synthesis
7. **Knowledge management** — Obsidian integration, linking, organization
8. **Automation** — monitors, schedulers, recurring workflows
9. **Faith support** — Bible study, prayer journal, scripture memory

---

## 8. Non-Goals

KANG is **not**, and will not become:

- ❌ A social network
- ❌ A team collaboration tool
- ❌ An enterprise SaaS product
- ❌ A general-purpose AI chatbot for the public
- ❌ A Windows replacement
- ❌ A CRM
- ❌ An email client (it may *read and draft* email via integration; it is not a mail app)
- ❌ A note-taking app (Obsidian is the note-taking app; KANG organizes it)
- ❌ A code editor (VS Code + Claude Code own that; KANG tracks the projects)

When a proposed feature drifts toward any of these, the answer is no.

---

## 9. Product Evolution

How KANG grows, in order. Each stage builds on — and requires — the previous one:

```
Secretary            (tracks, reminds, protects plans)
    ↓
Planner              (generates the day, defends the schedule)
    ↓
Organizer            (files, links, maintains the vault)
    ↓
Second Brain         (remembers and connects years of knowledge)
    ↓
Research Assistant   (finds, digests, synthesizes the world's knowledge)
    ↓
Growth Partner       (critiques, teaches, calibrates to how Kang works)
    ↓
Personal Operating System
                     (coordinates memory, agents, tools, workflows,
                      automation, and knowledge for one human life)
```

The stages are cumulative, not sequential replacements. The Personal OS at the end still does the secretary's job every morning — it has simply become far more on top of it.

**Rule:** never build stage N+1 features while stage N is unreliable. A brilliant research assistant that misses deadlines is a failed product.

---

## 10. Core Capabilities

### 10.1 Capability Tiers

Not all capabilities are equal. Tiers prevent scope creep and settle prioritization arguments:

| Tier | Capabilities | Rule |
|---|---|---|
| **Tier 1 — The Spine** | Planner, Memory, Projects, Dashboard, Chat, Automation core | Product fails without these. They get resources first, always. |
| **Tier 2 — The Specialists** | Competitions, Research, Learning, Second Brain | The differentiators. Built only on a working Tier 1. |
| **Tier 3 — The Enrichment** | Faith, Creative, Plugins & Settings | Valuable, but never at the expense of Tiers 1–2. |

A Tier 3 feature request never preempts a Tier 1 bug. Written here so it never has to be argued.

> [!note] No Business/monetization capability tier exists here **by design, not omission.** Per `docs/guides/user-profile-intake-2026-07.md` (Kang, 2026-07-19): *"no business yet — it's aspirational."* Not a scoping gap to fill; revisit only if that changes.

### 10.2 Capability Dependency Map

```
                    ┌─────────────┐
                    │   MEMORY    │  ◄── everything reads/writes memory
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  PROJECTS   │
                    └──────┬──────┘
                           │
   Research ──────┐        │
                  │        │
   Learning ──────┼──► ┌───▼─────┐      ┌────────────┐
                  │    │ PLANNER │ ◄────│ AUTOMATION │──► (monitors,
   Competitions ──┘    └───┬─────┘      └─────┬──────┘     schedules,
        │                  │                  │            feeds all)
        │                  │                  │
        │           ┌──────▼──────────────────▼─┐
        └──────────►│         DASHBOARD          │
                    │      (+ CHAT overlay)      │
                    └────────────────────────────┘

   Second Brain ◄──► Memory (bidirectional: vault ↔ memory reference each other)
   Faith, Creative ──► ride on Projects, Planner, Memory (no unique infrastructure)
```

Reading the map:

- **Memory is the root.** Nothing works without it. It is built first and held to the highest quality bar.
- **Projects sit on Memory; the Planner sits on Projects.** The daily plan is derived state — it aggregates projects, deadlines, learning, and competitions.
- **The specialists (Research, Learning, Competitions) feed the Planner and Projects** — they generate the work that planning organizes.
- **Automation drives everything on a clock;** the Dashboard displays everything.
- **Faith and Creative add no unique infrastructure** — they are workflows over existing capabilities. That is deliberate: it keeps Tier 3 cheap.

### 10.3 Capability Sections

Each capability uses the same template: **Purpose / Features / Inputs / Outputs / Dependencies / Success Means / Future Expansion.**

---

### 10.4 Daily Operating System (Planner) — Tier 1

**Purpose**
Generate and maintain the daily plan — the single most important recurring output of KANG.

**Features**
- Morning plan generation: Today's Quests, schedule, deadlines, priority tasks, estimated workload, recommended learning
- Plan adaptation during the day as things change
- Evening review: what got done, what carries over
- Weekly review: patterns, wins, adjustments

**Inputs**
Calendar events, active projects & tasks, deadlines, goals, learning plans, past completion patterns.

**Outputs**
Daily plan (dashboard + Obsidian daily note), carry-over updates, review summaries.

**Dependencies**
Memory, Projects, Calendar integration, Scheduler.

**Success means**
- The plan exists every morning without prompting.
- It is actually used daily — not regenerated, ignored, or manually redone.
- Priorities feel right ≥ 80% of mornings (Kang's own judgment).
- Planning overhead drops to near zero (< 2 min/day).

**Future Expansion**
Workload prediction calibrated on personal history; energy-aware scheduling; automatic replanning.

---

### 10.5 Memory — Tier 1

**Purpose**
The persistent, trusted store of everything that matters — the foundation every other capability reads from.

**Features**
- Structured memory: projects, competitions, deadlines, goals, preferences
- Semantic memory: ideas, notes, research (searchable by meaning)
- Explicit save/edit/delete controls; memory browser UI
- Context assembly: give any agent the right memories for its task
- Provenance: every memory knows its source, date, and reason for existing

**Inputs**
Explicit saves, capability outputs (project created, competition archived), importance rules.

**Outputs**
Retrieved context for agents, memory browser views, answers to "what do I know about X?"

**Dependencies**
Database, embedding/vector search, permission layer.

**Success means**
- **Zero fabricated memories.** If KANG says it remembers something, it exists in the store, verbatim traceable.
- Retrieval is trusted: Kang stops double-checking KANG's recall.
- Search is fast (< 1s for structured, < 3s for semantic).
- Nothing enters memory that Kang didn't sanction (explicitly or by rule).

**Future Expansion**
Pattern extraction across years ("you underestimate report time by 2x"); memory consolidation and decay policies.

---

### 10.6 Projects — Tier 1

**Purpose**
Every project becomes a tracked workspace: goals, tasks, milestones, files, notes, progress.

**Features**
- Project creation from an idea in seconds
- Task & milestone tracking with deadlines
- GitHub repo linking; commit-activity awareness
- Project-scoped notes linked to Obsidian
- Progress summaries; archive with retrospective on completion

**Inputs**
Kang's ideas, tasks, GitHub activity, notes, deadlines.

**Outputs**
Project dashboards, task lists feeding the daily plan, retrospectives feeding Memory.

**Dependencies**
Memory, GitHub integration, Obsidian integration.

**Success means**
- Every active project has exactly one home. No orphaned work.
- Progress is visible at a glance without asking.
- Retrospectives demonstrably improve later projects (patterns cited in future critiques).

**Future Expansion**
Effort estimation from history; automatic status detection from commits; documentation generation.

---

### 10.7 Competitions — Tier 2

**Purpose**
The highest-priority specialist domain: never miss an opportunity, and maximize performance in every competition entered.

**Features**
- Discovery: monitor competition sources for relevant opportunities
- Evaluation: fit, feasibility, effort estimate, risk, expected value
- Deadline tracking: registration, submission, judging — with lead-time alerts
- Preparation support: past winners research, judging criteria analysis, idea generation & critique, datasets, repos, papers
- Timeline & milestone generation per competition
- Deliverable support: reports, posters, presentations
- Judge simulation: adversarial Q&A practice
- Archive & reflection after each competition

**Inputs**
Competition sources (web), Kang's interests & skill profile, calendar, project capacity.

**Outputs**
Opportunity briefs, evaluations, timelines, deadline alerts, prep materials, post-competition retrospectives.

**Dependencies**
Research, Projects, Planner, Memory, Critic capability, web access.

**Success means**
- Zero missed deadlines for tracked competitions. Non-negotiable.
- Discovery surfaces ≥ 1 genuinely relevant opportunity per month that Kang didn't know about.
- Evaluations are honest — including "skip this one" recommendations.
- Each archived competition leaves lessons that appear in later prep.

**Future Expansion**
Win-pattern analysis across Kang's competition history; team-competition support.

---

### 10.8 Learning — Tier 2

**Purpose**
A world-class tutor for physics, mathematics, chemistry, AI, CV, ML, and programming.

**Features**
- Deep explanations with intuition-first teaching
- Study plan generation tied to goals and calendar
- Quizzes and comprehension checks
- Spaced repetition scheduling
- Learning mode vs. building mode distinction (per P1: teach vs. execute)

**Inputs**
Learning goals, curriculum/syllabus, past quiz results, study history.

**Outputs**
Study plans, lessons, quizzes, repetition schedules feeding the daily plan, progress reports.

**Dependencies**
Memory, Planner, AI models.

**Success means**
- Study plans are personalized and survive contact with the real calendar.
- Quiz history shows measurable improvement on repeated topics.
- Repetition reviews actually happen (they reach the daily plan and get done).
- Kang understands more, not just finishes more (per P1 — never automate away learning).

**Future Expansion**
Weakness detection from quiz history; automatic problem generation; exam simulation.

---

### 10.9 Research — Tier 2

**Purpose**
Find, digest, and connect external knowledge: papers, repos, datasets, documentation, technical blogs.

**Features**
- Multi-source search (arXiv, GitHub, datasets, docs, blogs)
- Summaries with uncertainty flagged and sources cited (per A3, P5)
- Comparison across sources; contradiction surfacing
- Research-gap and future-work identification
- Literature notes pushed to Obsidian

**Inputs**
Research questions, project context, interest profile.

**Outputs**
Research briefs, literature notes, dataset/repo shortlists, citation trails.

**Dependencies**
Web access, Memory, Obsidian integration.

**Success means**
- Every claim in a brief traces to a real, cited source. Zero invented citations.
- Uncertainty and contradictions are surfaced, not smoothed over.
- Time-to-understanding measurably beats manual searching.
- Literature notes land in the vault, linked, without manual filing.

**Future Expansion**
Standing research threads that accumulate over months; automatic relevance alerts for new papers.

---

### 10.10 Second Brain (Knowledge) — Tier 2

**Purpose**
Deep Obsidian integration: KANG organizes, links, and strengthens the vault without ever hijacking it.

**Features**
- Vault conventions: projects, research, ideas, daily notes, literature notes, permanent notes
- Automatic filing of KANG outputs into the right locations
- Link suggestion: connect related notes across the vault
- Knowledge graph awareness: answer "what do I know about X?"
- Zero-friction capture inbox → organized later by KANG

**Inputs**
Vault contents (read), KANG outputs, captures.

**Outputs**
Organized notes, link suggestions, knowledge answers, vault health reports.

**Dependencies**
Obsidian integration (filesystem-level), Memory, embedding search.

**Success means**
- Kang still trusts and enjoys the vault — KANG's organization helps, never clutters.
- Capture-to-filed happens without Kang's attention.
- "What do I know about X?" returns useful answers ≥ 80% of the time.
- The vault remains fully usable without KANG (plain Markdown, standard Obsidian — no lock-in, per P2).

**Future Expansion**
Permanent-note suggestions from accumulated literature notes; concept emergence detection.

---

### 10.11 Automation & Monitors — Tier 1 (core) / Tier 2 (monitors)

**Purpose**
The scheduled and reactive machinery: things KANG does without being asked.

**Features**
- Scheduler: morning plan, evening review, weekly review, repetition reminders
- Monitors: competition sources, deadline proximity, GitHub trending, AI news, scholarships
- Relevance filter: only surface what matches interests and goals (per U2)
- Full audit log of every automated action (per S5)

**Inputs**
Schedules, monitor configurations, interest profile.

**Outputs**
Triggered plans, alerts, digests — all filtered, all logged.

**Dependencies**
Scheduler infrastructure, web access, Memory, permission layer.

**Success means**
- Scheduled jobs fire reliably, including catch-up after downtime (NFR-008).
- Signal-to-noise stays high: Kang acts on most surfaced items rather than dismissing them.
- The audit log can explain any automated action, any time.
- Notification fatigue never sets in (see Risks, R3).

**Future Expansion**
User-defined workflows (if-this-then-that for life operations); plugin-provided monitors.

---

### 10.12 Dashboard (Mission Control) — Tier 1

**Purpose**
The primary interface. Answers: What should I do? What changed? What needs attention? What opportunities exist?

**Features**
- Today's Quests, calendar, deadlines (competition deadlines prominent)
- Goals & project status
- Research/news digest (filtered)
- Prayer/faith panel
- Quick capture + quick chat
- Windows 11-inspired, cyberpunk aesthetic, dark blue accent — legibility first (per U5)

**Inputs**
All capability outputs.

**Outputs**
The glanceable state of Kang's life; entry points to every capability.

**Dependencies**
Every other capability; UI framework.

**Success means**
- Opened every morning (≥ 6 days/week).
- The four questions are answerable in a single glance, < 10 seconds.
- It feels like home, not like a report.

**Future Expansion**
Customizable panels; focus mode; multi-monitor layouts.

---

### 10.13 Chat — Tier 1

**Purpose**
Conversational access to everything — one interface among several, not the product itself.

**Features**
- Context-aware conversation (knows active projects, today's plan, recent memory)
- Command palette-style quick actions
- Mode awareness: learning mode vs. building mode
- Honest-by-default persona (per P3): critiques, uncertainty, no flattery

**Inputs**
Kang's messages, assembled memory context.

**Outputs**
Answers, drafts, critiques, actions (with confirmation where required).

**Dependencies**
Memory, AI routing, all capabilities (as tools).

**Success means**
- Chat answers reflect real context (today's plan, active projects) without re-explaining.
- Uncertainty and sources appear in answers, unprompted.
- Kang gets pushback when ideas are weak — verifiably not a yes-man.

**Future Expansion**
Voice interface; multi-turn agent tasks launched from chat.

---

### 10.14 Faith — Tier 3

**Purpose**
Support Christian growth: study, prayer, memorization — never authority.

**Features**
- Bible reading plans & study support
- Prayer journal (private, local, encrypted)
- Sermon notes organization
- Scripture memorization with spaced repetition

**Inputs**
Reading plans, journal entries, sermon notes.

**Outputs**
Daily reading prompts, memorization reviews, organized notes.

**Dependencies**
Memory, Planner, Obsidian. Governed by anti-principle: never speak for God.

**Success means**
- The practices happen more consistently than before KANG.
- The prayer journal is verifiably private: local, encrypted, never in any AI context without explicit action.
- KANG supports practice and never positions itself as spiritual authority.

**Future Expansion**
Original-language study aids; church calendar integration.

---

### 10.15 Creative — Tier 3

**Purpose**
Support music production, video, presentations, posters, branding.

**Features**
- Project support for creative works (via Projects)
- Feedback and critique on creative output
- Presentation & poster assistance (heavily used by Competitions)

**Inputs**
Creative project context, drafts, references.

**Outputs**
Critiques, drafts, structure suggestions.

**Dependencies**
Projects, Critic capability.

**Success means**
- Creative projects get the same tracking rigor as technical ones.
- Critiques improve the work (Kang keeps coming back for them voluntarily).
- Competition deliverables (posters, decks) ship faster with KANG than without.

**Future Expansion**
Audio analysis for music production; Premiere Pro workflow support.

---

### 10.16 Plugins & Settings — Tier 3

**Purpose**
Extensibility and control: add capabilities without touching core; configure everything.

**Features**
- Plugin system: integrations, monitors, agents, UI panels as plugins (per AR2)
- Provider settings: AI model routing, API keys (in OS keychain, per S7)
- Permission management per agent/plugin (per S2)
- Memory browser & audit log viewer

**Inputs**
Configuration, plugin packages.

**Outputs**
Extended capabilities; system transparency.

**Dependencies**
Plugin SDK (`08_PLUGIN_SYSTEM.md`), permission layer.

**Success means**
- A new integration can be added as a plugin without touching core code.
- Every permission is visible and editable in one place.
- Kang can answer "what can KANG touch?" in under a minute.

**Future Expansion**
Community plugin ecosystem (only if multi-user future materializes).

---

## 11. Product States

KANG is always in a state. States drive scheduling, notification behavior, and UI emphasis.

| State | Meaning | Behavior |
|---|---|---|
| **Idle** | Kang isn't actively using KANG | Background monitors run; notifications batched unless urgent |
| **Planning** | Morning plan / replanning session | Dashboard leads with quests & deadlines; full attention mode |
| **Building** | Kang is executing (coding, creating) | Interruptions suppressed except critical deadlines; capture stays available |
| **Learning** | Study session active | Tutor persona; teach, don't do (P1); quizzes and explanations lead |
| **Researching** | Active research thread | Research tools lead; sources and briefs in focus |
| **Reviewing** | Evening/weekly review, retrospectives | Reflection prompts; completion data; carry-over decisions |
| **Monitoring** | Background (overlaps Idle) | Monitors and scheduler working; audit log accumulating |
| **Sleeping** | Quiet hours | No notifications, no exceptions; overnight jobs prepare the morning plan |

Rules:

- States are **suggested by KANG, controlled by Kang** (P6). KANG may infer "you seem to be building" — Kang confirms or overrides.
- Notification policy is a function of state. The same alert that interrupts during *Idle* waits during *Building* and never fires during *Sleeping*.
- States later map directly to scheduler and UI behavior in the architecture docs.

---

## 12. Data Ownership & Sources of Truth

**Kang owns everything.** Explicitly:

Projects · Tasks · Goals · Competitions · Research · Notes · Memory · Quiz & learning history · Settings · Conversation history · Audit logs · Plugins & their data

Ownership means: viewable, editable, deletable, exportable — at any time, in open formats (P2, NFR-009, FR-103).

**Source of truth per domain** (per M7, AR6 — exactly one authoritative home per piece of state):

| Data | Source of truth | Others hold |
|---|---|---|
| Notes & knowledge | **Obsidian vault** (Markdown files) | KANG holds an index + links, never the master copy |
| Structured state: projects, tasks, deadlines, goals, competitions | **KANG database** (SQLite) | Vault may embed references/views |
| Memory (semantic + structured) | **KANG database** | Agents receive copies as context, never write back directly |
| Calendar events | **Calendar provider** (Google Calendar) | KANG caches read-only; writes require confirmation |
| Code | **Git/GitHub** | KANG reads metadata only |
| Settings & permissions | **KANG config store** | — |
| Secrets (API keys) | **OS keychain** | Never in code, logs, DB, or memory (S7) |
| Audit log | **Append-only local log** | Never edited, even by Kang — integrity is the point |

**Conflict rule:** when two systems disagree, the source of truth wins, and KANG reports the discrepancy rather than silently "fixing" either side.

---

## 13. Functional Requirements

Priorities: **Critical** (product fails without it) / **High** / **Medium** / **Low**.
Version = first release where the requirement must be satisfied.

### Planner

| ID | Requirement | Priority | Version |
|---|---|---|---|
| FR-001 | KANG shall generate a daily plan (quests, schedule, deadlines, priorities) every morning without prompting | Critical | 0.1 |
| FR-002 | KANG shall allow tasks to be completed, deferred, or edited during the day | Critical | 0.1 |
| FR-003 | KANG shall generate an evening review summarizing completion and carry-overs | High | 0.2 |
| FR-004 | KANG shall generate a weekly review with patterns and adjustments | Medium | 0.3 |
| FR-005 | KANG shall estimate daily workload and warn on overcommitment | Medium | 0.4 |
| FR-006 | KANG shall detect commitments Kang has repeatedly deferred or avoided despite knowing about them, and surface them with escalating visibility, distinct from ordinary deadline tracking | High | 0.3+ |

### Memory

| ID | Requirement | Priority | Version |
|---|---|---|---|
| FR-010 | KANG shall persist projects, competitions, deadlines, goals, and preferences across sessions | Critical | 0.1 |
| FR-011 | KANG shall let Kang explicitly save, edit, and delete any memory | Critical | 0.1 |
| FR-012 | KANG shall store provenance (source, date, reason) with every memory | Critical | 0.1 |
| FR-013 | KANG shall retrieve memories by semantic similarity as well as structured query | High | 0.2 |
| FR-014 | KANG shall never store conversations as memory without explicit save or matching importance rule | Critical | 0.1 |
| FR-015 | KANG shall provide a memory browser UI | High | 0.2 |

### Projects

| ID | Requirement | Priority | Version |
|---|---|---|---|
| FR-020 | KANG shall create a project workspace (goals, tasks, milestones, notes) from a short description | Critical | 0.1 |
| FR-021 | KANG shall track tasks and milestones with deadlines feeding the daily plan | Critical | 0.1 |
| FR-022 | KANG shall link projects to GitHub repositories | High | 0.3 |
| FR-023 | KANG shall archive completed projects with a retrospective saved to memory | High | 0.2 |

### Competitions

| ID | Requirement | Priority | Version |
|---|---|---|---|
| FR-030 | KANG shall track competitions with registration, submission, and event deadlines | Critical | 0.1 |
| FR-031 | KANG shall alert on approaching deadlines with configurable lead times | Critical | 0.1 |
| FR-032 | KANG shall monitor configured sources for new relevant competitions | High | 0.2 |
| FR-033 | KANG shall evaluate a competition for fit, feasibility, effort, and risk | High | 0.2 |
| FR-034 | KANG shall generate a competition timeline with milestones | High | 0.2 |
| FR-035 | KANG shall research past winners and judging criteria on request | High | 0.3 |
| FR-036 | KANG shall generate and critique competition ideas | High | 0.3 |
| FR-037 | KANG shall simulate judges for presentation practice | Medium | 0.4 |
| FR-038 | KANG shall archive completed competitions with reflection saved to memory | High | 0.2 |

### Learning

| ID | Requirement | Priority | Version |
|---|---|---|---|
| FR-040 | KANG shall generate study plans tied to goals and calendar | High | 0.2 |
| FR-041 | KANG shall produce explanations, examples, and quizzes on demand | High | 0.2 |
| FR-042 | KANG shall schedule spaced repetition reviews into the daily plan | High | 0.3 |
| FR-043 | KANG shall track quiz results and learning progress in memory | Medium | 0.3 |

### Research

| ID | Requirement | Priority | Version |
|---|---|---|---|
| FR-050 | KANG shall search papers, repositories, and datasets from a single query | High | 0.2 |
| FR-051 | KANG shall produce research briefs with cited sources and flagged uncertainty | High | 0.2 |
| FR-052 | KANG shall write literature notes into the Obsidian vault | High | 0.3 |

### Second Brain

| ID | Requirement | Priority | Version |
|---|---|---|---|
| FR-060 | KANG shall read and write the Obsidian vault via the filesystem using defined conventions | Critical | 0.2 |
| FR-061 | KANG shall provide sub-5-second capture that files items into an inbox for later organization | High | 0.2 |
| FR-062 | KANG shall organize inbox items into vault conventions automatically (with review option) | High | 0.3 |
| FR-063 | KANG shall suggest links between related notes | Medium | 0.4 |
| FR-064 | KANG shall answer "what do I know about X?" from vault + memory | High | 0.3 |

### Automation

| ID | Requirement | Priority | Version |
|---|---|---|---|
| FR-070 | KANG shall run scheduled jobs (morning plan, reviews, monitors) reliably, including catch-up after downtime | Critical | 0.1 |
| FR-071 | KANG shall filter all proactive surfacing through a relevance model of Kang's interests | High | 0.2 |
| FR-072 | KANG shall log every automated action to an append-only, human-readable audit log | Critical | 0.1 |
| FR-073 | KANG shall require explicit confirmation for any consequential action (send, delete, publish, spend) | Critical | 0.1 |
| FR-074 | KANG shall respect product states (e.g., no non-critical interruptions during Building; silence during Sleeping) | High | 0.2 |

### Dashboard & Chat

| ID | Requirement | Priority | Version |
|---|---|---|---|
| FR-080 | KANG shall display a dashboard answering: what to do, what changed, what needs attention, what opportunities exist | Critical | 0.1 |
| FR-081 | KANG shall provide context-aware chat with access to memory and capabilities | Critical | 0.1 |
| FR-082 | KANG shall surface uncertainty and sources in chat answers | High | 0.1 |

### Faith

| ID | Requirement | Priority | Version |
|---|---|---|---|
| FR-090 | KANG shall support Bible reading plans with daily prompts | Medium | 0.3 |
| FR-091 | KANG shall provide a private, locally encrypted prayer journal | Medium | 0.3 |
| FR-092 | KANG shall schedule scripture memorization via spaced repetition | Medium | 0.3 |

### System

| ID | Requirement | Priority | Version |
|---|---|---|---|
| FR-100 | KANG shall support multiple AI providers behind a routing layer | Critical | 0.1 |
| FR-101 | KANG shall expose extension points for plugins (integrations, monitors, panels) | High | 0.4 |
| FR-102 | KANG shall enforce per-agent/per-plugin permissions | Critical | 0.2 |
| FR-103 | KANG shall provide full data export in open formats at any time | High | 0.2 |

> **Note:** This is the seed set (~46 requirements). It will grow toward 200–300 as architecture and agent documents mature. IDs are permanent; gaps in numbering are reserved per capability.

---

## 14. User Workflows & Story Matrix

### 14.1 User Story Matrix

The product at a glance — what Kang wants, what KANG does, and what success looks like:

| Kang wants to… | KANG does… | Success |
|---|---|---|
| Capture an idea mid-task | Hotkey → inbox item | < 5 seconds, focus unbroken |
| Start a project | Creates full workspace (goals, tasks, vault folder) | One action, one home |
| Know what to do today | Morning plan, generated overnight | < 2 min planning overhead |
| Never miss a deadline | Tracks + alerts with lead time | Zero misses, ever |
| Learn a topic | Personalized study plan + tutoring + repetition | Measurable understanding |
| Enter a competition | Evaluation → timeline → prep → judge sim | No missed deadlines, honest odds |
| Understand a research area | Multi-source brief, cited, uncertainty flagged | Faster than manual search |
| Find what he knows | "What do I know about X?" over vault + memory | Useful answer, ≥ 80% |
| Get honest feedback | Critique: strengths, weaknesses, risks, blind spots | Verifiably not a yes-man |
| Keep faith practices consistent | Reading prompts, journal, memorization | More consistent than before |

### 14.2 W1 — Morning Routine (the heartbeat)

```
Wake up
  ↓
Open dashboard (or it's already open)
  ↓
Today's Quests: 3–5 priorities, generated overnight
  ↓
Deadlines: anything within lead-time windows, competitions first
  ↓
Schedule: calendar + study blocks + repetition reviews
  ↓
(Optional) Faith panel: today's reading, memorization review
  ↓
Begin work — zero planning overhead spent
```

**Acceptance:** From wake to work-start, planning costs < 2 minutes of attention.

### 14.3 W2 — Idea Capture

```
Idea strikes (anywhere, mid-task)
  ↓
Quick capture (hotkey / quick chat) — under 5 seconds
  ↓
Item lands in inbox
  ↓
KANG organizes it later: idea note in vault, linked to related notes,
   surfaced if it matches an active project or competition
  ↓
Kang's focus was never broken
```

### 14.4 W3 — New Project

```
Idea → "make this a project"
  ↓
KANG creates workspace: goals, initial tasks, milestone skeleton, vault folder
  ↓
KANG researches: similar projects, repos, papers (on request)
  ↓
Tasks flow into daily plans
  ↓
Progress tracked; Critic reviews at milestones
  ↓
Completion → archive + retrospective → memory
```

### 14.5 W4 — Competition Lifecycle

```
Monitor finds competition (or Kang adds one)
  ↓
Evaluation brief: fit, feasibility, effort, risk, expected value
  ↓
Kang decides: enter / skip (KANG advises, Kang decides — P6)
  ↓
Registration deadline tracked immediately
  ↓
Timeline generated: milestones back-planned from submission
  ↓
Prep: winners research, criteria analysis, idea generation → Critic → refine
  ↓
Build phase: tasks in daily plans, progress tracked
  ↓
Deliverables: report, poster, presentation support
  ↓
Judge simulation before the real thing
  ↓
Submission → result → reflection → memory
       ("what worked, what didn't, what patterns emerged")
```

### 14.6 W5 — Learning Session

```
Learning goal exists (e.g., "master multivariable calculus by June")
  ↓
Study plan spread across calendar
  ↓
Daily plan includes today's study block
  ↓
Session: intuition-first teaching, examples, practice
  ↓
Quiz → results to memory
  ↓
Spaced repetition schedules future reviews automatically
```

### 14.7 W6 — Research Thread

```
Question arises (from project, competition, or curiosity)
  ↓
KANG searches: papers, repos, datasets, blogs
  ↓
Brief produced: synthesis, comparisons, contradictions, uncertainty flagged
  ↓
Literature notes → Obsidian, linked to related notes
  ↓
Thread stays open: new findings surface as they appear (future)
```

**Loop check:** every workflow above ends by feeding the Product Loop — a plan (W1), a note (W2), a memory (W3, W4), learning data (W5), or knowledge (W6). No dead ends.

---

## 15. Integrations

| Integration | Why | Data exchanged | Access | Priority | Version |
|---|---|---|---|---|---|
| **Obsidian** (filesystem) | The second brain substrate | Notes read/written per vault conventions | Read/Write | Critical | 0.2 |
| **Filesystem** | Projects, exports, documents | Files in designated KANG + vault directories | Read/Write (scoped) | Critical | 0.1 |
| **Claude API** | Primary intelligence provider | Prompts/completions; minimum necessary context | External call | Critical | 0.1 |
| **Other AI providers** (OpenAI, local LLMs) | Model-agnostic routing (A7) | Prompts/completions | External call | High | 0.2–0.5 |
| **GitHub** | Project ↔ code linkage; trending monitor | Repo metadata, commits, issues (read); no pushes in early versions | Read | High | 0.3 |
| **Google Calendar** | Schedule substrate for planning | Events read; event creation with confirmation | Read/Write (confirmed) | High | 0.2 |
| **Chrome** | Research and capture context | Via extension or Claude-in-Chrome; page content on request | Read (on request) | Medium | 0.5 |
| **Notion** | Existing workspace content | Pages read; writes with confirmation | Read/Write (confirmed) | Medium | 0.4 |
| **Email** | Deadline/opportunity extraction; drafts | Read configured folders; drafts only, never auto-send (P6) | Read/Draft | Medium | 0.5 |
| **Claude Code / VS Code** | Development workflow | Project context handoff | Read | Low | 0.6+ |

**Rules for all integrations:** least privilege (S2), audit-logged (S5), replaceable behind interfaces (AR4), external content treated as untrusted data (S6).

---

## 16. Non-Functional Requirements

| ID | Requirement | Notes |
|---|---|---|
| NFR-001 | Dashboard usable < 5s after launch | Cold start on typical Windows hardware |
| NFR-002 | Core loop (plan, tasks, memory, capture) works fully offline | AI-dependent features degrade gracefully (AR7) |
| NFR-003 | All personal data stored locally by default | Cloud only as encrypted opt-in (P8) |
| NFR-004 | Sensitive stores (prayer journal, credentials) encrypted at rest | Keys owned by Kang (S3) |
| NFR-005 | Every automated action auditable | Append-only human-readable log (S5) |
| NFR-006 | Full recovery from backup of the data directory | One directory = whole life; test restores |
| NFR-007 | Any provider/integration swappable without core changes | Interface boundaries (AR4, E6) |
| NFR-008 | System survives weeks of neglect | Catch-up gracefully; no cascading stale-state failures |
| NFR-009 | All data in open formats | Markdown, SQLite, JSON (P2) |
| NFR-010 | Windows-first; no architectural blockers to future cross-platform | Avoid Windows-only core dependencies |
| NFR-011 | Quick capture end-to-end < 5 seconds | Hotkey to saved (U4) |
| NFR-012 | AI provider outage never blocks non-AI functionality | Defined failure paths (A9) |

---

## 17. Success Metrics

Measured, not felt:

- **Daily use:** dashboard opened ≥ 6 days/week (measured by KANG itself)
- **Zero missed deadlines** that KANG knew about
- **Capture speed:** median < 5 seconds, hotkey to saved
- **Plan completion:** ≥ 60% of Today's Quests completed (calibration target, not a guilt metric)
- **Memory trust:** "what do I know about X?" answers rated useful by Kang ≥ 80% of the time
- **Research leverage:** research briefs reduce time-to-understanding vs. manual search (self-assessed per brief)
- **The offline test:** a week without KANG visibly hurts (Year 1 vision test)

---

## 18. Product Risks

Every mature PRD names its failure modes. Each risk has a mitigation and an owner-check (where in the docs it's guarded).

| ID | Risk | Consequence | Mitigation | Guarded by |
|---|---|---|---|---|
| R1 | **Over-automation** | Kang's skills atrophy; dependence grows | Learning vs. building mode; teach-first in learning contexts | P1, A-P "never automate away learning" |
| R2 | **Feature creep** | Tier 1 quality erodes under Tier 3 ambitions | Tiers, Decision Framework, Non-Goals | §10.1, `01_PRINCIPLES §11` |
| R3 | **Notification fatigue** | Kang starts ignoring KANG; trust dies quietly | Relevance filter, states, calm-by-default; measure dismissal rate | U2, U7, FR-071, FR-074 |
| R4 | **Poor memory quality** | Every downstream capability degrades | Provenance, no-fabrication rule, explicit controls, quality bar | P4, A4, FR-011..014 |
| R5 | **Vendor dependence** | A pricing/API change breaks KANG | Provider routing, model-agnostic core, open formats | A7, AR4, FR-100 |
| R6 | **Overengineering** | Grand architecture, nothing ships | Incremental development; v0.1 brutally small; ship-first rule | P9, Vision §9.3 |
| R7 | **Maintenance burden** | One part-time developer can't sustain it | Boring tech, simplicity, design-for-deletion, survives-neglect NFR | E1, E10, AR8, NFR-008 |
| R8 | **User dependency** | KANG replaces thinking instead of amplifying it | Anti-metrics in Vision; honest critique culture; human-in-control | Vision §8, P3, P6 |
| R9 | **Trust collapse** (one bad incident) | Fabricated memory / missed tracked deadline / unauthorized action destroys years of trust | Highest severity bug class; audit log; confirmation gates | P4, P6, S1, S5 |
| R10 | **Building KANG > using KANG** | The tool crowds out the growth it serves | Vision constraint §9.5; anti-metric; periodic honest review | Vision §8, §9 |

Risks are reviewed at every version boundary. A risk trending toward reality pauses feature work.

---

## 19. Future Features

Parked here so they don't distract current development:

- Voice mode (wake word, conversational operations)
- Mobile app / companion
- Vision (documents, whiteboards, screens)
- Wearable integration
- Local model inference for all sensitive processing
- Workflow builder (user-defined automations)
- Robotics interfaces
- Multi-device encrypted sync
- Team/multi-user support (only if the mission ever expands)
- Plugin marketplace

Each graduates from this list only through the Decision Framework.

---

## 20. Version Roadmap (summary)

Detailed roadmap lives in `03_ROADMAP.md`. Summary:

```
v0.1 — The Spine (secretary MVP)
    Chat • Memory (structured) • Dashboard • Projects & tasks
    Daily plan • Deadline tracking • Scheduler • Audit log
    → Success: used every morning for 2 weeks straight

v0.2 — The Second Brain seed
    Obsidian integration • Quick capture • Semantic memory
    Calendar integration • Competition tracking & evaluation
    Evening review • Memory browser • Product states

v0.3 — The Specialists
    Competition Agent (full) • Learning Agent • Research Agent
    Literature notes • Spaced repetition • GitHub linking

v0.4 — The Platform
    Plugin system • Permission manager UI • Relevance filtering v2
    Judge simulation • Link suggestions • Notion integration

v0.5+ — The Expansion
    Voice • Email integration • Chrome integration
    Local models • Sync • Workflow automation
```

---

*Previous: `01_PRINCIPLES.md` — how we decide.*
*Next: `03_ROADMAP.md` — when we build what, sprint by sprint.*
