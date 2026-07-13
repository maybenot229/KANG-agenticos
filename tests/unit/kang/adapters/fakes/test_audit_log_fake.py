"""FakeAuditLog against the port contract (13 §2.3 fake/real pairing)."""

from __future__ import annotations

import pytest

from kang.adapters.fakes.audit_log import FakeAuditLog
from tests.fixtures.audit_log_contract import AuditLogContract


class TestFakeAuditLog(AuditLogContract):
    @pytest.fixture
    def log(self) -> FakeAuditLog:
        return FakeAuditLog()
