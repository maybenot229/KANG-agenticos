"""Config port — resolves the data directory; runtime truth never comes
from the repository tree.

Layer: domain/ports.
Constitutional home: 04_ARCHITECTURE D003 (%KANG_HOME% is the one runtime
tree); 17_PROJECT_STRUCTURE PS-002/§8 (production code MUST NOT read
repository config/; the config port resolves %KANG_HOME% only).
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

__all__ = ["ConfigError", "ConfigPort"]


class ConfigError(Exception):
    """Configuration could not be resolved. Fail-fast at startup (11 §10)."""


class ConfigPort(Protocol):
    """Access to deployment configuration truth."""

    def kang_home(self) -> Path:
        """Return the resolved %KANG_HOME% data directory.

        Raises ConfigError when the location cannot be determined — there is
        no silent default into the repository tree (PS-002).
        """
        ...
