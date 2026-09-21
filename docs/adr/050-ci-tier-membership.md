# ADR-050 — CI tier membership: the marker is the cadence authority, the directory stays the suite-class authority

**Status:** accepted (2026-09-21) — Kang's own "accept it", same session as drafting; Options 1B / 2B / 3B as recommended, D1–D5 accepted as written. Drafted after ADR-049's implementing session recorded a three-way disagreement it could not resolve alone. **Not yet implemented** — implementation is delegated to a separate coding session; its build brief is `docs/guides/session-2026-09-21-adr050-build-brief.md`.
**Date:** 2026-09-21
**Supersedes:** none
**Affected documents (if accepted):** `17_PROJECT_STRUCTURE.md` §11.2 (a dated amendment: the sentence "cadence markers by CI config" is made precise — a cadence marker is a pytest marker *in the test*, which CI selects on; the tree states what is proven **and how expensive it is**, CI states when, D1); `13_TESTING.md` §3 (the Weekly row's "migration chain on corpus" moves to Nightly, D2; a dated note that Weekly and Monthly remain unbuilt tiers, D3) and §4 gate 1 (its "including the most recent weekly" clause gains a dated qualifier while no weekly tier exists, D3); `docs/adr/049-synthetic-corpus-generator.md` D3 (a dated "Corrected by ADR-050" note: its table's "merge (integration)" tier column for `year1` was wrong at implementation time and is wrong now — `year1` runs at the commit tier, D4); `.github/workflows/ci.yml` and `pyproject.toml` (marker registry and selection expressions — tooling config, not constitutional)
**Cites:** 17_PROJECT_STRUCTURE §11.1 ("`tests/` mirrors and maps; it never invents structure of its own"), §11.2 (the sentence this ADR makes precise, `docs/17_PROJECT_STRUCTURE.md:416`), §16/PS-006 (reservations are registry entries, never empty directories — why no empty Weekly job is created, D3), §1.2 (determinism: placement follows rules, not taste); 13_TESTING §2 (the seventeen suite classes the directories are named for), §3 (the five-tier table and its budgets, `docs/13_TESTING.md:134-140`), §4 (the nine release gates; gate 1 names Weekly, gate 6 names 90% budget utilization), §1.4 (deterministic always; a flaky test is quarantined within 24h — the marker vocabulary is also how a quarantine is expressed later); ADR-049 D3/D5 (the tier placement this ADR corrects and completes), ADR-049's own Verification paragraph (the implementing session's recorded finding); 11_CODING §3 ("one concept, one name, everywhere"), §24 ("CI config changes are reviewed like code"); 03_ROADMAP §8 (the RESERVED registry that Weekly/Monthly tiers join)
**Related:** [[049-synthetic-corpus-generator.md]], [[048-memory-truth-schema.md]]

---

## Context

ADR-049 landed the synthetic corpus, the first `nightly`-marked suites, and the first scheduled CI job. Its implementing session reported, honestly and without resolving it, that the tier placement of those suites is stated three different ways. Verified against the real repository and a real run on 2026-09-21, not taken from that report:

**The three statements.**
1. **ADR-049 D3's own table** puts the `year1` profile in the "merge (integration)" tier.
2. **ADR-049 D5 and the implementation** put the suites under `tests/suites/migration/` and `tests/suites/performance/`, and CI's commit-tier job runs `pytest tests/unit tests/suites` — so `year1` runs at the **commit** tier, two tiers earlier than D3's table says.
3. **13_TESTING §3's tier table** assigns "migration chain on corpus" to the **Weekly** tier and "performance budgets on 10-yr corpus" to **Nightly**. The implementation put both at Nightly.

Today's placement is the strictest of the three, so nothing is under-tested and no claim in `CLAIMS.md` is false. But three documents disagreeing about when a suite runs is exactly the drift this project treats as a bug with an owner (11 §8), and the next suite to land in a cadence-mixed directory will re-open the same argument.

