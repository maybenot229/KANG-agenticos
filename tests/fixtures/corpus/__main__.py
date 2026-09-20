"""`python -m tests.fixtures.corpus <year1|year5|year10> <out.db> [--seed N]
[--fraction F]` — the same artifact the suites use, for hands-on inspection.
Prints the report as JSON. Refuses an out path inside the repository (PS-002).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .generate import assert_outside_repo, generate
from .profiles import PROFILES


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.fixtures.corpus")
    parser.add_argument("profile", choices=sorted(PROFILES))
    parser.add_argument("out", type=Path)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--fraction", type=float, default=1.0)
    args = parser.parse_args(argv)
    try:
        assert_outside_repo(args.out)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    report = generate(
        PROFILES[args.profile], args.out, seed=args.seed, fraction=args.fraction
    )
    print(report.to_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
