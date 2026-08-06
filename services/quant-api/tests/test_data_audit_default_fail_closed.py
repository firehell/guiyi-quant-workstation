"""Audit default composition must fail closed for unwired scopes."""

from __future__ import annotations

from app.services.data_operations.composition import build_default_audit_service
from app.services.data_operations.contracts import (
    AuditRequest,
    AuditScope,
    CommandStatus,
)


def test_default_audit_unwired_scopes_are_unavailable_not_empty_passed() -> None:
    service = build_default_audit_service()
    result = service.run(AuditRequest(scope=AuditScope.CATALOG))
    assert result.status is CommandStatus.ERROR
    assert result.error is not None
    assert result.error.code == "AUDIT_SCOPE_UNAVAILABLE"
    assert result.extras.get("findings") in (None, [])
