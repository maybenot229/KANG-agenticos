# tools/lint_doc_citations.py
"""Verifies that every 'NN_DOC §X.Y' citation in docs/ resolves to a real heading.

Scope (v1): numeric-section citations only ('07_DATABASE §5.5', '15 §11.2').
Out of scope: 'Part IX' word-numeral cites, decision IDs (D004, EB-003) —
those are registry-checked concepts, not section anchors.
Exit 1 on any unresolved citation. Allowlist: tools/citation_allowlist.txt.
"""
import re
import sys
from pathlib import Path

DOCS = Path("docs")

# "07_DATABASE §5.5" | "07_DATABASE.md §5.5" | bare "15 §11.2"
CITE = re.compile(r"\b(\d{2})(?:_[A-Z_]+(?:\.md)?)?\s+§(\d+(?:\.\d+)*)")
# headings: "## 5. Title" | "### 5.2 Title" | "## Part V — ..." (skipped)
HEADING = re.compile(r"^#{1,6}\s+(\d+(?:\.\d+)*)[.\s]", re.M)


def load_allowlist() -> set[str]:
    p = Path("tools/citation_allowlist.txt")
    return set(p.read_text().split()) if p.exists() else set()


def headings_by_doc() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for f in DOCS.glob("[0-9][0-9]_*.md"):
        num = f.name[:2]
        sections = set(HEADING.findall(f.read_text(encoding="utf-8")))
        # §5.2 also satisfied by parent §5 existing? No — require exact,
        # but accept prefix match when the doc uses '### 5.2' style.
        out[num] = sections
    return out


def main() -> int:
    allow = load_allowlist()
    docs = headings_by_doc()
    failures = []
    for f in DOCS.glob("*.md"):
        text = f.read_text(encoding="utf-8")
        for m in CITE.finditer(text):
            doc, sec = m.group(1), m.group(2)
            key = f"{doc}:{sec}"
            if key in allow:
                continue
            if doc not in docs:
                failures.append(f"{f.name}: cites doc {doc} — no such document")
            elif sec not in docs[doc]:
                failures.append(f"{f.name}: cites {doc} §{sec} — heading not found")
    for line in failures:
        print(f"CITATION: {line}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())