# ADR-003: goal.horizon does not gain a '5yr' enum value

**Status:** accepted
**Date:** 2026-07-19

## Context

`07_DATABASE.md`'s `goal` table has `horizon CHECK IN ('quarter','year','life')`.
The user-profile intake (docs/guides/user-profile-intake-2026-07.md) surfaces
a 5-year lead goal — NUS admission — as a forced-choice answer during
interview. The intake's own language describes it as: "kinda my aim rn but
idk," "still figuring it out," explicitly a **candidate**, not a commitment.

## Options

(a) Add `'5yr'` to the `horizon` CHECK enum — widens frozen schema to fit
    the new data point.
(b) Model it as a `'year'`-horizon goal with a target date ~5 years out —
    reuses the existing enum, stretches its semantic meaning.
(c) Do not seed it structurally at all. The 5-year candidate stays in the
    vault (Kang's authored note) and the guide (docs/guides/...), cited but
    not persisted as a `goal` row, until it becomes a real commitment.

## Decision

**(c).** The `goal` table is structured, decided state (07_DATABASE §1.4:
"deterministic state is sacred... exact queries only"). This intake item is,
by its own author's words, explicitly undecided. Seeding a tentative
aspiration into a frozen schema now is the same anti-pattern the roadmap
already names elsewhere: building structure ahead of real need (03_ROADMAP
§1.3 — "infrastructure precedes its consumer by exactly one phase, never
more"). Here the "phase" is Kang's own decision-making, which hasn't
happened yet.

## Consequences

- `goal` table seeds only `quarter` and `year` rows from the intake for now.
- The 5-year candidate remains visible via the guide → vault chain, so it
  isn't lost, just not falsely promoted to committed state.
- When Kang actually commits to a 5-year horizon (explicit statement, not a
  forced-ranking answer), re-open this ADR's decision: at that point, option
  (a) (widen the enum) is likely correct, since by then it's a genuine
  decided fact deserving structured storage.
- `life` horizon stays empty in the `goal` table per the intake's own
  Part F item 1 — same reasoning, one level further out.

## Trigger for revisiting

Kang states a 5-year goal as decided (not "idk," not a forced-choice
artifact) — likely surfacing in a future intake round or a direct statement
in chat. When that happens: file a new ADR (don't reopen this one — append,
never rewrite, per 14_CLAUDE §8.7), widen the enum, migrate.
