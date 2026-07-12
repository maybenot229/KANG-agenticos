"""EnvConfig — resolves %KANG_HOME% from the process environment.

Layer: adapters/config (the ONE sanctioned home of os.environ, 11 §10).
Constitutional home: 04_ARCHITECTURE D003 (all runtime state under
%KANG_HOME%); 17_PROJECT_STRUCTURE PS-002 (a repository path appearing in
runtime config is a defect — hence no fallback into the checkout).
"""

from __future__ import annotations

import os
from pathlib import Path

from kang.domain.ports.config import ConfigError

__all__ = ["EnvConfig"]

_ENV_VAR = "KANG_HOME"


class EnvConfig:
    """ConfigPort implementation over the process environment."""

    def kang_home(self) -> Path:
        value = os.environ.get(_ENV_VAR, "").strip()
        if not value:
            raise ConfigError(
                f"%{_ENV_VAR}% is not set. KANG refuses to guess a data "
                "directory: runtime state never lives in the repository "
                "(PS-002) and a silent default would hide the real one (E4)."
            )
        home = Path(value).expanduser()
        if not home.is_absolute():
            raise ConfigError(f"%{_ENV_VAR}% must be an absolute path, got: {value!r}")
        return home
