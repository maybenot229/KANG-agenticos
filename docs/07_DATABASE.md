# KANG — Database Specification

**Document:** 07_DATABASE.md
**Version:** 0.1
**Author:** Kang, with Claude (Founding Database Architect)
**Status:** Normative — every persistence-related component MUST conform; changes require an ADR
**Last updated:** 2026-07-11
**Upstream (binding):** `00_VISION.md`, `01_PRINCIPLES.md`, `02_PRODUCT_REQUIREMENTS.md`, `04_ARCHITECTURE.md` (D003, D004, D008, D009, D016), `06_MEMORY.md`
**Downstream:** `05_AGENTS.md`, `08_PLUGIN_SYSTEM.md`, `12_API.md`, `16_SYNC.md`

> **RFC-2119:** MUST / MUST NOT / SHOULD / MAY are used normatively. Assumptions are stated explicitly. There are no TODOs in this document.

---

## Part I — Philosophy

### 1.1 Why SQLite

SQLite is the persistence engine for all structured KANG state. The reasons are terminal, not preferences:

1. **Longevity.** SQLite's file format is one of the very few formats with a stated long-term support horizon measured in decades, is public domain, and is readable by effectively every programming language. A 2036 KANG MUST be able to open a 2026 database. No client-server database offers this guarantee without an operating burden.
2. **Zero administration.** There is no server to install, patch, secure, or restart. The database is a file. One part-time developer (Vision §9.1) cannot be a DBA; SQLite removes the role.
3. **Correct scale.** Part XIII of `06_MEMORY.md` establishes 10-year scale at 6–15 GB and low-hundreds-of-thousands of hot rows. This is SQLite's home territory with orders of magnitude to spare.
4. **Transparency (P2, P5).** `sqlite3 kang.db` in any terminal shows Kang his own life. No hidden storage is possible when the store is a single inspectable file.
5. **Transactional unity.** Structured state, memory, FTS, and vectors live in one transactional domain (§1.2), eliminating the multi-store consistency problem entirely.

### 1.2 Why one primary database

All authoritative structured state lives in **one file: `kang.db`**. Rejected: per-domain databases (projects.db, memory.db…).

**Why.** Cross-domain transactions are constant in KANG (archive project → write retrospective episode → update links → log invocation). One database makes these ACID by default. Separate files make them distributed transactions — the exact class of problem this architecture exists to avoid (Architecture §0).

**The two deliberate exceptions** (different write patterns, no cross-transactions needed):

| File | Why separate |
|---|---|
| `events/eventlog.db` | Write-ahead event log (D006): append-heavy, independent retention/compaction, and MUST survive/replay across `kang.db` restores — coupling them would entangle recovery domains |
| `audit/*.jsonl` | Append-only flat files (D004): integrity reasoning, grep-ability at 3 a.m., survives DB corruption by construction. **Audit is deliberately NOT in SQLite** |

`cache/*.db` files MAY exist (web cache, embedding cache); they are disposable by definition (§3.2) and carry no authority.

### 1.3 Why not the alternatives (recorded once, permanently)

| Alternative | Rejected because | Revisit trigger (Architecture §19) |
|---|---|---|
| **PostgreSQL** | A server process for one user: install/upgrade/auth/backup complexity with zero benefit at our scale; breaks single-file recovery (NFR-006) | A genuine multi-writer server deployment — i.e., a mission change |
| **Neo4j / graph DBs** | JVM server for 1–3-hop queries over ≤10⁶ edges that recursive CTEs answer in <10 ms (§7); links must live in their sources of truth anyway (D008) | A feature whose queries provably exceed CTE ergonomics |
| **Pinecone** | Cloud-hosted vectors = personal semantic memory on someone else's servers. Categorical P8 violation, not a trade-off | Never (principle-level) |
| **Chroma / Qdrant / LanceDB** | A second local store to back up, version, and keep consistent with row data; sqlite-vec keeps vectors in the same transaction as their records | Measured retrieval quality/latency failure of sqlite-vec on the synthetic 10-year corpus |
| **DuckDB** | OLAP engine; wrong tool for transactional app state | MAY be added read-only over exports for analytics; never authoritative |
| **JSON/flat files as primary store** | No transactions, no constraints, no queries; corruption-prone | Never for state (fine for config — §3.3) |

### 1.4 Database principles (normative)

1. **Single source of truth (AR6).** Every datum has exactly one authoritative table or file. Everything else — FTS, vectors, link_index, caches, views — is derived and MUST be rebuildable from truth with one command (`kang rebuild-indexes`).
2. **Deterministic state is sacred.** Deadlines, tasks, grants: exact queries only, never approximated retrieval (Memory §5.1).
3. **No hidden storage.** Every file KANG writes lives under `%KANG_HOME%` or the vault. Writing anywhere else is a critical bug.
4. **Everything explainable.** Every row can answer where it came from (provenance columns or originating audit entry). Schema design MUST NOT create anonymous data.
5. **Fail visibly, never corrupt silently.** Every failure path in Part XV resolves to loud degradation.
6. **Boring by construction (E10).** Features of SQLite used: WAL, FTS5, sqlite-vec, recursive CTEs, generated columns, partial indexes, triggers (narrowly, §5.5), `VACUUM INTO`. Features avoided: everything exotic.

---

## Part II — Physical Layout
%KANG_HOME%/
├── kang.db                  # THE database (WAL: kang.db-wal, kang.db-shm)
├── events/eventlog.db       # persistent event log (D006)
├── audit/YYYY-MM.jsonl      # append-only audit (monthly files)
├── config/                  # TOML truth: kang, permissions, providers, memory,
│   └── ...                  #   database, retention, backup, performance
├── cache/                   # DISPOSABLE: embeddings cache, web cache, thumbnails
├── backups/
│   ├── daily/kang-YYYYMMDD.db        # VACUUM INTO snapshots (30 rotating)
│   ├── monthly/kang-YYYYMM.db        # 12 rotating
│   └── manifest.jsonl                # backup records + verification results
├── plugins/                 # installed plugins (08_PLUGIN_SYSTEM)
└── exports/                 # kang export products (FR-103, D016)

Rules:

- The **vault is never inside `%KANG_HOME%`** and `kang.db` never stores note bodies — only references and derived chunks (M7).
- `cache/` MUST be deletable at any moment with zero data loss (tested: the corpus test suite runs a cache-wipe scenario).
- `exports/` holds outputs from `kang export` (FR-103, D016). Exports are products, not state: excluded from snapshots, excluded from retention machinery, excluded from backups.
- WAL sidecar files MUST be excluded from naive file-copy backups; backups use `VACUUM INTO` exclusively (§12).
---

