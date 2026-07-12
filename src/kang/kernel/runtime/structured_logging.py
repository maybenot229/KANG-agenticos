"""Structured logging — JSON lines only, correlation-id threaded.

Layer: kernel/runtime.
Constitutional home: 11_CODING §6 (structured JSON lines; every log call
carries correlation_id inside an invocation; print() is banned in src);
04_ARCHITECTURE D015. Log ≠ audit: audit truth goes through the audit
service exclusively (S5) — this is diagnostics.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from kang.kernel.runtime.correlation import get_correlation_id

__all__ = ["JsonLineFormatter", "configure_logging"]

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
}


class JsonLineFormatter(logging.Formatter):
    """One JSON object per line; extra kwargs pass through as fields."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": get_correlation_id(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                entry[key] = value
        if record.exc_info and record.exc_info[0] is not None:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


def configure_logging(stream=None, level: int = logging.INFO) -> None:
    """Install the JSON-lines handler on the root logger (idempotent:
    replaces prior KANG handlers rather than stacking them)."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_kang_handler", False):
            root.removeHandler(handler)
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonLineFormatter())
    handler._kang_handler = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(level)
