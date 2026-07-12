"""EnvConfig: %KANG_HOME% resolution, no silent defaults (D003, PS-002).

os.environ manipulation is sanctioned in test fixtures (11 §10).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kang.adapters.config.env_config import EnvConfig
from kang.domain.ports.config import ConfigError


def test_resolves_kang_home_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("KANG_HOME", str(tmp_path))
    assert EnvConfig().kang_home() == Path(str(tmp_path))


def test_unset_kang_home_fails_fast(monkeypatch):
    monkeypatch.delenv("KANG_HOME", raising=False)
    with pytest.raises(ConfigError):
        EnvConfig().kang_home()


def test_blank_kang_home_fails_fast(monkeypatch):
    monkeypatch.setenv("KANG_HOME", "   ")
    with pytest.raises(ConfigError):
        EnvConfig().kang_home()


def test_relative_kang_home_rejected(monkeypatch):
    monkeypatch.setenv("KANG_HOME", "relative/path")
    with pytest.raises(ConfigError):
        EnvConfig().kang_home()
