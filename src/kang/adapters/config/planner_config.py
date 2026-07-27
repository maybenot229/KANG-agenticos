"""kang.toml loader — the Planner's real trigger times.

Layer: adapters/config (TOML parsing is I/O at the boundary).
Constitutional home: 04_ARCHITECTURE D003 (config is TOML, diffable,
hand-editable in recovery), 17 §8 (`config/defaults/` ships them; runtime
truth is `%KANG_HOME%/config/`), 05_AGENTS Appendix E (trigger times are
config, not spec — grounded in Kang's actual routine per
`docs/guides/user-profile-intake-2026-07.md`, not placeholders).

The shipped defaults are 05:45 on the six school days, 06:45 Sunday. This
loader reads them; it never hardcodes them, so changing the routine is a
config edit and not a code change — which is the whole point of Appendix E's
"config, not spec".
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

__all__ = ["PlannerTriggers", "PlannerConfigError", "load_planner_triggers"]

# Python's date.weekday(): Monday is 0, Sunday is 6.
_SATURDAY = 5
_SUNDAY = 6


class PlannerConfigError(Exception):
    """kang.toml is missing or malformed. Fail fast at startup (11 §10) —
    never silently substitute an invented time, because a wrong morning
    trigger is a plan Kang never sees."""


@dataclass(frozen=True)
class PlannerTriggers:
    """The `[planner.triggers]` block that governs when a plan is due."""

    weekday_morning: str
    saturday_morning: str
    sunday_morning: str
    catch_up_policy: str
    timezone: str

    def morning_cron(self) -> str:
        """The morning brief as a `cron:` schedule (ADR-006).

        Two expressions, because standard cron cannot say "05:45 Mon–Sat but
        06:45 Sun" in one — and one job row, because splitting the ritual in
        two would give it two independent catch-up baselines and generate the
        plan twice after downtime spanning Saturday into Sunday.

        Cron day-of-week: 0 = Sunday, so 1-6 is Monday–Saturday. Saturday is
        a school day; the week has no gap.
        """
        weekday_h, weekday_m = self.weekday_morning.split(":")
        saturday_h, saturday_m = self.saturday_morning.split(":")
        sunday_h, sunday_m = self.sunday_morning.split(":")
        if (weekday_h, weekday_m) == (saturday_h, saturday_m):
            school = f"{int(weekday_m)} {int(weekday_h)} * * 1-6"
        else:
            # They are equal in the shipped config, but that is a fact about
            # Kang's routine rather than a rule — keep them separable.
            school = (
                f"{int(weekday_m)} {int(weekday_h)} * * 1-5"
                f" | {int(saturday_m)} {int(saturday_h)} * * 6"
            )
        return f"cron:{school} | {int(sunday_m)} {int(sunday_h)} * * 0"

    def morning_for(self, day: date) -> str:
        """The morning-brief time for a given day.

        Saturday has its own key rather than folding into `weekday_morning`
        even though both are currently 05:45: Saturday is a school day for
        Kang (the intake is explicit that his week has no real weekend), so
        the two being equal today is a fact about his routine, not a rule.
        Collapsing them would silently couple two independently-changing
        values.
        """
        if day.weekday() == _SUNDAY:
            return self.sunday_morning
        if day.weekday() == _SATURDAY:
            return self.saturday_morning
        return self.weekday_morning


def parse_planner_triggers(toml_text: str) -> PlannerTriggers:
    """Parse `[planner.triggers]`. Raises PlannerConfigError on anything
    missing — there are no defaults here, because a default would be an
    invented time (05 Appendix E)."""
    try:
        data = tomllib.loads(toml_text)
    except tomllib.TOMLDecodeError as exc:
        raise PlannerConfigError(f"kang.toml is not valid TOML: {exc}") from exc
    triggers = data.get("planner", {}).get("triggers")
    if not isinstance(triggers, dict):
        raise PlannerConfigError("kang.toml is missing [planner.triggers]")
    required = (
        "weekday_morning",
        "saturday_morning",
        "sunday_morning",
        "catch_up_policy",
    )
    missing = [key for key in required if key not in triggers]
    if missing:
        raise PlannerConfigError(f"[planner.triggers] is missing {missing}")
    # Top-level, not under [planner]: the timezone governs every wall-clock
    # schedule, not just the Planner's (ADR-006).
    zone = data.get("timezone")
    if not isinstance(zone, str) or not zone:
        raise PlannerConfigError(
            "kang.toml is missing a top-level `timezone` — a cron schedule "
            "without one fires at a time nobody chose (ADR-006)"
        )
    values = {key: triggers[key] for key in required}
    return PlannerTriggers(timezone=zone, **values)


def load_planner_triggers(path: Path) -> PlannerTriggers:
    """Load trigger truth from `path` (%KANG_HOME%/config/kang.toml)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PlannerConfigError(f"kang.toml unreadable at {path}: {exc}") from exc
    return parse_planner_triggers(text)