## Part III — Connection & Transaction Model

### Decision DB-001 — Single writer connection, read pool, application-serialized writes

**Decision.**
- Exactly **one** write connection, owned by a single async write-executor task; all writes flow through it as queued, explicit transactions.
- A pool (default 4) of read-only connections (`PRAGMA query_only=ON`) serves all reads.
- PRAGMAs (set at open, verified at startup, drift = startup failure):

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous  = NORMAL;      -- durability note below
PRAGMA foreign_keys = ON;          -- per connection, always
PRAGMA busy_timeout = 5000;
PRAGMA wal_autocheckpoint = 1000;  -- pages; plus scheduled TRUNCATE checkpoint nightly
PRAGMA temp_store  = MEMORY;
PRAGMA cache_size  = -65536;       -- 64 MB page cache per connection
```

**Why.** SQLite is single-writer by nature; embracing it in the application (a write queue) eliminates `SQLITE_BUSY` handling everywhere else and makes write ordering deterministic — which sync's change log (§10) depends on. WAL gives readers-don't-block-writer, which is the actual concurrency KANG needs (dashboard reading while a job writes).

**Durability note (explicit assumption).** `synchronous=NORMAL` under WAL can lose the final transactions on OS crash/power loss (never corrupting). Accepted for most state because the event log (D006, written write-ahead with `synchronous=FULL` on its own connection) replays recent Tier-1 effects. The **write gate** additionally wraps memory-record commits with an event-log entry *before* the DB write — memory is recoverable to the exact record even across power loss. This pairing is normative.

**Alternatives.** `synchronous=FULL` everywhere (2–5× write latency for risk the event log already covers — rejected; MAY be enabled via `database.toml` on machines without battery); multiple writer connections with retry (rejected: nondeterministic ordering, busy-storm complexity); an ORM managing connections (see DB-002).

**Trade-offs.** All writes serialize: a slow write delays others. Mitigated: writes are small (rows, not blobs); bulk jobs chunk into ≤1000-row transactions with yield points.

**Scaling implications.** The write queue is also the future sync-outbox hook (§10): one interception point for change capture.

### Decision DB-002 — SQL-first, no ORM

**Decision.** Raw SQL via a thin typed repository layer (ports from D005). Migrations are SQL files. No ORM (SQLAlchemy et al.).

**Why.** The schema *is* the specification; hiding it behind a mapper obscures the thing this document exists to make explicit (P5). ORMs bring session/identity-map magic (violates E4), migration auto-generation drift, and a decade-scale dependency on someone else's abstraction over our most critical asset.

**Alternatives.** SQLAlchemy Core (query builder only — the least bad ORM option; still rejected: one more layer to be fluent in forever); Django ORM (framework gravity — rejected outright).

**Trade-offs.** More hand-written SQL; repository tests carry the correctness load (Part XVI). Accepted: SQL is the most durable skill and most durable code in this stack.

**Transactions (normative rules):**
- Every write is an explicit transaction (`BEGIN IMMEDIATE`); autocommit writes are forbidden.
- Multi-entity operations (archive project + episode + links) MUST be one transaction — partial application is forbidden.
- Savepoints are used inside batch jobs for per-item rollback without losing the batch.
- Read connections MUST NOT hold transactions open across await points >100 ms (WAL file growth); long analytical reads use a dedicated snapshot connection.

---

## Part IV — Keys, Identity & Time

### Decision DB-003 — UUIDv7 as lowercase TEXT

**Decision.** Every synchronizable entity's primary key is a UUIDv7, stored as 36-char lowercase TEXT. Local-only rows (job_run, model_call) MAY use `INTEGER PRIMARY KEY` rowids.

**Why UUIDv7:** time-ordered (index-friendly inserts, meaningful default sort), collision-free across future devices (D009 — retrofit is brutal, adopt at v0.1), standard.
**Why TEXT not BLOB(16):** inspectability (Principle 1.4.4 — Kang reads his own DB); joins remain human-debuggable; the size cost (~20 bytes/row×keys) is irrelevant at Part XIV scale. Transparency beats 16 bytes.

**Time:** all timestamps are TEXT ISO-8601 UTC (`YYYY-MM-DDTHH:MM:SS.SSSZ`) — sortable, human-readable, timezone-unambiguous. Local time is a presentation concern. The clock-skew guard (Memory XIV-9) is enforced at the write executor: writes with `created_at` beyond ±24h of wall clock are refused.

**Constraints doctrine:**
- Foreign keys: ON, always; `ON DELETE` is explicit per relationship (mostly `RESTRICT`; `CASCADE` only parent→owned-child like project→task, and each CASCADE is listed in Appendix B).
- CHECK constraints enforce every closed enum from `06_MEMORY.md` (types, statuses, tiers, link types) — **the taxonomy is enforced by the database, not by convention.**
- `NOT NULL` on all provenance columns (Memory Part VIII: missing provenance is a schema violation — literally).

### 4.1 Views & triggers policy

- **Views** are the sanctioned read shapes: `v_active_deadlines`, `v_today_tasks`, `v_project_memory` (the domain views of Memory §2.1C), `v_contested_records`. Application code SHOULD read domain aggregates via views so "what the Planner sees" is inspectable in SQL.
- **Triggers** are restricted to three mechanical duties: FTS5 external-content synchronization, `updated_at`/`revision` bumps, and change-capture rows (§10). **Business logic in triggers is forbidden** — invisible control flow violates E4/P5.

---

## Part V — Schema

### 5.0 Event Log Schema (15_EVENT_BUS.md §5.2)

Adopted from 15_EVENT_BUS EB-005 at authoring; 07 is now the DDL's home; amendments land here.

```sql
CREATE TABLE event (
  seq            INTEGER PRIMARY KEY,          -- single-writer monotonic
  event_id       TEXT NOT NULL UNIQUE,          -- UUIDv7
  type           TEXT NOT NULL,
  type_version   INTEGER NOT NULL DEFAULT 1,
  occurred_at    TEXT NOT NULL,
  recorded_at    TEXT NOT NULL,
  principal      TEXT NOT NULL,
  correlation_id TEXT NOT NULL,
  causation_id   TEXT,                          -- parent event_id, nullable
  entity_refs    TEXT NOT NULL,                 -- JSON array
  payload        TEXT NOT NULL,                 -- JSON, schema-validated
  provenance     TEXT NOT NULL CHECK (provenance IN
                   ('kang','derived','external_untrusted')),
  recovery_grade INTEGER NOT NULL DEFAULT 0,
  device_id      TEXT NOT NULL,
  state          TEXT NOT NULL DEFAULT 'pending' CHECK (state IN
                   ('pending','confirmed','orphaned'))
);
CREATE INDEX idx_event_type       ON event(type, seq);
CREATE INDEX idx_event_corr       ON event(correlation_id);
CREATE INDEX idx_event_pending    ON event(state) WHERE state = 'pending';

