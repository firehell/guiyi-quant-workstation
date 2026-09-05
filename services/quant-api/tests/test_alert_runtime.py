from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from types import SimpleNamespace

import pytest

from app.alerts.notification import (
    ALERT_AUDIENCE_OWNER,
    ALERT_NOTIFICATION_POLICIES,
    AlertNotificationPolicy,
)
from app.alerts.registry import HTDY_ALERT_RULE_CODE, SUBING_THS_ALERT_RULE_CODE
from app.alerts.evaluators import AlertEvaluationError
from app.alerts.models import AlertRule
from app.alerts.runtime import (
    AlertRuntime,
    AlertNotificationAcknowledgeError,
    _parse_canonical_updated_trigger,
    _parse_live_bar_trigger,
    acknowledge_notification_failure,
    empty_alert_runtime_status,
    validate_alert_runtime_status,
)
from app.market_data.domain import CanonicalBar
from app.market_data.market_read_service import MarketReadWindow


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


def test_startup_composition_rejects_malformed_policy_before_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def session_factory():
        nonlocal called
        called = True
        raise AssertionError("policy validation must precede DB access")

    monkeypatch.setitem(ALERT_NOTIFICATION_POLICIES, SUBING_THS_ALERT_RULE_CODE, object())
    runtime = AlertRuntime(
        session_factory=session_factory,
        market_read_factory=lambda _session: None,  # type: ignore[arg-type]
        evaluators={
            HTDY_ALERT_RULE_CODE: object(),  # type: ignore[dict-item]
            SUBING_THS_ALERT_RULE_CODE: object(),  # type: ignore[dict-item]
        },
        sender=None,  # type: ignore[arg-type]
        operational_products=(),
        taxonomy={},
    )
    with pytest.raises(RuntimeError, match="ALERT_RUNTIME_COMPOSITION_INVALID"):
        runtime._validate_startup_composition()
    assert called is False


def test_startup_composition_rejects_policy_binding_mismatch_before_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def session_factory():
        nonlocal called
        called = True
        raise AssertionError("policy validation must precede DB access")

    monkeypatch.setitem(
        ALERT_NOTIFICATION_POLICIES,
        HTDY_ALERT_RULE_CODE,
        AlertNotificationPolicy(
            rule_code=HTDY_ALERT_RULE_CODE,
            title="归一量化 · 火天大有",
            audience=ALERT_AUDIENCE_OWNER,
            formatter=lambda _message: "wrong formatter",
        ),
    )
    runtime = AlertRuntime(
        session_factory=session_factory,
        market_read_factory=lambda _session: None,  # type: ignore[arg-type]
        evaluators={
            HTDY_ALERT_RULE_CODE: object(),  # type: ignore[dict-item]
            SUBING_THS_ALERT_RULE_CODE: object(),  # type: ignore[dict-item]
        },
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


def test_unrelated_live_frequency_does_not_clear_subing_rule_failure() -> None:
    first_bar_at = datetime(2026, 9, 4, 1, 0, tzinfo=UTC)
    now = iter(
        first_bar_at + timedelta(minutes=offset) for offset in (1, 2, 3)
    )
    rule = AlertRule(
        rule_code=SUBING_THS_ALERT_RULE_CODE,
        enabled=True,
        scope_product_frequencies={"rb": ["15m"]},
    )

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def scalars(self, _statement):
            return SimpleNamespace(all=lambda: [rule])

        @staticmethod
        def in_transaction() -> bool:
            return False

    class MarketRead:
        def bars_until(self, _query, *, trading_day, end, limit):
            del limit
            bar = CanonicalBar(
                bar_end=end,
                trading_day=trading_day,
                open=1,
                high=1,
                low=1,
                close=1,
                volume=1,
                turnover=None,
                open_interest=None,
            )
            return MarketReadWindow(
                symbol="rb",
                series_kind="actual_dominant",
                frequency="15m",
                trading_day=trading_day,
                contract="RB2610",
                cutoff=end,
                bars=(bar,),
                bar_contracts=("RB2610",),
            )

    class Evaluator:
        def __init__(self) -> None:
            self.calls = 0

        def evaluate_candidates(self, _market_read, _window):
            self.calls += 1
            if self.calls == 1:
                raise AlertEvaluationError("ALERT_EVALUATION_FAILED")
            return ()

    evaluator = Evaluator()
    runtime = AlertRuntime(
        session_factory=Session,
        market_read_factory=lambda _session: MarketRead(),
        evaluators={SUBING_THS_ALERT_RULE_CODE: evaluator},
        sender=object(),  # type: ignore[arg-type]
        operational_products=("rb",),
        taxonomy={},
        clock=lambda: next(now),
    )
    payload = {
        "bar_end": first_bar_at.isoformat(),
        "trading_day": first_bar_at.date().isoformat(),
        "open": "1",
        "high": "1",
        "low": "1",
        "close": "1",
        "volume": "1",
        "turnover": None,
        "open_interest": None,
    }

    runtime.process_message("live:bar:rb:15m", payload)
    failed = runtime._current_runtime_status()["rule_status"][
        SUBING_THS_ALERT_RULE_CODE
    ]
    assert failed["error_type"] == "evaluation_failed"
    assert failed["last_failure_at"] == "2026-09-04T01:01:00+00:00"
    assert failed["last_evaluated_bar_at"] is None

    runtime.process_message("live:bar:rb:1m", payload)
    assert runtime._current_runtime_status()["rule_status"][
        SUBING_THS_ALERT_RULE_CODE
    ] == failed

    runtime.process_message("live:bar:rb:15m", payload)
    recovered = runtime._current_runtime_status()["rule_status"][
        SUBING_THS_ALERT_RULE_CODE
    ]
    assert recovered["error_type"] is None
    assert recovered["last_evaluated_bar_at"] == first_bar_at.isoformat()
    assert recovered["last_failure_at"] == failed["last_failure_at"]
    assert evaluator.calls == 2
