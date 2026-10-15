"""Independent regression for v2 sender failures and operational health classes."""
from datetime import UTC, datetime
import logging

import pytest

from app.alerts.runtime import (
    AlertRuntime,
    NOTIFICATION_ACCEPTANCE_INVALID,
    NOTIFICATION_PREPARATION_FAILURE,
    NOTIFICATION_TRANSPORT_FAILURE,
)


@pytest.mark.parametrize(
    ('status', 'diagnostic', 'expected'),
    [
        ('PREPARATION_FAILED_NO_SEND', None, NOTIFICATION_PREPARATION_FAILURE),
        ('FAILED_OR_UNKNOWN', 'UNKNOWN', NOTIFICATION_PREPARATION_FAILURE),
        ('FAILED_OR_UNKNOWN', 'PUSHPLUS_ACCEPTANCE_INVALID', NOTIFICATION_ACCEPTANCE_INVALID),
        ('FAILED_OR_UNKNOWN', 'PUSHPLUS_REQUEST_OUTCOME_UNKNOWN', NOTIFICATION_TRANSPORT_FAILURE),
        ('FAILED_OR_UNKNOWN', 'PUSHPLUS_RATE_LIMITED', NOTIFICATION_TRANSPORT_FAILURE),
        ('FAILED_OR_UNKNOWN', 'PUSHPLUS_PROVIDER_REJECTED', NOTIFICATION_TRANSPORT_FAILURE),
    ],
)
def test_handoff_failure_preserves_health_class_and_event_link(caplog, status, diagnostic, expected):
    now = datetime(2026, 10, 15, 8, tzinfo=UTC)
    runtime = AlertRuntime(
        session_factory=lambda: None,
        market_read_factory=lambda session: None,
        evaluators={}, sender=None, operational_products=(), taxonomy={},
        clock=lambda: now,
    )
    with caplog.at_level(logging.WARNING, logger='app.alerts.runtime'):
        runtime._handoff_result((2117, 2118), status, diagnostic)
    result = runtime._current_runtime_status()
    assert result['notification_error_type'] == expected
    assert result['last_notification_failure_at'] == now.isoformat()
    assert result['consecutive_notification_failures'] == 1
    assert result['last_provider_accepted_at'] is None
    records = [r for r in caplog.records if r.msg == 'ALERT_NOTIFICATION_TRANSPORT_FAILED']
    assert [r.diagnostic_fields for r in records] == [{'event_id': 2117}, {'event_id': 2118}]
    assert all(r.diagnostic_code == (diagnostic or 'UNKNOWN') for r in records)
