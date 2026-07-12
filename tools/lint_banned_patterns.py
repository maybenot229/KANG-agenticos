"""Banned-pattern linter — enforces the mechanical subset of 11_CODING §25.

Patterns caught (each a named rot vector):
- print() in src (11 §6) — structured logging exists for a reason
- TODO markers (11 §8) — the allowed markers are DEBT(#issue) / RESERVED(trigger)
- datetime.now()/utcnow()/time.time() outside the clock adapter (11 §14)
- os.environ outside adapters/config (11 §10 — the config-module exception)
- bare `except:` (11 §9)
- eval()/exec() outside the plugin host (SEC-005)
- SQL outside adapters/sqlite + adapters/eventlog (DB-002)

Token-aware: code rules skip strings/comments (docstrings may *cite* the
bans); the SQL rule scans string literals (SQL lives in strings), skipping
docstrings; the TODO rule scans comments and strings. Dev-only tool;
imports nothing from src/ (17 §4.2).
Usage: python tools/lint_banned_patterns.py [src_dir]   (default: src)
"""

from __future__ import annotations

import io
import re
import sys
import tokenize
from pathlib import Path

CODE_RULES: list[tuple[str, re.Pattern[str], tuple[str, ...]]] = [
    ("print in src (11 §6)", re.compile(r"(?<![\w.])print\($"), ()),
    (
        "wall clock outside clock adapter (11 §14)",
        re.compile(r"datetime\.(now|utcnow)\($|time\.time\($"),
        ("kang/adapters/os_windows",),  # the future SystemClock's home
    ),
    (
        "os.environ outside config adapter (11 §10)",
        re.compile(r"os\.(environ|getenv)$"),
        ("kang/adapters/config",),
    ),
    ("bare except (11 §9)", re.compile(r"(?<!\w)except:$"), ()),
    (
        "eval/exec outside plugin host (SEC-005)",
        re.compile(r"(?<![\w.])(eval|exec)\($"),
        ("kang/kernel/plugin_host",),
    ),
]

SQL_RE = re.compile(
    r"\b(SELECT\s+.+?\s+FROM\s|INSERT\s+INTO\s|UPDATE\s+\w+\s+SET\s"
    r"|DELETE\s+FROM\s|CREATE\s+TABLE\s|DROP\s+TABLE\s)",
    re.IGNORECASE | re.DOTALL,
)
SQL_EXEMPT = ("kang/adapters/sqlite", "kang/adapters/eventlog")

TODO_RE = re.compile(r"\bTODO\b")


def _exempt(rel: str, prefixes: tuple[str, ...]) -> bool:
    return any(rel.startswith(p) for p in prefixes)


def _code_stream_findings(rel: str, tokens: list[tokenize.TokenInfo]) -> list[str]:
    """Run code rules over sliding joins of non-string, non-comment tokens.

    Each rule's regex is end-anchored ($) so a window matches exactly when
    its final token completes the banned construct — one finding per site."""
    findings: list[str] = []
    code = [
        t
        for t in tokens
        if t.type not in (tokenize.STRING, tokenize.COMMENT, tokenize.NL)
    ]
    seen: set[tuple[int, str]] = set()
    for index, token in enumerate(code):
        window = "".join(t.string for t in code[max(0, index - 5) : index + 1])
        line = token.start[0]
        for name, pattern, exemptions in CODE_RULES:
            if _exempt(rel, exemptions):
                continue
            if pattern.search(window) and (line, name) not in seen:
                seen.add((line, name))
                findings.append(f"{line}: {name}")
    return findings


def check_file(path: Path, rel: str) -> list[str]:
    source = path.read_text(encoding="utf-8")
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except tokenize.TokenizeError:
        return [f"{path}:1: unparseable file"]
    failures = [f"{path}:{f}" for f in _code_stream_findings(rel, tokens)]

    previous_type: int | None = None
    for token in tokens:
        if token.type == tokenize.STRING:
            is_docstring = previous_type in (
                None,
                tokenize.NEWLINE,
                tokenize.INDENT,
                tokenize.DEDENT,
                tokenize.ENCODING,
            )
            if (
                not is_docstring
                and not _exempt(rel, SQL_EXEMPT)
                and SQL_RE.search(token.string)
            ):
                failures.append(
                    f"{path}:{token.start[0]}: SQL outside the store layer (DB-002)"
                )
            if TODO_RE.search(token.string):
                failures.append(f"{path}:{token.start[0]}: TODO marker (11 §8)")
        elif token.type == tokenize.COMMENT:
            if TODO_RE.search(token.string):
                failures.append(f"{path}:{token.start[0]}: TODO marker (11 §8)")
        if token.type not in (tokenize.NL, tokenize.COMMENT):
            previous_type = token.type
    return failures


def main(argv: list[str]) -> int:
    src = Path(argv[0]) if argv else Path("src")
    failures: list[str] = []
    for path in sorted(src.rglob("*.py")):
        rel = path.relative_to(src).as_posix()
        failures.extend(check_file(path, rel))
    for failure in failures:
        print(f"BANNED: {failure}")
    print(f"lint_banned_patterns: {len(failures)} violation(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
