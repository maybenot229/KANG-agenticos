# tools/lint_doc_citations.py
# DEBT(#TBD): DOCS.glob("*.md") is non-recursive and won't scan docs/guides/
# or docs/adr/ for §-style citations. Not triggered by any current guide or
# ADR (both are cited by path only, not by internal section number, as of
# this writing). Fix when a doc first cites a numbered section inside a
# guide or ADR. Issue number is a placeholder — 11_CODING §26 requires a
# real filed issue (cost/interest/payoff-trigger stated there, not just
# here); flagging rather than inventing one, since opening it isn't mine to
# do without asking.
"""Verifies that every 'NN_DOC §X.Y' citation in docs/ resolves to a real heading.

Scope (v1): numeric-section citations only ('07_DATABASE §5.5', '15 §11.2').
Out of scope: 'Part IX'/'Part X' word-numeral cites, decision IDs (D004,
EB-003) — those are registry-checked concepts, not section anchors. Prefer
Part-numeral or Decision-ID citations over plain §-numbers when citing content
that has both, since decimal sections renumber under document restructuring
and Part/Decision identifiers don't (see docs/INDEX.md §2.2's numbering-
stability rationale, generalized to sub-document citations).
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