# CLAIMS.md — Constitutional Claims Under Test

Registry mandated by 14_CLAUDE §7 / 03_ROADMAP §1.6: every suite starts from
a constitutional MUST and proves *that claim*. Updated in the same PR as any
claim-bearing test. One line per claim; the test proves it or the line lies.

| Claim (decision / MUST) | Proven by |
|---|---|
| 17 §4.2/§4.3 — imports point inward only; the named forbidden vectors are individually red | `suites/architecture/test_import_contracts.py` (green on real code + red-test: deliberate violation fails) |
| 17 §4.4 — a package without a contract entry is red by omission | `suites/architecture/test_import_contracts.py::test_every_src_package_has_a_contract_entry` |
| 17 §4.3.6 — no cross-adapter imports | import contract "adapter tech folders are independent" + independence-entry test |
| 17 §4.3.9 — production never imports tests/ or tools/ | `suites/architecture/test_import_contracts.py::test_no_production_import_of_tests_or_tools` |
| 11 §4 — size hard limits fail CI | `suites/architecture/test_architecture_lints.py` (green + planted-violation red-tests) |
| 11 §25 — print/SQL-outside-store/wall-clock/os.environ bans | `suites/architecture/test_architecture_lints.py` (per-pattern red-tests; os.environ config exemption proven) |
| PS-002 — zero runtime state, zero secrets in the repo | `suites/architecture/test_architecture_lints.py` (tree hygiene green + .db/secret red-tests) |
| 14 header — root CLAUDE.md is a generated copy, never hand-edited | `suites/architecture/test_architecture_lints.py::test_root_claude_md_is_generated_and_current` |
| 07 Part XIII.4 — a modified historical migration is startup-blocking | `integration/sqlite/test_migrations.py::test_modified_historical_migration_blocks_startup` |
| 07 Part XIII.1 — migrations are NNNN_description.sql, gapless, checksummed | `integration/sqlite/test_migrations.py` (discover + checksum tests) |
| DB-003 — no partial truth: a failed migration leaves nothing behind | `integration/sqlite/test_migrations.py::test_failed_migration_leaves_no_partial_truth` |
| D009 — sync quartet on every synchronizable row from migration 0001 | `integration/sqlite/test_task_store.py::test_task_table_carries_the_quartet_columns` + contract quartet test |
| 07 §5.6 — every write is change-captured (insert/update/delete), ordered by seq | `integration/sqlite/test_task_store.py` capture tests |
| 07 §5.1 — deletes tombstone | `integration/sqlite/test_task_store.py::test_delete_is_captured_and_tombstoned` |
| DB-001/DB-003 — optimistic revision checks; stale writes conflict, revisions bump | `fixtures/task_store_contract.py` (run against fake AND sqlite) |
| 13 §2.3 — fakes are contract-paired with real adapters | `unit/.../test_task_store_fake.py` + `integration/sqlite/test_task_store.py` share `TaskStoreContract` |
| 11 §14 — the clock is injected; domain stamps time only through it | `unit/kang/domain/tasks/test_task_service.py` (FakeClock determinism) |
| 12 §5 / D015 — one correlation id threads the execution context; logs are JSON lines | `unit/kang/kernel/runtime/test_structured_logging.py` |
| D003 / PS-002 — %KANG_HOME% resolves from environment; no silent default into the checkout | `unit/kang/adapters/config/test_env_config.py` |
| 12 §16 — the registry is machine-readable, deterministic, the contract's source of truth | `unit/kang/api/registry/test_registry.py` |
| SEC-013 — audit is append-only JSONL, monthly, hash-chained per file; tampering is evident | `fixtures/audit_log_contract.py` (fake + jsonl) + `integration/jsonl/test_audit_log.py` (bit-flip and deletion break the chain loudly — 13 §2.9) |
| SEC-006 — anonymous action is architecturally impossible; every entry carries principal + correlation id | `unit/kang/kernel/audit/test_service.py` |
| 15 §5.1/§5.2 — the envelope is a closed field list; the eventlog DDL is exact; nothing invalid enters the log | `fixtures/event_log_contract.py` (fake + sqlite) + `integration/eventlog/test_event_log.py` (DDL column-exact, indexes cited) |
| EB-003 / DB-001 — eventlog runs synchronous=FULL on its own connection; recovery-grade payloads are self-sufficient | `integration/eventlog/test_event_log.py::test_connection_runs_synchronous_full` + contract self-sufficiency rejection test |
| 15 §4 — pending → confirmed \| orphaned; orphans are never deleted | `fixtures/event_log_contract.py` state-machine tests |
| 07 Part XII — VACUUM INTO is the only backup method; integrity gate before snapshot; corruption detected loudly | `integration/sqlite/test_backup.py` |
| EB-003 — re-application is idempotent, keyed by entity id + revision | `suites/replay/test_crash_replay.py::test_recovery_is_idempotent_run_twice` + `suites/backup_restore/test_restore_drill.py::test_restore_replay_is_idempotent` |
| **C1 (18 §3 M1)** — kill between every M1 write-order step pair ⇒ reconciliation converges, zero partial truth (13 §2.5) | `suites/replay/test_crash_replay.py` (subprocess fault injection, all four kill points + clean run) |
| **C1 (18 §3 M1)** — snapshot → corrupt live → restore → field-equality → gap replay (13 §2.15) | `suites/backup_restore/test_restore_drill.py::test_the_c1_restore_drill` |
| EB-004 — the five-step write order is event-first; a lost state commit becomes a recoverable ghost, never a silent miss | `suites/replay/test_crash_replay.py` (real `EventBus.publish` killed at every boundary) |
| EB-004 §4 — the caged reconciliation pass: re-apply recovery-grade & confirm; confirm-or-orphan the rest; report the window | `unit/kang/kernel/bus/test_reconciliation.py` |
| EB-007 — per-subscriber cursors, FIFO by seq, retry ×5 → dead-letter, cursor advances past a poison event; consumers dedup on event_id | `unit/kang/kernel/bus/test_delivery.py` (incl. poison-event §16.4) |
| EB-007 — cursors are delivery truth, per-subscriber, monotonic, durable across reopen | `fixtures/delivery_store_contract.py` (fake + sqlite) + `integration/eventlog/test_delivery_store.py` |
| EB-011.1 — a declared event→job→event cycle is rejected and named (static lint) | `unit/kang/kernel/bus/test_cycle_defense.py` |
| EB-011.2 — a causation chain deeper than 16 must not publish further (runtime depth guard) | `unit/kang/kernel/bus/test_cycle_defense.py` |
| §6.3 — publishing an unregistered type is rejected; recovery_grade is the registry's not the publisher's; payload schema checked | `unit/kang/kernel/bus/test_event_registry.py` |
| §16.2 / EB-003 — every recovery-grade type's payload reconstructs its row on an empty store (registry-driven — a new type without the proof fails CI) | `suites/replay/test_payload_sufficiency.py` |
| **C2 (18 §3 M2)** — kill between every EB-004 step pair ⇒ the REAL reconciliation + delivery resume converge, zero partial truth, at-least-once + idempotent delivery (13 §2.5) | `suites/replay/test_crash_replay.py` |