**The underlying mechanism problem, which is the real subject of this ADR.** 17 §11.2 already rules: *"Suite membership is by directory, cadence markers by CI config — the tree states what is proven, CI states when."* Under that sentence, CI selects a cadence by **path**. That worked while every directory held tests of one cost. `tests/suites/migration/` is the first directory whose contents span two cadences — the `year1` chain (seconds, every push) and the `year10` chain (minutes, nightly) — and **no path expression can separate them**. ADR-049 therefore put the cadence into the test files as pytest markers, which is the tree stating *when*. That is a departure from 17 §11.2's letter, and it was not named as one.

**Two marker mechanisms are already in use**, found by reading the tree rather than the report: a module-level `pytestmark = pytest.mark.nightly` in `tests/suites/performance/test_budgets_on_corpus.py:36`, and a per-parameter `pytest.param("corpus_year10", marks=pytest.mark.nightly)` in `tests/suites/migration/test_chain_on_corpus.py:30`. Both are ordinary pytest markers; the second is what lets one parametrized test body serve two cadences, and it is the shape every future cadence-mixed suite will need.

**Two further facts the tier table asserts and the repository does not have.** `ci.yml` has four jobs — `commit-tier`, `integration`, `nightly`, `ui` — and no Weekly or Monthly tier; the suites those tiers would run (injection red-team, corruption drills, stress) do not exist and are Phase 3+ work. Meanwhile 13 §4's release gate 1 requires "All tiers green, **including the most recent weekly**" — a gate that cannot be satisfied, and cannot be honestly waived, while no weekly tier exists. Seven of 17 §11's fifteen suite directories are likewise absent, which is correct and deliberate (PS-006: reservations are registry entries, never empty directories) — the tiers should follow the same rule, and the gate should say so.

**Measured, so the decision is grounded** (this machine, 2026-09-21): the commit tier runs 874 tests in 280 s against 13 §3's < 5 min budget; the same 837 pre-corpus tests took 239 s in that run and 172 s earlier the same day, a ~39% swing from machine state alone. The corpus's own added cost is ~41–46 s. The nightly suite runs 15 tests in 506 s. So commit-tier headroom is real but thin, and it is dominated by machine variance rather than by this slice — a fact that matters for D1's cost, not for its direction.

**What is settled and not re-decided here:** the seventeen suite classes and their directory names (13 §2, 17 §11); that `tests/` never invents structure of its own (17 §11.1); the budgets themselves (13 §3, 07 Part XIV); that CI config is reviewed like code (11 §24); and everything ADR-049 decided about the corpus itself.

---

## Options

### Option 1 — How a test's cadence is expressed

**1A — Path only: CI selects directories, and a cadence-mixed suite is split by making the *data* a CI-supplied parameter.** `tests/suites/performance/` is nightly by nature, so the nightly job names that path; `tests/suites/migration/` runs at both cadences with the corpus profile chosen by a pytest CLI option (`--corpus-profile=year10`) that CI passes.
- *For:* 17 §11.2 survives untouched — the tree states only what is proven, CI states when and at what size. No marker vocabulary to maintain.
- *Against:* it is true only for suites whose cost difference is *data volume*. It fails the moment a single expensive test sits beside cheap ones for a reason that is not data — the weekly injection red-team (13 §2.9) will live in `security/` beside fast scrubber tests; the weekly corruption drills (13 §2.14) will live in `recovery/` beside fast F-code assertions. Those are coming, and 17 §11.1 forbids inventing `security_weekly/` to hold them. It also hides cost from the reader: nothing in the test file says "this one takes eight minutes," so the expensive test is invisible until CI is slow.

