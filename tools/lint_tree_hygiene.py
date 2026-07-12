"""Tree-hygiene linter — enforces PS-002 (17_PROJECT_STRUCTURE §1.3).

The repository holds zero runtime state and zero secrets. This linter fails
on: database files (*.db and WAL sidecars), runtime log/audit patterns
(*.jsonl), .env files, and secret-shaped strings in text files (extends the
11 §25 banned list to the tree, as 17 §1.3 mandates).

Dev-only tool; imports nothing from src/ (17 §4.2).
Usage: python tools/lint_tree_hygiene.py [repo_root]   (default: .)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

BANNED_FILE_PATTERNS = ("*.db", "*.db-wal", "*.db-shm", "*.sqlite", "*.jsonl", ".env")
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    "build",
    "dist",
}
TEXT_SUFFIXES = {
    ".py",
    ".toml",
    ".md",
    ".sql",
    ".yml",
    ".yaml",
    ".json",
    ".ts",
    ".tsx",
    ".cfg",
    ".ini",
    ".txt",
}

SECRET_PATTERNS = [
    ("Anthropic key", re.compile(r"sk-ant-[A-Za-z0-9-]{8,}")),
    ("OpenAI-style key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("AWS key id", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    (
        "assigned secret literal",
        re.compile(
            r"(api_key|apikey|secret|password|token)\s*[:=]\s*['\"][^'\"\s]{12,}['\"]",
            re.IGNORECASE,
        ),
    ),
]


def _iter_files(root: Path):
    for path in sorted(root.rglob("*")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.is_file():
            yield path


def check_tree(root: Path) -> list[str]:
    failures: list[str] = []
    for path in _iter_files(root):
        for pattern in BANNED_FILE_PATTERNS:
            if path.match(pattern):
                failures.append(f"{path}: runtime-state file in the repo (PS-002)")
        if path.suffix.lower() in TEXT_SUFFIXES:
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for name, regex in SECRET_PATTERNS:
                for match in regex.finditer(text):
                    line = text.count("\n", 0, match.start()) + 1
                    failures.append(f"{path}:{line}: secret pattern ({name})")
    return failures


def main(argv: list[str]) -> int:
    root = Path(argv[0]) if argv else Path(".")
    failures = check_tree(root)
    for f in failures:
        print(f"HYGIENE: {f}")
    print(f"lint_tree_hygiene: {len(failures)} violation(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
