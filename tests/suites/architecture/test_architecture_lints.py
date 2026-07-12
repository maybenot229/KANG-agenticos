"""Architecture suite 2.1 — boundary bans, size limits, tree hygiene
(13 §2.1: the 11 §25 list as lint tests; PS-002 tree hygiene).

Each linter is proven both ways: green on the real tree, red on a planted
violation — a lint that cannot fail is not a lint.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOLS = REPO_ROOT / "tools"
_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}


def _run(tool: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(TOOLS / tool), *args],
        cwd=REPO_ROOT,
        env=_ENV,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


# ------------------------------------------------------------- size limits


def test_size_limits_green_on_real_code():
    result = _run("lint_sizes.py", "src")
    assert result.returncode == 0, result.stdout


def test_size_limits_catch_an_oversized_function(tmp_path):
    body = "\n".join(f"    x{i} = {i}" for i in range(90))
    (tmp_path / "big.py").write_text(f"def oversized():\n{body}\n")
    result = _run("lint_sizes.py", str(tmp_path))
    assert result.returncode == 1
    assert "oversized" in result.stdout


def test_size_limits_catch_too_many_parameters(tmp_path):
    (tmp_path / "wide.py").write_text("def wide(a, b, c, d, e, f, g):\n    return a\n")
    result = _run("lint_sizes.py", str(tmp_path))
    assert result.returncode == 1
    assert "parameters" in result.stdout


# --------------------------------------------------------- banned patterns


def test_banned_patterns_green_on_real_code():
    result = _run("lint_banned_patterns.py", "src")
    assert result.returncode == 0, result.stdout


def test_banned_patterns_catch_print_in_src(tmp_path):
    pkg = tmp_path / "kang" / "domain"
    pkg.mkdir(parents=True)
    (pkg / "noisy.py").write_text('print("debugging")\n')
    result = _run("lint_banned_patterns.py", str(tmp_path))
    assert result.returncode == 1
    assert "print in src" in result.stdout


def test_banned_patterns_catch_sql_outside_store_layer(tmp_path):
    pkg = tmp_path / "kang" / "domain"
    pkg.mkdir(parents=True)
    (pkg / "sneaky.py").write_text('q = "SELECT id FROM task"\n')
    result = _run("lint_banned_patterns.py", str(tmp_path))
    assert result.returncode == 1
    assert "SQL outside the store layer" in result.stdout


def test_banned_patterns_catch_wall_clock(tmp_path):
    pkg = tmp_path / "kang" / "domain"
    pkg.mkdir(parents=True)
    (pkg / "impatient.py").write_text("now = datetime.now()\n")
    result = _run("lint_banned_patterns.py", str(tmp_path))
    assert result.returncode == 1
    assert "wall clock" in result.stdout


def test_banned_patterns_allow_os_environ_in_config_adapter(tmp_path):
    pkg = tmp_path / "kang" / "adapters" / "config"
    pkg.mkdir(parents=True)
    (pkg / "env_config.py").write_text('home = os.environ.get("KANG_HOME")\n')
    result = _run("lint_banned_patterns.py", str(tmp_path))
    assert result.returncode == 0, result.stdout


# ------------------------------------------------------------ tree hygiene


def test_tree_hygiene_green_on_the_repository():
    result = _run("lint_tree_hygiene.py", ".")
    assert result.returncode == 0, result.stdout


def test_tree_hygiene_catches_a_database_file(tmp_path):
    (tmp_path / "local_test.db").write_bytes(b"")
    result = _run("lint_tree_hygiene.py", str(tmp_path))
    assert result.returncode == 1
    assert "runtime-state file" in result.stdout


def test_tree_hygiene_catches_a_planted_secret(tmp_path):
    # Assembled at runtime so this test file itself stays clean.
    fake_key = "sk-ant-" + "a0" * 8
    (tmp_path / "config.toml").write_text(f'key = "{fake_key}"\n')
    result = _run("lint_tree_hygiene.py", str(tmp_path))
    assert result.returncode == 1
    assert "secret pattern" in result.stdout


# ------------------------------------------------------------- root docs


def test_root_claude_md_is_generated_and_current():
    result = _run("build_root_docs.py", "--check")
    assert result.returncode == 0, result.stdout
