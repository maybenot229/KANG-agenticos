"""Size-limit linter — enforces 11_CODING_STANDARDS §4.

Hard limits (CI fail): function 80 lines, class 400, file/module 800,
parameters 6. Soft limits are reported as warnings: 40 / 200 / 400 / 4.
Hard-limit exceptions require an inline justification naming an ADR or
reason (11 §4) — this linter recognizes none yet; the first exception adds
the mechanism in the same PR.

Dev-only tool: parses source as text/AST, imports nothing from src/ (17 §4.2).
Usage: python tools/lint_sizes.py [target_dir ...]   (default: src)
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

HARD_FUNCTION_LINES = 80
HARD_CLASS_LINES = 400
HARD_FILE_LINES = 800
HARD_PARAMS = 6
SOFT_FUNCTION_LINES = 40
SOFT_CLASS_LINES = 200
SOFT_FILE_LINES = 400
SOFT_PARAMS = 4


@dataclass
class Finding:
    path: Path
    line: int
    message: str
    hard: bool


def _node_lines(node: ast.AST) -> int:
    return (node.end_lineno or node.lineno) - node.lineno + 1


def _param_count(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    a = node.args
    count = len(a.posonlyargs) + len(a.args) + len(a.kwonlyargs)
    params = a.posonlyargs + a.args
    if params and params[0].arg in ("self", "cls"):
        count -= 1
    return count


def _check_node(path: Path, node: ast.AST, findings: list[Finding]) -> None:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        lines = _node_lines(node)
        if lines > SOFT_FUNCTION_LINES:
            findings.append(
                Finding(
                    path,
                    node.lineno,
                    f"function '{node.name}' is {lines} lines "
                    f"(soft {SOFT_FUNCTION_LINES}, hard {HARD_FUNCTION_LINES})",
                    hard=lines > HARD_FUNCTION_LINES,
                )
            )
        params = _param_count(node)
        if params > SOFT_PARAMS:
            findings.append(
                Finding(
                    path,
                    node.lineno,
                    f"function '{node.name}' has {params} parameters "
                    f"(soft {SOFT_PARAMS}, hard {HARD_PARAMS}; then a dataclass)",
                    hard=params > HARD_PARAMS,
                )
            )
    elif isinstance(node, ast.ClassDef):
        lines = _node_lines(node)
        if lines > SOFT_CLASS_LINES:
            findings.append(
                Finding(
                    path,
                    node.lineno,
                    f"class '{node.name}' is {lines} lines "
                    f"(soft {SOFT_CLASS_LINES}, hard {HARD_CLASS_LINES})",
                    hard=lines > HARD_CLASS_LINES,
                )
            )


def check_file(path: Path) -> list[Finding]:
    findings: list[Finding] = []
    source = path.read_text(encoding="utf-8")
    file_lines = source.count("\n") + 1
    if file_lines > SOFT_FILE_LINES:
        findings.append(
            Finding(
                path,
                1,
                f"file is {file_lines} lines "
                f"(soft {SOFT_FILE_LINES}, hard {HARD_FILE_LINES})",
                hard=file_lines > HARD_FILE_LINES,
            )
        )
    for node in ast.walk(ast.parse(source, filename=str(path))):
        _check_node(path, node, findings)
    return findings


def main(targets: list[str]) -> int:
    findings: list[Finding] = []
    for target in targets or ["src"]:
        for path in sorted(Path(target).rglob("*.py")):
            findings.extend(check_file(path))
    hard_failures = [f for f in findings if f.hard]
    for f in findings:
        kind = "HARD" if f.hard else "soft"
        print(f"{kind}: {f.path}:{f.line}: {f.message}")
    print(
        f"lint_sizes: {len(hard_failures)} hard violation(s), "
        f"{len(findings) - len(hard_failures)} soft warning(s)"
    )
    return 1 if hard_failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
