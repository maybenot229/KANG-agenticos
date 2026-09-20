"""The synthetic corpus generator package (ADR-049). See `generate.py`."""

from .generate import CorpusReport, generate, table_digest
from .profiles import PROFILES, YEAR1, YEAR5, YEAR10, Profile

__all__ = [
    "CorpusReport",
    "PROFILES",
    "Profile",
    "YEAR1",
    "YEAR5",
    "YEAR10",
    "generate",
    "table_digest",
]
