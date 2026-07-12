"""Architecture suite 2.1 — dependency direction (13 §2.1; 17 §4).

Two halves, both required by the M0 gate (18 §3 M0):
- GREEN: the 17 §4.2/§4.3 contracts hold on the real kang package.
- RED: a deliberate violation is actually caught — proving green is not
  vacuous ("import-linter red-tests: deliberate violations fail").
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}


def _lint_imports(config: Path, cwd: Path, env: dict) -> subprocess.CompletedProcess:
    executable = shutil.which("lint-imports")
    assert executable, "import-linter is not installed (pip install -e .[dev])"
    return subprocess.run(
        [executable, "--config", str(config)],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_the_dependency_constitution_holds_on_real_code():
    result = _lint_imports(REPO_ROOT / "tools" / "importlinter.toml", REPO_ROOT, _ENV)
    assert result.returncode == 0, (
        "17 §4 import contracts broken:\n" + result.stdout + result.stderr
    )
    assert "broken" in result.stdout.lower()  # "0 broken" summary is present
    assert "0 broken" in result.stdout


def test_a_deliberate_violation_turns_the_build_red(tmp_path):
    # A miniature repo whose domain imports its kernel — 17 §4.3 rule 1.
    package = tmp_path / "kangv"
    (package / "domain").mkdir(parents=True)
    (package / "kernel").mkdir()
    (package / "__init__.py").write_text("")
    (package / "kernel" / "__init__.py").write_text("")
    (package / "domain" / "__init__.py").write_text("import kangv.kernel\n")
    config = tmp_path / "importlinter.ini"
    config.write_text(
        "[importlinter]\n"
        "root_packages =\n    kangv\n\n"
        "[importlinter:contract:red]\n"
        "name = red-test: domain must not import kernel\n"
        "type = forbidden\n"
        "source_modules =\n    kangv.domain\n"
        "forbidden_modules =\n    kangv.kernel\n"
    )
    env = {**_ENV, "PYTHONPATH": str(tmp_path)}
    result = _lint_imports(config, tmp_path, env)
    assert result.returncode != 0, (
        "the linter passed a deliberate violation — contracts are vacuous:\n"
        + result.stdout
        + result.stderr
    )
    assert "BROKEN" in result.stdout


def test_every_src_package_has_a_contract_entry():
    """A new layer package without a contract entry is red by omission
    (17 §4.4). The top-level layers must each appear in the contract file."""
    contracts = (REPO_ROOT / "tools" / "importlinter.toml").read_text(encoding="utf-8")
    layers = [
        p.name
        for p in (REPO_ROOT / "src" / "kang").iterdir()
        if p.is_dir() and (p / "__init__.py").exists()
    ]
    missing = [layer for layer in layers if f"kang.{layer}" not in contracts]
    assert not missing, (
        f"layer packages without any contract entry: {missing} "
        "(add them to tools/importlinter.toml in this PR — 17 §4.4)"
    )


def test_adapter_tech_folders_each_have_an_independence_entry():
    contracts = (REPO_ROOT / "tools" / "importlinter.toml").read_text(encoding="utf-8")
    adapters = [
        p.name
        for p in (REPO_ROOT / "src" / "kang" / "adapters").iterdir()
        if p.is_dir() and (p / "__init__.py").exists()
    ]
    missing = [tech for tech in adapters if f"kang.adapters.{tech}" not in contracts]
    assert not missing, (
        f"adapter packages missing from the independence contract: {missing}"
    )


def test_no_production_import_of_tests_or_tools():
    """17 §4.3 rule 9, checked textually (tests/ and tools/ are not
    importable packages of kang, so the graph cannot see them)."""
    offenders = []
    for path in (REPO_ROOT / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "import tests" in text or "from tests" in text or "import tools" in text:
            offenders.append(str(path))
    assert not offenders, f"src imports tests/tools: {offenders}"
