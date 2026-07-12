"""Generate root-level pointer artifacts from their sources of truth.

Constitutional home: 14_CLAUDE.md header ("A copy of this file MUST live at
the repository root as CLAUDE.md ... the root copy is generated from this one
— one source of truth, never edit the copy") and 17_PROJECT_STRUCTURE §12
(root files are pointers or generated copies; generated artifacts are never
hand-edited).

Dev-only tool: imports nothing from src/ (17 §4.2).
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE = REPO_ROOT / "docs" / "14_CLAUDE.md"
TARGET = REPO_ROOT / "CLAUDE.md"

BANNER = (
    "<!-- GENERATED FILE — DO NOT EDIT. Source of truth: docs/14_CLAUDE.md. -->\n"
    "<!-- Regenerate with: python tools/build_root_docs.py -->\n\n"
)


def build() -> None:
    TARGET.write_text(BANNER + SOURCE.read_text(encoding="utf-8"), encoding="utf-8")


def check() -> bool:
    """Return True when the root copy matches its source (CI mode)."""
    expected = BANNER + SOURCE.read_text(encoding="utf-8")
    return TARGET.exists() and TARGET.read_text(encoding="utf-8") == expected


if __name__ == "__main__":
    if "--check" in sys.argv:
        if check():
            print("CLAUDE.md is current.")
            sys.exit(0)
        print("CLAUDE.md is stale or hand-edited; run: python tools/build_root_docs.py")
        sys.exit(1)
    build()
    print(f"Wrote {TARGET}")
