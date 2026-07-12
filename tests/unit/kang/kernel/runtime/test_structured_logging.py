"""Structured logging: JSON lines, correlation threading (11 §6, 12 §5)."""

from __future__ import annotations

import io
import json
import logging

from kang.kernel.runtime.correlation import correlation_context, get_correlation_id
from kang.kernel.runtime.structured_logging import configure_logging


def _capture() -> tuple[io.StringIO, logging.Logger]:
    buffer = io.StringIO()
    configure_logging(stream=buffer, level=logging.DEBUG)
    return buffer, logging.getLogger("kang.test")


def test_log_lines_are_json_with_required_fields():
    buffer, logger = _capture()
    logger.info("state transition")
    entry = json.loads(buffer.getvalue().strip())
    assert entry["level"] == "info"
    assert entry["logger"] == "kang.test"
    assert entry["message"] == "state transition"
    assert "ts" in entry


def test_correlation_id_threads_through_the_context():
    buffer, logger = _capture()
    with correlation_context("corr-0001"):
        logger.info("inside invocation")
    logger.info("outside invocation")
    inside, outside = [
        json.loads(line) for line in buffer.getvalue().strip().splitlines()
    ]
    assert inside["correlation_id"] == "corr-0001"
    assert outside["correlation_id"] is None


def test_correlation_context_resets_on_exit():
    with correlation_context("corr-0002"):
        assert get_correlation_id() == "corr-0002"
    assert get_correlation_id() is None


def test_extra_fields_pass_through():
    buffer, logger = _capture()
    logger.info("captured", extra={"task_id": "task-0001"})
    entry = json.loads(buffer.getvalue().strip())
    assert entry["task_id"] == "task-0001"


def test_configure_logging_is_idempotent():
    buffer = io.StringIO()
    configure_logging(stream=buffer)
    configure_logging(stream=buffer)
    logging.getLogger("kang.test").info("once")
    assert len(buffer.getvalue().strip().splitlines()) == 1
