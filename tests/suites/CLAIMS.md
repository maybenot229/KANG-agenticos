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
