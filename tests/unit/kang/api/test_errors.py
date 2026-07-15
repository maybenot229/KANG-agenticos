"""The one error model (API-006)."""

from __future__ import annotations

import pytest

from kang.api.errors import ApiError


def test_envelope_carries_the_correlation_id_and_shape():
    envelope = ApiError("not_found", "no task").to_envelope("corr-1")
    assert envelope == {
        "code": "not_found",
        "message": "no task",
        "correlation_id": "corr-1",
        "retryable": False,
    }


def test_details_and_remedy_are_included_when_present():
    envelope = ApiError(
        "permission_denied",
        "missing scope",
        details={"scope": "task.write"},
        remedy="grant task.write",
    ).to_envelope("corr-1")
    assert envelope["details"] == {"scope": "task.write"}
    assert envelope["remedy"] == "grant task.write"


def test_timeout_and_internal_are_retryable():
    assert ApiError("timeout", "slow").retryable
    assert ApiError("internal", "bug").retryable
    assert not ApiError("conflict", "stale").retryable


def test_unknown_code_is_rejected():
    with pytest.raises(ValueError, match="closed enum"):
        ApiError("teapot", "short and stout")
