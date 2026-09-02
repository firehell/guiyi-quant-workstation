from __future__ import annotations

from datetime import UTC, datetime
import json

import pytest

from app.alerts.runtime import (
    AlertRuntime,
    AlertNotificationAcknowledgeError,
    _parse_canonical_updated_trigger,
    _parse_live_bar_trigger,
    acknowledge_notification_failure,
    empty_alert_runtime_status,
    validate_alert_runtime_status,
)


def test_startup_composition_requires_exact_registry_evaluator_and_policy_coverage() -> None:
    called = False

    def session_factory():
        nonlocal called
        called = True
        raise AssertionError("not reached")

    runtime = AlertRuntime(
        session_factory=session_factory,
        market_read_factory=lambda _session: None,  # type: ignore[arg-type]
        evaluators={},
        sender=None,  # type: ignore[arg-type]
        operational_products=(),
        taxonomy={},
    )
    with pytest.raises(RuntimeError, match="ALERT_RUNTIME_COMPOSITION_INVALID"):
        runtime._validate_startup_composition()
    assert called is False


def test_empty_status_is_generic_schema_v6_with_fixed_per_rule_health() -> None:
    status = empty_alert_runtime_status()
    assert status["schema_version"] == 6
    assert set(status) == {
        "schema_version",
        "last_processed_bar_at",
        "last_processing_success_at",
        "last_processing_failure_at",
        "processing_error_type",
        "last_event_at",
        "last_transport_attempt_at",
        "last_provider_accepted_at",
        "last_notification_failure_at",
        "notification_acknowledged_at",
        "notification_error_type",
        "consecutive_notification_failures",
        "rule_status",
    }
    assert set(status["rule_status"]) == {
        "htdy_original_15m",
        "subing_ths_alert_15m_v1",
    }


def test_legacy_status_normalizes_by_discarding_unknown_fields() -> None:
    normalized = validate_alert_runtime_status({
        "schema_version": 4,
        "last_event_at": "2026-08-15T01:00:00+00:00",
        "removed_field": "ignored",
    })
    assert normalized == {
        **empty_alert_runtime_status(),
        "last_event_at": "2026-08-15T01:00:00+00:00",
    }


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"schema_version": 7},
        {**empty_alert_runtime_status(), "consecutive_notification_failures": -1},
        {**empty_alert_runtime_status(), "last_event_at": "naive"},
    ],
)
def test_invalid_status_fails_closed(payload: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="ALERT_RUNTIME_STATUS_INVALID"):
        validate_alert_runtime_status(payload)


def test_notification_acknowledgement_is_exact_and_one_shot() -> None:
    failure_at = "2026-08-15T01:00:00+00:00"
    status = {
        **empty_alert_runtime_status(),
        "last_notification_failure_at": failure_at,
        "notification_error_type": "notification_transport_failed",
        "consecutive_notification_failures": 1,
    }
    acknowledged = acknowledge_notification_failure(
        status,
        expected_failure_at=failure_at,
        acknowledged_at=datetime(2026, 8, 15, 1, 1, tzinfo=UTC),
    )
    assert acknowledged["notification_acknowledged_at"] == (
        "2026-08-15T01:01:00+00:00"
    )
    with pytest.raises(
        AlertNotificationAcknowledgeError,
        match="ALERT_NOTIFICATION_FAILURE_ALREADY_ACKNOWLEDGED",
    ):
        acknowledge_notification_failure(
            acknowledged,
            expected_failure_at=failure_at,
            acknowledged_at=datetime(2026, 8, 15, 1, 2, tzinfo=UTC),
        )


def test_live_trigger_accepts_only_completed_intraday_bar_shape() -> None:
    payload = json.dumps({
        "bar_end": "2026-08-15T01:00:00Z",
        "trading_day": "2026-08-15",
        "open": "100",
        "high": "102",
        "low": "99",
        "close": "101",
        "volume": "10",
        "turnover": None,
        "open_interest": "20",
    })
    trigger = _parse_live_bar_trigger("live:bar:jm:15m", payload)
    assert trigger is not None
    assert trigger.symbol == "jm"
    assert trigger.frequency.value == "15m"
    assert _parse_live_bar_trigger("live:bar:jm:1d", payload) is None
    assert _parse_live_bar_trigger("wrong", payload) is None
    assert _parse_live_bar_trigger("live:bar:jm:15m", "{}") is None


def test_canonical_trigger_is_exact_and_date_canonical() -> None:
    trigger = _parse_canonical_updated_trigger(
        "market:state",
        {"reason": "canonical_updated", "trading_day": "2026-08-15"},
    )
    assert trigger is not None
    assert trigger.trading_day.isoformat() == "2026-08-15"
    assert _parse_canonical_updated_trigger(
        "market:state",
        {"reason": "other", "trading_day": "2026-08-15"},
    ) is None