CREATE TABLE subscription_cursor (
  subscriber   TEXT PRIMARY KEY,
  last_seq     INTEGER NOT NULL DEFAULT 0,
  updated_at   TEXT NOT NULL
);

CREATE TABLE dead_letter (
  id           TEXT PRIMARY KEY,
  event_seq    INTEGER NOT NULL REFERENCES event(seq),
  subscriber   TEXT NOT NULL,
  attempts     INTEGER NOT NULL,
  last_error   TEXT NOT NULL,
  created_at   TEXT NOT NULL,
  resolved     TEXT CHECK (resolved IN ('redelivered','discarded')),
  resolved_at  TEXT
);
```

Index doctrine per Part VI: every index cites its consumer; speculative indexes forbidden. Compaction (90 days, D006) deletes `confirmed` events below every subscriber's cursor; `orphaned` rows and unresolved `dead_letter` rows are **never compacted away silently** — they are surfaced until Kang resolves them.
### 5.1 Memory domain (implements `06_MEMORY.md`)

```sql
CREATE TABLE memory_record (
  id            TEXT PRIMARY KEY,                -- UUIDv7
  type          TEXT NOT NULL CHECK (type IN
                 ('profile','preference','fact','relationship',
                  'lesson','rule','observation','reflection')),
  status        TEXT NOT NULL DEFAULT 'candidate' CHECK (status IN
                 ('candidate','active','under_review','superseded',
                  'archived','rejected')),                    -- deleted = row gone + tombstone
  content       TEXT NOT NULL CHECK (length(content) > 0),
  trust_tier    INTEGER NOT NULL CHECK (trust_tier IN (0,1,2)),
  confidence    REAL NOT NULL DEFAULT 1.0 CHECK (confidence BETWEEN 0 AND 1),
  sensitivity   TEXT NOT NULL DEFAULT 'normal' CHECK (sensitivity IN
                 ('normal','sensitive','private')),
  content_enc   BLOB,            -- §11: ciphertext when sensitivity='private'
                                 -- INVARIANT (CHECK): private ⇒ content = '[encrypted]'
                                 --                    AND content_enc NOT NULL
  source_kind   TEXT NOT NULL CHECK (source_kind IN
                 ('stated','observed','vault','web','rule','consolidation')),
  source_detail TEXT NOT NULL,   -- url | vault path#anchor | rule:{id} | invocation id
  source_quote  TEXT,            -- original wording where applicable
  reason        TEXT NOT NULL CHECK (length(reason) > 0),
  created_by    TEXT NOT NULL,   -- principal: 'kang' | 'rule:{id}' | 'agent:{id}' | 'plugin:{id}'
  created_at    TEXT NOT NULL, updated_at TEXT NOT NULL,
  device_id     TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
  importance    REAL NOT NULL DEFAULT 0.5 CHECK (importance BETWEEN 0 AND 1),
  pinned        INTEGER NOT NULL DEFAULT 0 CHECK (pinned IN (0,1)),
  last_accessed TEXT, access_count INTEGER NOT NULL DEFAULT 0,
  embedding_ver INTEGER            -- FK → embedding_version; NULL = not yet embedded
);

CREATE TABLE memory_revision (     -- edit history (Memory §8.2)
  record_id  TEXT NOT NULL REFERENCES memory_record(id) ON DELETE CASCADE,
  revision   INTEGER NOT NULL,
  content    TEXT NOT NULL,
  edited_by  TEXT NOT NULL, edited_at TEXT NOT NULL,
  PRIMARY KEY (record_id, revision)
);

CREATE TABLE episode (
  id         TEXT PRIMARY KEY,
  type       TEXT NOT NULL CHECK (type IN
              ('plan','review','retrospective','session','decision')),
  occurred_at TEXT NOT NULL,      -- event time (distinct from created_at)
  content    TEXT NOT NULL,       -- structured JSON body, type-specific schema
  summary    TEXT,                -- human-readable one-liner for lists
  status     TEXT NOT NULL DEFAULT 'active' CHECK (status IN
              ('active','compressed','archived')),
  compressed_into TEXT REFERENCES episode(id),   -- abstraction pass (Memory §6.1)
  -- provenance block (identical discipline):
  source_kind TEXT NOT NULL, source_detail TEXT NOT NULL,
  reason TEXT NOT NULL, created_by TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  device_id TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
  embedding_ver INTEGER
);

CREATE TABLE memory_candidate_queue (   -- quarantine (Memory §4.3); same shape as
  id TEXT PRIMARY KEY,                  -- memory_record minus retrieval fields, plus:
  payload      TEXT NOT NULL,           -- full proposed record as JSON
  flags        TEXT NOT NULL DEFAULT '[]',  -- ['near_duplicate','conflict']
  flag_context TEXT,                    -- ids of dup/conflict counterparts
  proposed_at  TEXT NOT NULL, expires_at TEXT NOT NULL,   -- +14d
  resolved     TEXT CHECK (resolved IN ('approved','edited','rejected','expired')),
  resolved_at  TEXT
);

CREATE TABLE tombstone (
  id TEXT PRIMARY KEY,               -- id of the destroyed row
  entity TEXT NOT NULL,              -- 'memory_record' | 'episode' | ...
  deleted_at TEXT NOT NULL, deleted_by TEXT NOT NULL,
  policy_ref TEXT                    -- retention.toml line or 'kang:explicit'
);
```

### 5.2 Structured operational domain

```sql
CREATE TABLE project (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN
    ('active','paused','completed','archived','abandoned')),
  vault_folder TEXT,                 -- path within vault (reference, not content)
  github_repo TEXT,                  -- owner/name
  goal_id TEXT REFERENCES goal(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  device_id TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE task (
  id TEXT PRIMARY KEY,
  project_id TEXT REFERENCES project(id) ON DELETE CASCADE,  -- NULL = standalone
  title TEXT NOT NULL, notes TEXT,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN
    ('open','scheduled','done','deferred','dropped')),
  priority INTEGER NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
  due TEXT, plan_date TEXT,          -- date scheduled into a daily plan
  estimate_min INTEGER, actual_min INTEGER,   -- calibration data (lessons!)
  completed_at TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  device_id TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE milestone (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  title TEXT NOT NULL, due TEXT,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN
    ('pending','reached','missed','dropped')),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  device_id TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1
);

