"""Banned-pattern linter — enforces the mechanical subset of 11_CODING §25.

Patterns caught here (each a named rot vector):
- print() in src (11 §6) — structured logging exists for a reason
- TODO markers (11 §8) — the allowed markers are DEBT(#issue) / RESERVED(trigger)
- datetime.now()/utcnow() outside the clock adapter (11 §14 — injected clock)
- os.environ outside adapters/config (11 §10 — the config module exception)
- bare `except:` (11 §9)
- eval()/exec() outside the plugin host (SEC-005)
- SQL outside adapters/sqlite (DB-002 — SQL lives in the store layer only)

Deliberately regex-simple: this is the commit-tier tripwire; ruff and review
carry the rest. Dev-only tool; imports nothing from src/ (17 §4.2).
Usage: python tools/lint_banned_patterns.py [src_dir]   (default: src)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SQL_RE = re.compile(
    r"\b(SELECT\s+.+?\s+FROM\s|INSERT\s+INTO\s|UPDATE\s+\w+\s+SET\s"
    r"|DELETE\s+FROM\s|CREATE\s+TABLE\s|DROP\s+TABLE\s)",
    re.IGNORECASE,
)

# (name, regex, path-prefixes exempt from the rule)
RULES: list[tuple[str, re.Pattern[str], tuple[str, ...]]] = [
    ("print in src (11 §6)", re.compile(r"(?<![\w.])print\("), ()),
    ("TODO marker (11 §8: use DEBT(#) or RESERVED())", re.compile(r"\bTODO\b"), ()),
    (
        "wall clock outside clock adapter (11 §14)",
        re.compile(r"datetime\.(now|utcnow)\(|time\.time\(\)"),
        ("kang/adapters/os_windows", "kang/kernel/runtime/structured_logging"),
    ),
    (
        "os.environ outside config adapter (11 §10)",
        re.compile(r"os\.environ|os\.getenv"),
        ("kang/adapters/config",),
    ),
    ("bare except (11 §9)", re.compile(r"except\s*:"), ()),
    (
        "eval/exec outside plugin host (SEC-005)",
        re.compile(r"(?<![\w.])(eval|exec)\("),
        ("kang/kernel/plugin_host",),
    ),
    (
        "SQL outside the store layer (DB-002)",
        re.compile(SQL_RE.pattern, re.IGNORECASE),
        ("kang/adapters/sqlite", "kang/adapters/eventlog"),
    ),
]


def _exempt(rel: str, prefixes: tuple[str, ...]) -> bool:
    return any(rel.startswith(p) for p in prefixes)


def check_file(path: Path, rel: str) -> list[str]:
    failures: list[str] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for name, pattern, exemptions in RULES:
            if _exempt(rel, exemptions):
                continue
            if pattern.search(line):
                failures.append(f"{path}:{lineno}: {name}: {stripped[:80]}")
    return failures


def main(argv: list[str]) -> int:
    src = Path(argv[0]) if argv else Path("src")
    failures: list[str] = []
    for path in sorted(src.rglob("*.py")):
        rel = path.relative_to(src).as_posix()
        failures.extend(check_file(path, rel))
    for f in failures:
        print(f"BANNED: {f}")
    print(f"lint_banned_patterns: {len(failures)} violation(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