**1B — The marker is the cadence authority; the directory stays the suite-class authority. (Recommended.)** A test's *class* is its directory (unchanged, 17 §11.1). A test's *cadence* is a registered pytest marker on the test, the module, or the parameter: `nightly`, `weekly`, `monthly`. Unmarked means the default tier for its path — commit for `tests/unit`+`tests/suites`, merge for `tests/integration` — which is exactly today's behavior for all 1,198 existing tests. CI selects by marker, never by path, for the scheduled tiers.
- *For:* one mechanism that scales to every reason a test is expensive, not just data volume; cost is declared where the cost lives, so a reader of the file knows; `--strict-markers` (already on) makes a typo a red build rather than a silently-never-run test; it generalizes the mechanism ADR-049 already built rather than replacing it, so the change is small; and it gives the flaky-quarantine vocabulary 13 §1.4 will need a home later.
- *Against:* 17 §11.2's sentence needs a dated amendment — the tree now states *how expensive* a test is as well as *what it proves*. That is a real widening of the tree's job, and it must be written down rather than absorbed. A marker can also drift from reality (a test marked `nightly` that became fast stays nightly), which no lint catches; accepted, because the reverse failure under 1A — an expensive test silently landing in the commit tier — is the one that actually hurts, and it is caught by the tier budget.

**1C — Keep both mechanisms and document the precedence.** *For:* zero change. *Against:* two ways to say one thing is the defect 11 §3 names outright; the next contributor picks whichever they see first. Rejected on the project's own rule.

### Option 2 — Where "migration chain on corpus" runs

**2A — Weekly, exactly as 13 §3's table says.** *For:* the document is the law; no amendment needed. *Against:* the assertion is one chain application, but the fixture it needs is a 350,000-chunk corpus that takes minutes to build. A weekly job would rebuild that corpus for a single test, while the nightly job already has it built and sitting in `tmp_path_factory`. That is paying a multi-minute build, once a week, to run something later than it could run for free.

**2B — Nightly; amend 13 §3's Weekly row. (Recommended.)** *For:* the corpus fixture is already built in the nightly tier for the performance budgets, so the chain assertion is nearly free there; running it daily rather than weekly is strictly stricter, and 13 §3's own budget for Nightly (< 2 h) has ample room at the measured 506 s. *Against:* a constitutional table is edited to match an implementation, which is the direction this project is most suspicious of — mitigated by the fact that the reason is a real cost argument, stated here, not a convenience.

### Option 3 — Whether Weekly and Monthly CI jobs are created now

**3A — Create them now, empty or near-empty, so 13 §4 gate 1 is literally satisfiable.** *For:* the gate stops referring to something that does not exist. *Against:* PS-006's exact anti-pattern one layer up — a scheduled job that runs nothing is speculative structure that invites content ("well, the job exists") and misstates the present. It would also be a green tier that proves nothing, which is worse than an absent one.

**3B — Keep them RESERVED with a trigger; qualify gate 1 while they do not exist. (Recommended.)** *For:* matches how this project already handles unbuilt suite directories and every other reservation; the gate becomes honestly satisfiable instead of permanently, silently failed. *Against:* a release gate's wording is weakened, which must be explicit and dated rather than quietly reinterpreted — hence D3 writing the trigger down.

---

## Decision

### D1 — The marker is the cadence authority; the directory stays the suite-class authority (Option 1B)

Registered cadence markers: `nightly`, `weekly`, `monthly`. A test carries at most one, on the test, the module (`pytestmark`), or a single parameter (`pytest.param(..., marks=...)`) — all three are the same mechanism and all three are legal; the parametrized form is what lets one body serve two cadences and is expected to be the common case for corpus-scaled suites. **Absent means the default tier for the test's path**: commit for `tests/unit` and `tests/suites`, merge for `tests/integration`. This is exactly today's behavior for every existing test, so nothing is re-marked.

CI selects by marker for every scheduled tier and never by path:

| Job | Selection |
|---|---|
| commit-tier | `pytest tests/unit tests/suites -m "not (nightly or weekly or monthly)"` |
| integration | `pytest tests/integration -m "not (nightly or weekly or monthly)"` |
| nightly | `pytest -m nightly` |
| weekly | RESERVED (D3) — would be `pytest -m weekly` |
| monthly | RESERVED (D3) — would be `pytest -m monthly` |

`--strict-markers` stays on, and all three markers are registered in `pyproject.toml` from this ADR forward — including `weekly` and `monthly`, which no test carries yet. Registering a marker is not creating a tier: the marker is vocabulary, and registering it now means the first weekly-shaped test can declare itself honestly instead of being silently commit-tier until someone notices.

