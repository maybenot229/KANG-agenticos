# ADR Index — Decision Book

Registry mandated by `docs/INDEX.md` §6.4 and 17_PROJECT_STRUCTURE §12.
Each entry: ID → status (active / superseded-by-NNN) → affected documents.
Append-only; an ADR that reverses or narrows another MUST cite it.

| ADR | Title | Status | Affected documents |
|---|---|---|---|
| [001](001-held-action-crash-semantics.md) | Held-action lifecycle and crash-semantics | accepted (w/ amendment) | 05_AGENTS §6/App. B/App. D, 12_API §7, 07_DATABASE §5.5 |
| [002](002-approval-channel.md) | The approval channel: first-party confirmation enforcement | accepted (w/ amendment) | 12_API §7/API-003/API-006, 05_AGENTS §8/App. D, 10_SECURITY §5.4/SEC-003/SEC-004 |
| [003](003-goal-horizon-5yr.md) | goal.horizon does not gain a '5yr' enum value | accepted | 07_DATABASE §1.4/§5.2 (no schema change — deliberate) |
| [004](004-m5-event-types.md) | Register the M5 event types: deadline lifecycle, notification, plan | accepted | 15_EVENT_BUS §6.1/§6.3, 05_AGENTS App. F, 13_TESTING §16 |
| [005](005-notification-queue-schema.md) | The notification queue schema | accepted | 07_DATABASE §5.2, 09_UI §9, 12_API §13 |
| [006](006-cron-schedules-and-job-invocation.md) | Wall-clock (cron) schedules, and how a job invokes an operation | accepted (w/ amendment) | 04_ARCH D014, 07_DATABASE §5.5, 12_API §14, 05_AGENTS App. E, 17 §2 |
| [007](007-ui-shell-decision.md) | UI shell: Tauri is committed for v0.1 | accepted | 04_ARCH §20.2, 18_IMPLEMENTATION_MASTER_PLAN §8.5/§10/I6 |
| [008](008-single-instance-enforcement.md) | Single-instance enforcement at the KANG shell | proposed | 04_ARCH D016, 17_PROJECT_STRUCTURE (`ui/shell/`), 07_DATABASE DB-001, 03_ROADMAP §8 |
| [009](009-http-transport-and-schema-authority.md) | HTTP transport ratified as stdlib `http.server`; Pydantic adopted for operation schemas | accepted | 04_ARCH D002, 12_API §2/§16, 17_PROJECT_STRUCTURE §4.2, 03_ROADMAP §8 |
| [010](010-pydantic-schema-implementation.md) | Pydantic schema implementation: layout, attachment, null-schema contract, validation-error mapping | accepted | 12_API §2/§16, 17_PROJECT_STRUCTURE (`api/schemas/`), `src/kang/api/registry/__init__.py`, `src/kang/api/dispatch.py` |
| [011](011-ts-client-generator.md) | Registry→TypeScript client generator: json-schema-to-typescript | proposed | 03_ROADMAP §8, 17_PROJECT_STRUCTURE §2, 18_IMPLEMENTATION_MASTER_PLAN §3 M6 |
| [012](012-ui-interaction-test-harness.md) | UI-interaction test harness: Vitest + React Testing Library | accepted | 13_TESTING §2.6, 17_PROJECT_STRUCTURE (no new top-level dir), 18_IMPLEMENTATION_MASTER_PLAN §3 M6 |
| [013](013-project-created-event.md) | Register `project.created`: the Projects domain's first write path | accepted | 15_EVENT_BUS §6.1/§6.3, 07_DATABASE §5.6, 13_TESTING §16.2 |
| [014](014-competition-created-event.md) | Register `competition.created`: the Competitions domain's first write path | accepted | 15_EVENT_BUS §6.1/§6.3, 07_DATABASE §5.6, 13_TESTING §16.2 |
| [015](015-milestone-created-event.md) | Register `milestone.created`: the Milestones sub-domain's first write path | proposed | 15_EVENT_BUS §6.1/§6.3, 07_DATABASE §5.6, 13_TESTING §16.2 |