```

**Initial seed data** (`quarter` and `year` only — per `docs/adr/003-goal-
horizon-5yr.md`, accepted): `horizon='quarter'` → "Ship KANG v0.1" (this
quarter's aim); `horizon='year'` → ranked list, 1 = highest — KANG v0.1
shipped and used daily, Olympiad result/medal, grades locked in, money saved
(rank order is the content; do not flatten it into an unranked set).
`horizon='life'` stays intentionally empty, per the intake's own finding
(Kang: "unresolved, honestly" — do not fabricate a life-goal narrative;
revisit quarterly). Source: `docs/guides/user-profile-intake-2026-07.md`
D15. Not a migration; not applied here — this is intent for M5's first
runtime population. The intake also names a 5-year candidate goal (NUS
admission, explicitly "candidate not committed") — ADR-003 decided it stays
in the vault/guide, not the `goal` table, until it becomes a real
commitment; `horizon` above deliberately has no slot for it.

```sql
CREATE TABLE goal (
  id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT,
  horizon TEXT NOT NULL CHECK (horizon IN ('quarter','year','life')),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN
    ('active','achieved','revised','retired')),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  device_id TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE competition (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, url TEXT,
  status TEXT NOT NULL DEFAULT 'discovered' CHECK (status IN
    ('discovered','evaluating','entered','skipped','submitted',
     'judged','archived')),
  evaluation TEXT,                   -- JSON: fit/feasibility/effort/risk brief
  result TEXT,                       -- JSON: outcome after judging
  project_id TEXT REFERENCES project(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  device_id TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE deadline (
  id TEXT PRIMARY KEY,
  competition_id TEXT REFERENCES competition(id) ON DELETE CASCADE,
  project_id     TEXT REFERENCES project(id)     ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN
    ('registration','submission','event','school','custom')),
  title TEXT NOT NULL, at TEXT NOT NULL,
  lead_days TEXT NOT NULL DEFAULT '[14,7,3,1]',   -- JSON alert schedule
  status TEXT NOT NULL DEFAULT 'tracked' CHECK (status IN
    ('tracked','alerted','met','missed','cancelled')),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  device_id TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
  CHECK (competition_id IS NOT NULL OR project_id IS NOT NULL
         OR kind IN ('school','custom'))
);

CREATE TABLE quiz_result (
  id TEXT PRIMARY KEY, topic TEXT NOT NULL,
  score REAL NOT NULL, max_score REAL NOT NULL, detail TEXT,  -- JSON per-question
  taken_at TEXT NOT NULL, created_at TEXT NOT NULL,
  device_id TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE repetition_item (      -- spaced repetition (FR-042, FR-092)
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('learning','scripture')),
  prompt TEXT NOT NULL, answer TEXT,
  ease REAL NOT NULL DEFAULT 2.5, interval_days REAL NOT NULL DEFAULT 1,
  due TEXT NOT NULL, lapses INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  device_id TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE calendar_cache (       -- DERIVED (truth = provider, PRD §12); rebuildable
  provider_event_id TEXT PRIMARY KEY,
  calendar_id TEXT NOT NULL, title TEXT, starts TEXT, ends TEXT,
  all_day INTEGER NOT NULL DEFAULT 0, fetched_at TEXT NOT NULL
);
```

### 5.3 Vault reference domain (derived; truth = Markdown files)

```sql
CREATE TABLE vault_note (
  path TEXT PRIMARY KEY,             -- vault-relative, forward slashes
  title TEXT, mtime TEXT NOT NULL, size INTEGER NOT NULL,
  content_hash TEXT NOT NULL,        -- change detection
  indexed_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'indexed' CHECK (status IN
    ('indexed','stale','missing'))   -- 'missing' drives broken-link flow (Memory XIV-5)
);

CREATE TABLE vault_chunk (
  id TEXT PRIMARY KEY,
  note_path TEXT NOT NULL REFERENCES vault_note(path) ON DELETE CASCADE,
  anchor TEXT,                       -- heading anchor
  seq INTEGER NOT NULL,              -- order within note
  content TEXT NOT NULL,             -- the excerpt text (derived copy, rebuildable)
  token_est INTEGER NOT NULL,
  embedding_ver INTEGER,
  UNIQUE (note_path, seq)
);
```

### 5.4 Link domain (implements D008 + Memory Part IX)

```sql
CREATE TABLE link (                  -- AUTHORITATIVE for memory-originated edges only
  id TEXT PRIMARY KEY,
  src_kind TEXT NOT NULL, src_id TEXT NOT NULL,   -- ('memory','episode','project',
  dst_kind TEXT NOT NULL, dst_id TEXT NOT NULL,   --  'task','competition','goal',
  type TEXT NOT NULL CHECK (type IN               --  'note','conversation','person')
    ('relates_to','derived_from','supersedes','superseded_by','contradicts',
     'about_project','about_competition','about_goal','about_person',
     'references_note','from_conversation','evidence_for','evidence_against')),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','broken','retired')),
  created_by TEXT NOT NULL, created_at TEXT NOT NULL, reason TEXT,
  device_id TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
  UNIQUE (src_kind, src_id, dst_kind, dst_id, type)
);

CREATE TABLE link_index (            -- DERIVED merge: link ∪ vault wikilinks ∪ FKs
  src TEXT NOT NULL, dst TEXT NOT NULL,   -- composite refs 'kind:id' / 'note:path'
  type TEXT NOT NULL,
  origin TEXT NOT NULL CHECK (origin IN ('link','wikilink','fk')),
  PRIMARY KEY (src, dst, type, origin)
) WITHOUT ROWID;
```

`link_index` is rebuilt incrementally by the indexer and fully by `kang rebuild-indexes`. Graph queries (`WITH RECURSIVE`, depth ≤ 3, cycle-guarded via visited-set) run against `link_index` only.

### 5.5 System domain

```sql
CREATE TABLE job (                   -- scheduler (D014)
  id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE,
  schedule TEXT NOT NULL,            -- cron expr | 'event:{type}'
  catch_up TEXT NOT NULL CHECK (catch_up IN ('run_once_latest','run_all_missed','skip')),
  enabled INTEGER NOT NULL DEFAULT 1,
  timeout_s INTEGER NOT NULL DEFAULT 300,
  quarantined INTEGER NOT NULL DEFAULT 0,      -- auto-disable on repeated failure
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE job_run (
  id INTEGER PRIMARY KEY,            -- local-only: rowid fine (DB-003)
  job_id TEXT NOT NULL REFERENCES job(id) ON DELETE CASCADE,
  started TEXT NOT NULL, finished TEXT,
  outcome TEXT CHECK (outcome IN ('ok','failed','timeout','skipped')),
  detail TEXT, correlation_id TEXT NOT NULL
);

CREATE TABLE held_action (            -- consequential-action gate (12 §7, D-owed;
                                      --   docs/adr/001-held-action-crash-semantics.md)
  id            TEXT PRIMARY KEY,     -- UUIDv7
  operation     TEXT NOT NULL,        -- registry operation name — resolves
                                      --   commit_mode on approval/recovery
  action        TEXT NOT NULL,        -- what will happen (exact)
  principal     TEXT NOT NULL,        -- who asked
  reason        TEXT NOT NULL,        -- why (one paragraph max)
  reversibility TEXT NOT NULL,        -- the reversibility statement
  correlation_id TEXT NOT NULL,       -- thread to invocation/audit
  created_at    TEXT NOT NULL,
  expires_at    TEXT NOT NULL,        -- created_at + 24h (12 §7)
  status        TEXT NOT NULL DEFAULT 'pending' CHECK (status IN
                  ('pending','approved','executed','cancelled'))
                                      -- 'approved' = intent recorded, not done;
                                      --   'executed' = the held effect committed
                                      --   (ADR 001: approved != done)
);
CREATE INDEX idx_held_action_pending ON held_action(status, created_at)
  WHERE status = 'pending';

CREATE TABLE agent_invocation (      -- execution history (observability, D015)
  id TEXT PRIMARY KEY, correlation_id TEXT NOT NULL,
  agent TEXT NOT NULL, task_class TEXT NOT NULL,
  trigger TEXT NOT NULL,             -- 'kang' | 'job:{id}' | 'event:{type}'
  started TEXT NOT NULL, finished TEXT,
  outcome TEXT CHECK (outcome IN ('ok','failed','degraded','denied')),
  manifest TEXT,                     -- context manifest JSON (Memory §5.4);
  manifest_pruned INTEGER NOT NULL DEFAULT 0   -- content→ids-only after 180d
);

CREATE TABLE model_call (            -- usage & cost ledger (D010)
  id INTEGER PRIMARY KEY,
  invocation_id TEXT REFERENCES agent_invocation(id) ON DELETE SET NULL,
  provider TEXT NOT NULL, model TEXT NOT NULL, task_class TEXT NOT NULL,
  tokens_in INTEGER NOT NULL, tokens_out INTEGER NOT NULL,
  cost_usd REAL NOT NULL DEFAULT 0, latency_ms INTEGER NOT NULL,
  outcome TEXT NOT NULL CHECK (outcome IN ('ok','error','timeout','fallback')),
  at TEXT NOT NULL
);

CREATE TABLE conversation (          -- metadata; transcript retention per Memory §7.1
  id TEXT PRIMARY KEY, started TEXT NOT NULL, last_message TEXT NOT NULL,
  title TEXT, message_count INTEGER NOT NULL DEFAULT 0,
  purged INTEGER NOT NULL DEFAULT 0  -- transcript gone; id survives for from_conversation links
);
CREATE TABLE message (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversation(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('kang','kang_system','agent')),
  content TEXT NOT NULL, at TEXT NOT NULL
);

CREATE TABLE principal (             -- registry; grants live in permissions.toml (truth)
  id TEXT PRIMARY KEY,               -- 'kang' | 'agent:planner' | 'plugin:x' | 'rule:y'
  kind TEXT NOT NULL CHECK (kind IN ('user','agent','plugin','rule','system')),
  created_at TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE setting (             -- runtime-mutable UI/system state ONLY
  key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL
);  -- Config truth stays in TOML (D003). setting holds window layouts,
    -- last-seen markers, product state (§PRD 11) — never policy.

CREATE TABLE schema_version (
  version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL,
  checksum TEXT NOT NULL             -- of the migration file, verified on startup
);
```

**Permissions clarification (normative).** Grant *truth* is `config/permissions.toml` (D003: diffable, hand-editable in recovery). The DB stores only the `principal` registry and audit references. A permissions table as truth was considered and rejected: policy-in-DB is invisible to diff/review and mutable by the thing it governs.

### 5.6 Sync-preparation domain (built at v0.1, used at v0.5 — D009)

```sql
CREATE TABLE change_log (            -- outbox: row-level change capture
  seq INTEGER PRIMARY KEY,           -- strictly ordered by the single writer
  entity TEXT NOT NULL, entity_id TEXT NOT NULL,
  op TEXT NOT NULL CHECK (op IN ('insert','update','delete')),
  fields TEXT,                       -- JSON: changed field names (update only)
  revision INTEGER NOT NULL, device_id TEXT NOT NULL, at TEXT NOT NULL,
  synced INTEGER NOT NULL DEFAULT 0
);
```

Populated by narrow AFTER-triggers on synchronizable tables (the third sanctioned trigger duty, §4.1). Until sync ships: rotated at 90 days by the janitor; the mechanism is exercised (and tested) from day one so v0.5 builds on proven capture, not fresh code. Tombstones (§5.1) complete the delete story; per-field LWW uses `revision` + `fields`.

---

## Part VI — Index Strategy

**Doctrine.** Indexes exist to serve *named queries* (the views + repository methods). Every index in the schema cites its consumer in a comment. Speculative indexes are forbidden — each one taxes every write and bloats the file. Starting set:

```sql
-- Planner P0 (v_today_tasks, v_active_deadlines)
CREATE INDEX idx_task_plan     ON task(plan_date, status) WHERE status IN ('open','scheduled');
CREATE INDEX idx_task_project  ON task(project_id, status);
CREATE INDEX idx_deadline_at   ON deadline(at) WHERE status = 'tracked';
-- Memory retrieval prefilters (Memory §5.2 filters-before-scoring)
CREATE INDEX idx_mem_type_stat ON memory_record(type, status, sensitivity);
CREATE INDEX idx_mem_status    ON memory_record(status) WHERE status = 'under_review';
CREATE INDEX idx_episode_time  ON episode(type, occurred_at);
-- Link traversal
CREATE INDEX idx_linkindex_dst ON link_index(dst, type);
-- Ledger/analytics
CREATE INDEX idx_modelcall_at  ON model_call(at);
CREATE INDEX idx_changelog_syn ON change_log(synced, seq);
```

Notes: partial indexes (`WHERE`) keep hot-path indexes small; `link_index` is `WITHOUT ROWID` (the PK *is* the data). Index health: `PRAGMA integrity_check` covers structure; the quarterly retention audit re-runs `EXPLAIN QUERY PLAN` on all named queries and fails CI if a plan regresses to a full scan (Part XVI).

### 6.1 FTS5

```sql
CREATE VIRTUAL TABLE fts_memory USING fts5(
  content, content='memory_record', content_rowid='rowid',
  tokenize = 'porter unicode61'
);
-- sync triggers: AFTER INSERT/UPDATE(content)/DELETE on memory_record
-- (identical pattern for fts_episode, fts_chunk, fts_message)
```

External-content mode (no text duplication). **Private-sensitivity rows are excluded by trigger condition** — ciphertext is not indexed, plaintext of private records never exists in the DB (§11). `INSERT INTO fts_x(fts_x) VALUES('rebuild')` is wired into `kang rebuild-indexes`.

### 6.2 sqlite-vec

```sql
CREATE VIRTUAL TABLE vec_memory USING vec0(
  record_rowid INTEGER PRIMARY KEY,
  embedding float[768]               -- dimension fixed per embedding_version, §8
);
-- vec_episode, vec_chunk identical
```

Vector tables are derived (Principle 1.4.1): droppable and rebuildable from content + the embedding provider. They are maintained by the embedding worker (async, batched), not by triggers — embedding is I/O, and triggers doing I/O is forbidden.

---

## Part VII — Relationship Layer (graph without a graph DB)

The canonical traversal (link-distance ≤ 2, Memory §9.2):

```sql
WITH RECURSIVE hop(node, depth) AS (
  SELECT :start, 0
  UNION
  SELECT li.dst, hop.depth + 1
  FROM link_index li JOIN hop ON li.src = hop.node
  WHERE hop.depth < :max_depth
)
SELECT DISTINCT node, MIN(depth) FROM hop GROUP BY node;
```

- `UNION` (not `UNION ALL`) provides cycle safety; depth cap ≤ 3 is enforced in the repository layer.
- Benchmarked target: <10 ms at 400k edges (Part XIV; verified in CI on the synthetic corpus).
- **Integrity:** the nightly janitor cross-checks `link` endpoints against live rows → dangling links become `broken` (never silently deleted — Memory XIV-5). `link_index` needs no integrity of its own: it is disposable.
- Why this beats a graph DB at our scale: the queries are shallow, the edge count is small, and the index is one `WITHOUT ROWID` table living inside the same transaction domain as everything else. Cypher's expressiveness is solving problems KANG doesn't have.

---

## Part VIII — Vector Search & Embedding Lifecycle

### Decision DB-004 — 768-dim default, versioned embeddings, dual-index migration

**Decision.**
- Embedding space: **768 dimensions, float32** as the v1 default (`embedding_version = 1`), targeting a strong local-capable model class; the concrete model is pinned in `providers.toml` and recorded in the `embedding_version` table:

```sql
CREATE TABLE embedding_version (
  ver INTEGER PRIMARY KEY, model TEXT NOT NULL, dim INTEGER NOT NULL,
  created_at TEXT NOT NULL, status TEXT NOT NULL CHECK (status IN
    ('active','migrating','retired'))
);
```

- Every embedded row carries `embedding_ver`. Mixing versions in one vec table is forbidden (cosine across spaces is meaningless): each version gets its own `vec_*_v{n}` virtual table.
- **Model upgrade protocol (Memory XIV-6, made concrete):** create `v{n+1}` tables → background re-embed in mtime/priority order (hot rows first) → hybrid scorer reads old-version vectors *only* for rows not yet migrated (per-row fallback, FTS unaffected) → when coverage = 100%, atomic config cutover → drop old tables. The system never has a retrieval blackout during migration.
- Embedding cache (`cache/embeddings.db`): content-hash → vector, survives re-index (not re-model).

**Why 768/float32:** the sweet spot of local-model availability, quality, and size (768 × 4 B ≈ 3 KB/row; ~1.5 GB at the 10-year 500k-chunk ceiling — trivial). **Assumption stated:** if the v0.2 embedding benchmark (Architecture §20.1) selects a different-dimension model, `embedding_version` absorbs it — the *protocol* is the commitment, the dimension is a parameter.
**Alternatives:** 384-dim (cheaper, meaningfully worse on technical text — Kang's corpus is technical); 1536+ API-only dims (violates local-first trajectory D010); quantized int8 (MAY adopt later via a new version — the protocol handles it).
**Trade-off:** per-version tables add bookkeeping. Accepted: it is exactly the bookkeeping that makes decade-scale model churn survivable.

---

## Part IX — (reserved)

Section intentionally reserved to keep part numbering stable across future revisions of this document. (Numbering stability matters: downstream docs cite parts by number.)

---

## Part X — Sync Preparation (design-only; D009 binding)

What this document guarantees so `16_SYNC.md` can be written without schema surgery:

1. **Identity:** UUIDv7 everywhere synchronizable (DB-003); `device_id` on every synchronizable row.
2. **Versioning:** `revision` monotonic per row, bumped by trigger on update.
3. **Capture:** `change_log` outbox (§5.6) ordered by the single writer — a total order per device, which is the precondition for deterministic merge.
4. **Deletes:** tombstones (§5.1) for every destroyed synchronizable row.
5. **Clocks:** merge policy MUST use `(revision, device_id)` ordering with `at` as tiebreak only — wall clocks are advisory (Memory XIV-9). Conflicts resolve per-field LWW + surfaced conflict record (PRD §12); both losers preserved in `memory_revision`/change history.
6. **CRDT posture (recorded):** field-LWW-with-surfacing is the deliberate choice over CRDTs for a single-human system (D009 alternatives). If v0.5 reality shows real concurrent-edit pain, the change_log's total-order-per-device is exactly the substrate a CRDT layer would need — nothing here forecloses it.

**MUST NOT:** ship any code that syncs `kang.db` as a file (the corruption classic, D009).

---

## Part XI — Encryption

### Decision DB-005 — Application-level record encryption; no SQLCipher

*(Resolves Architecture §20.3.)*

**Decision.**
- `sensitivity='private'` records: `content` column holds the literal placeholder `'[encrypted]'`; real content lives in `content_enc` as libsodium `crypto_secretbox` ciphertext (XChaCha20-Poly1305), key held in **Windows Credential Manager** (S7), fetched at unlock, held in locked memory, never written to disk/logs.
- Searchable metadata of private records (type, dates, status, links) stays plaintext — **by design**: lifecycle, sync, and audit must function without decryption. Content is the secret; existence is not. (If existence itself is ever secret, that record does not belong in KANG — stated honestly.)
- Private rows are excluded from FTS and vec indexes by trigger/worker condition (§6.1). Retrieval of private content happens only in the Faith-style granted path (Memory §12.1), decrypt-on-read, local-model-only TaskSpec.
- `sensitive` (non-private) records: plaintext in DB; protection is scope-based (grants) + the strong recommendation of OS full-disk encryption (BitLocker), which is the honest defense for the whole file anyway (threat model D013: app-level measures do not survive same-user malware; we do not pretend otherwise).

**Why not SQLCipher:** whole-file encryption breaks casual inspectability (Principle 1.4.4) for *all* data to protect a tiny fraction; complicates `VACUUM INTO` backup tooling and third-party DB browsers; adds a native fork of SQLite to track for a decade. Record-level encryption puts the boundary exactly where the sensitivity boundary is.
**Alternatives:** SQLCipher (above); OS EFS per-directory (opaque, Windows-edition-dependent); no encryption + BitLocker only (rejected: prayer journal deserves defense-in-depth per PRD §10.14's "verifiably private" success criterion).
**Trade-off:** private content is invisible to FTS/vector search — private records are findable by metadata only. Accepted deliberately: unsearchable is the point.
**Scaling:** key rotation = new key version column + background re-encrypt (same dual-version pattern as embeddings — one protocol, reused).

---

## Part XII — Backup Strategy

**Mechanism (normative):**

1. **Daily snapshot** (02:30, Sleeping state): `PRAGMA integrity_check` → on OK, `VACUUM INTO 'backups/daily/kang-YYYYMMDD.db'` → record in `backups/manifest.jsonl` (size, duration, integrity result, schema_version).
   - `VACUUM INTO` produces a consistent, defragmented, WAL-independent copy while the DB stays live. It is the only sanctioned backup method. File-copying a live WAL database is forbidden.
2. **Retention:** 30 daily + 12 monthly (first snapshot of each month promoted). Event log and audit files are included in the daily job (audit: current month file copy; eventlog: its own `VACUUM INTO`).
3. **Verification — the monthly restore test (D016, automated):** open latest snapshot read-only → `integrity_check` → run the *named-query suite* against it (every view returns, plans don't regress) → row-count sanity vs. live (±expected churn) → write result to manifest + health panel. **A backup that hasn't been restore-tested is treated as nonexistent.**
4. **Single-record restore** (Memory §7.2): `ATTACH` snapshot → copy row(s) + revisions → detach. Exposed in the memory browser as "restore from snapshot."
5. **Off-machine:** KANG's own duty ends at `backups/`; the health panel warns (weekly) if `%KANG_HOME%` shows no evidence of external backup (last-backup-age heuristic on a Kang-configured marker). KANG cannot force this; it can refuse to let it be forgotten.

**Timing targets:** snapshot < 60 s at 10-year size (sequential write of ≤15 GB — comfortably; measured in the corpus suite); restore-test < 5 min; single-record restore < 5 s.

---

## Part XIII — Migration Strategy

1. **Versioning:** `schema_version` table (§5.5); migrations are files `migrations/NNNN_description.sql` (Python companion `NNNN_description.py` permitted only for data transforms SQL can't express — each Python migration requires a test).
2. **Forward-only** (D016): no down-migrations. Rollback = restore pre-migration snapshot (which the update process takes automatically). Down-migrations are a lie at decade scale — they are never tested against real data drift; the snapshot is.
3. **Protocol (staged, D016):** update process copies live DB → applies migrations to the **copy** → runs integrity + named-query suite on the copy → on pass, atomic swap (rename dance) → on fail, refuse update, report, live DB untouched.
4. **Checksums:** each applied migration's file checksum is stored; startup verifies history matches the shipped migration set — a modified historical migration is a startup-blocking error (the past is immutable).
5. **Provenance invariant (MUST):** no migration may drop or weaken provenance columns/constraints. A migration that cannot map old provenance to new losslessly MUST refuse to run (Memory §8.1). This clause outranks convenience permanently.
6. **Compatibility posture:** the app refuses to open a DB with `schema_version` > its own (no forward reading); older DBs are migrated on first open via the protocol above.

---

## Part XIV — Performance Envelope

Scale (inherits Memory §13.1; DB-level view):

| Horizon | Hot rows (all tables) | kang.db size | Largest table |
|---|---|---|---|
| 1 yr | ~150k | 0.5–1.5 GB | vault_chunk (~50k) |
| 5 yr | ~700k | 3–8 GB | vault_chunk (~250k) |
| 10 yr | ~1.5M | 6–15 GB | vault_chunk (~500k) |

(`model_call` and `job_run` are the row-count leaders long-term; both are prunable ledgers — retention.toml — and excluded from "hot.")

**Latency budgets** (CI-enforced on the 10-year synthetic corpus, cold cache, mid-range NVMe laptop — the assumption is stated so the benchmark is honest):

| Operation | Budget |
|---|---|
| Named P0 views (today, deadlines) | < 20 ms |
| Single-row insert via write queue (enqueue→durable) | < 15 ms typical, < 50 ms p99 |
| Hybrid candidate fetch (vec k=64 + FTS k=64 + prefilter) | < 250 ms |
| Recursive link query (depth 2) | < 10 ms |
| FTS query (deep search) | < 100 ms |
| `VACUUM INTO` snapshot | < 60 s |
| Full index rebuild (`kang rebuild-indexes`) | < 15 min |
| Startup (open + pragma + version check) | < 500 ms (inside NFR-001's 5 s) |

Exceeding a budget in CI is a failing build, not a warning (Part XVI).

---

## Part XV — Failure Modes & Recovery

The rule, restated as the contract every row below satisfies: **everything fails visibly; nothing silently corrupts.**

| # | Failure | Detection | Immediate response | Recovery |
|---|---|---|---|---|
| 1 | File corruption | Daily `integrity_check` (pre-backup) + on suspicious error codes | Freeze writes (queue holds), banner alert, health panel red | Restore latest verified snapshot; replay event log for post-snapshot Tier-1 effects (DB-001 durability pairing); report the gap explicitly |
| 2 | Partial write / crash mid-transaction | SQLite journal recovery (automatic, WAL) | None needed — atomicity is SQLite's contract | Verify with integrity_check on next start (always runs after unclean shutdown flag) |
| 3 | Power loss | Unclean-shutdown marker | Startup integrity_check + event-log replay window check | Worst case: last transactions re-applied from event log or visibly reported as lost (never half-applied) |
| 4 | Disk full | Write-executor catches SQLITE_FULL; free-space watchdog warns at <2 GB | Writes queue-and-hold; monitors pause; loud alert | Kang frees space; queue drains; nothing lost (queue is bounded — beyond bound, oldest *non-critical* jobs shed with audit note) |
| 5 | Migration failure | Staged protocol (XIII.3) fails on the copy | Update refused; live DB untouched | Fix migration, retry; live system never at risk |
| 6 | Index corruption (FTS/vec) | Named-query suite anomalies; explicit `rebuild` on checksum mismatch | Affected index dropped | `kang rebuild-indexes` (< 15 min); FTS/vec are derived — recovery is total by construction |
| 7 | Embedding store desync (rows without vectors / orphan vectors) | Nightly janitor count reconciliation | Worker re-queues gaps; orphans dropped | Self-healing; persistent gaps alert (worker health issue) |
| 8 | permissions.toml corrupt/missing | Startup schema validation of TOML | **Fail closed:** all non-Kang principals denied; system runs in Kang-only mode with banner | Restore file from config backup (in daily snapshot set) or re-grant via UI |
| 9 | change_log overflow (sync never enabled) | Size metric | Janitor rotation (90 d) — by design, not failure | — |
| 10 | Clock skew | Write-executor ±24h guard (DB-003) | Refuse writes with alert | Fix clock; UUIDv7/seq ordering unaffected (revision-based, X.5) |

---

## Part XVI — Testing (the database test suite is a first-class deliverable)

| Suite | Contents | Runs |
|---|---|---|
| **Schema** | Every CHECK/FK/NOT NULL exercised with violating inserts (must fail); enum exhaustiveness matches `06_MEMORY.md` taxonomy programmatically | CI |
| **Migration** | Full chain 0001→HEAD on: empty DB, 1-year corpus, 10-year corpus; checksum immutability; provenance-invariant (XIII.5) asserted by schema diff | CI |
| **Named queries** | Every view/repository query: correctness fixtures + `EXPLAIN QUERY PLAN` regression (no unexpected SCAN) | CI |
| **Performance** | Part XIV budgets on the 10-year synthetic corpus | CI (nightly) |
| **Backup/restore** | Snapshot → verify → restore → equality check; single-record restore; corruption injection (bit-flip a page → detection must fire) | CI (nightly) + live monthly (XII.3) |
| **FTS correctness** | Insert/update/delete trigger sync; private-row exclusion; rebuild equivalence | CI |
| **Vector correctness** | kNN sanity fixtures; version-migration protocol end-to-end (v1→v2 dual-index → cutover) | CI |
| **Crash safety** | Kill -9 during write bursts (harness) → reopen → integrity + event-log replay assertions | CI (nightly) |
| **Cache wipe** | Delete `cache/` mid-operation → zero authoritative loss | CI |

The **synthetic corpus generator** (Memory §13.2) is part of this suite: deterministic seeds produce 1-/5-/10-year databases with realistic distributions (types, links, vault sizes). It is the single most valuable test asset in the project — performance and migration claims are meaningless without it.

---

## Part XVII — Operational Metrics (health panel + `kang doctor`)

| Metric | Source | Alert threshold |
|---|---|---|
| kang.db size / monthly growth | file + trend | growth >2× trailing average |
| Index share of DB size | `dbstat` | informational |
| Fragmentation (freelist pages) | `PRAGMA freelist_count` | >20% → suggest offline VACUUM |
| p50/p99 named-query latency | repository timing | budget × 1.5 |
| Write-queue depth / wait | executor | depth > 100 sustained |
| WAL size | file | > 64 MB (checkpoint starvation) |
| Backup: last success age, duration, verify result | manifest | age > 26 h; verify fail = red |
| Restore-test: last run, result | manifest | > 35 days; fail = red |
| Migration status | schema_version vs shipped | mismatch = startup block |
| Corruption incidents (lifetime counter) | audit | any increment = red until acknowledged |
| Embedding coverage % per version | reconciliation job | < 99% sustained |
| change_log unsynced backlog | table | informational until sync ships |

---

## Part XVIII — Configuration (normative excerpts)

```toml
# config/database.toml
[sqlite]
synchronous   = "NORMAL"      # "FULL" permitted (DB-001 note)
busy_timeout_ms = 5000
read_pool     = 4
cache_kb      = 65536
[write_queue]
max_depth     = 10000
batch_rows    = 1000          # bulk-job chunking (DB-002)

# config/retention.toml       # single source for every purge policy
[db]
model_call_days   = 730
job_run_days      = 365
change_log_days   = 90        # until sync ships
manifest_full_days = 180      # then ids-only (Memory §7.1)
# memory-domain retention lives in memory.toml (06_MEMORY §7.1) — one table, one home

# config/backup.toml
[snapshot]
daily_at   = "02:30"
daily_keep = 30
monthly_keep = 12
verify_monthly = true
external_backup_warn_days = 7

# config/performance.toml     # CI budget mirror (single source for Part XIV numbers)
[budgets_ms]
p0_views = 20
hybrid_candidates = 250
link_depth2 = 10
fts_deep = 100
```

Every constant is a stated starting hypothesis (same posture as Memory Appendix A): **structure is the commitment; constants are tunable with data.**

---

## Appendix A — Derived-data inventory (rebuildable set)

`fts_*` tables · `vec_*` tables · `link_index` · `vault_note`/`vault_chunk` (from vault) · `calendar_cache` (from provider) · `cache/*` · all of these are covered by `kang rebuild-indexes` and excluded from "authoritative loss" accounting.

## Appendix B — Sanctioned CASCADE list

`project → task, milestone` · `competition → deadline` · `conversation → message` · `memory_record → memory_revision` · `vault_note → vault_chunk` · `job → job_run`. Every other FK is RESTRICT or SET NULL. Adding a CASCADE requires editing this appendix (i.e., an ADR).

---

*This document is normative for every component that touches persistence. When code and this document disagree, one of them is wrong on purpose — file the ADR.*