17 §11.2's sentence gets a dated amendment making this precise: **the tree states what is proven and how expensive it is; CI states when.**

### D2 — "Migration chain on corpus" runs Nightly (Option 2B)

13 §3's Weekly row loses "migration chain on corpus"; the Nightly row gains it, with a dated note giving the reason: the nightly tier already builds the `year10` corpus for the performance budgets, so the chain assertion rides a fixture that exists rather than forcing a weekly rebuild of it. No test moves — this amends the document to match a placement that was already the stricter one.

### D3 — Weekly and Monthly stay RESERVED, and release gate 1 says so

No Weekly or Monthly CI job is created. Both join 03_ROADMAP §8's RESERVED registry with an explicit trigger: **the first test that carries the corresponding marker.** Their suites are Phase 3+ work (injection red-team arrives with the first Tier-0-input agent, 18 §4; corruption drills and the stress suite likewise), and a scheduled job that runs nothing is PS-006's anti-pattern one layer up.

13 §4's gate 1 — "All tiers green, including the most recent weekly" — gains a dated qualifier: *all tiers that exist*, and the Weekly clause activates with the weekly tier. This is a real, dated weakening of a release gate's wording and is recorded as such rather than reinterpreted silently at release time.

### D4 — ADR-049 D3's tier column is corrected, not quietly left wrong

ADR-049's D3 table names "merge (integration)" as `year1`'s tier. That was already false when it was written and is false now: `year1` runs at the commit tier, because the suites live under `tests/suites/` and D5 put them there. A dated "Corrected by ADR-050" note lands on that table — the same discipline ADR-038/040/041 used for their own found errors. No other ADR-049 text is touched, and the placement itself does not change: commit tier is where `year1` stays, at a measured ~41–46 s.

### D5 — What this ADR does not do

No test moves directory. No test changes cadence except by the documents catching up to it. No Weekly or Monthly job. No new suite directory. No change to any budget number. No lint enforcing marker-to-runtime correspondence (a `nightly` test that became fast is not a red build — named, not built; if marker drift ever bites, that lint is its own small ADR).

---

## Consequences

**Easier.** One mechanism answers "when does this run?", and it answers it in the file the reader already has open. A cadence-mixed suite needs no new directory, which keeps 17 §11.1 intact as more suites land. The first weekly-shaped test can declare itself the day it is written rather than waiting for a tier to exist. Release gate 1 becomes satisfiable and honest at the same time.

**Harder, or a cost.** The tree now carries cost information, which 17 §11.2 previously reserved to CI — a real widening, dated. A marker can go stale and nothing catches it. Registering `weekly` and `monthly` before any test uses them is a small, deliberate exception to this project's habit of not naming what does not exist; it is vocabulary rather than structure, and the alternative (the first weekly test silently running on every push) is worse. And a release gate's wording is weakened while a tier is missing, which is the kind of thing that must be re-read at every version boundary rather than assumed handled — 03 §9's ritual is where that re-reading happens.

**Named, not decided here:** a marker-drift lint; whether the commit tier's thin headroom (280 s measured against a 300 s budget, dominated by machine variance rather than by any one suite) deserves its own budget test the way 07 Part XIV's are tested — today no test asserts 13 §3's tier budgets at all, which is a real gap this ADR deliberately does not close; and whether `tests/integration` should itself be marker-selected into commit and merge portions rather than running whole at merge.

## Verification

**Not yet implemented.** What would prove this ADR: `pyproject.toml` registering all three markers under `--strict-markers`; `ci.yml`'s four jobs selecting exactly as D1's table says, with the commit and merge jobs deselecting all three markers rather than only `nightly`; a test asserting that every registered cadence marker is either selected by some CI job or explicitly RESERVED (so a fourth marker cannot be added without a job or a registry line); the full suite unchanged in count and outcome, since no test moves or changes cadence; and the four dated document amendments (17 §11.2, 13 §3, 13 §4 gate 1, ADR-049 D3) landing in the same commit as the config change.
