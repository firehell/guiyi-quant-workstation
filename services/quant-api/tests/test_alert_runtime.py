from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, date, datetime, timedelta
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session as OrmSession

from app.alerts.evaluators import (
    AlertEvaluationError,
    AlertObservationCandidate,
    SubingThs15mEvaluator,
)
from app.alerts.models import AlertEvent, AlertRule
from app.alerts.notification import (
    ALERT_AUDIENCE_OWNER,
    ALERT_NOTIFICATION_POLICIES,
    AlertNotificationPolicy,
    ProviderAcceptance,
)
from app.alerts.registry import HTDY_ALERT_RULE_CODE, SUBING_THS_ALERT_RULE_CODE
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
from app.market_data.market_read_service import (
    CurrentContractReplayWindow,
    MarketReadWindow,
    MarketReadWindowError,
)
from app.services.runtime_health import _collect_alert_health


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


@pytest.mark.parametrize("rule_code", [HTDY_ALERT_RULE_CODE, SUBING_THS_ALERT_RULE_CODE])
def test_unrelated_live_frequency_does_not_clear_rule_failure_or_health(rule_code) -> None:
    first_bar_at = datetime(2026, 9, 4, 1, 0, tzinfo=UTC)
    now = iter(
        first_bar_at + timedelta(minutes=offset) for offset in (1, 2, 3)
    )
    rule = AlertRule(
        rule_code=rule_code,
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
        def assert_window_current(self, window):
            return None

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
        evaluators={rule_code: evaluator},
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

    def alert_health():
        values = {
            "alert:heartbeat": json.dumps({
                "generated_at": first_bar_at.isoformat(), "available": True,
                "enabled_rule_count": 1, "scope_product_count": 1,
            }),
            "alert:runtime-status": json.dumps(runtime._current_runtime_status()),
        }
        return _collect_alert_health(
            SimpleNamespace(get=values.get), now=first_bar_at,
            configured_enabled=True,
            notification={"configured": True}, transport_error_type=None,
            freshness_seconds=30,
        )

    runtime.process_message("live:bar:rb:15m", payload)
    failed = runtime._current_runtime_status()["rule_status"][
        rule_code
    ]
    assert failed["error_type"] == "evaluation_failed"
    assert failed["last_failure_at"] == "2026-09-04T01:01:00+00:00"
    assert failed["last_evaluated_bar_at"] is None
    assert alert_health()["status"] == "degraded"

    runtime.process_message("live:bar:rb:1m", payload)
    assert runtime._current_runtime_status()["rule_status"][
        rule_code
    ] == failed
    assert alert_health()["status"] == "degraded"

    runtime.process_message("live:bar:rb:15m", payload)
    recovered = runtime._current_runtime_status()["rule_status"][
        rule_code
    ]
    assert recovered["error_type"] is None
    assert recovered["last_evaluated_bar_at"] == first_bar_at.isoformat()
    assert recovered["last_failure_at"] == failed["last_failure_at"]
    assert evaluator.calls == 2
    assert alert_health()["status"] == "ok"


def test_subing_duplicate_after_failed_cutoff_does_not_clear_rule_health() -> None:
    first_bar_at = datetime(2026, 9, 4, 1, 0, tzinfo=UTC)
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

    class Kernel:
        def initial_state(self):
            return 0

        def step(self, state, close, *, bar_end):
            del close, bar_end
            return state + 1, SimpleNamespace(
                valid=state > 0, ready=state > 0, result_codes=()
            )

    class MarketRead:
        @staticmethod
        def assert_window_current(_window):
            return None

        def bars_until(self, _query, *, trading_day, end, limit):
            del limit
            bar = CanonicalBar(end, trading_day, 1, 1, 1, 1, 1, None, None)
            return MarketReadWindow(
                "rb", "actual_dominant", "15m", trading_day, "RB2610", end,
                (bar,), ("RB2610",),
            )

        def current_contract_replay_window(self, window, *, after):
            return CurrentContractReplayWindow(
                window.symbol, window.frequency, window.trading_day,
                window.contract, window.cutoff, after, (window.bars[-1],),
            )

    times = iter(
        (
            first_bar_at + timedelta(minutes=1),
            first_bar_at + timedelta(minutes=2),
            first_bar_at + timedelta(minutes=16),
        )
    )
    runtime = AlertRuntime(
        session_factory=Session,
        market_read_factory=lambda _session: MarketRead(),
        evaluators={SUBING_THS_ALERT_RULE_CODE: SubingThs15mEvaluator(kernel=Kernel())},
        sender=object(),  # type: ignore[arg-type]
        operational_products=("rb",),
        taxonomy={},
        clock=lambda: next(times),
    )
    payload = {
        "bar_end": first_bar_at.isoformat(),
        "trading_day": first_bar_at.date().isoformat(),
        "open": "1", "high": "1", "low": "1", "close": "1", "volume": "1",
        "turnover": None, "open_interest": None,
    }

    runtime.process_message("live:bar:rb:15m", payload)
    failed = runtime._current_runtime_status()["rule_status"][SUBING_THS_ALERT_RULE_CODE]
    runtime.process_message("live:bar:rb:15m", payload)
    assert runtime._current_runtime_status()["rule_status"][SUBING_THS_ALERT_RULE_CODE] == failed

    next_payload = {
        **payload,
        "bar_end": (first_bar_at + timedelta(minutes=15)).isoformat(),
    }
    runtime.process_message("live:bar:rb:15m", next_payload)
    recovered = runtime._current_runtime_status()["rule_status"][SUBING_THS_ALERT_RULE_CODE]
    assert recovered["error_type"] is None
    assert recovered["last_evaluated_bar_at"] == next_payload["bar_end"]
    assert recovered["last_failure_at"] == failed["last_failure_at"]


def test_htdy_incomplete_window_records_failure_without_event_or_notification() -> None:
    bar_at = datetime(2026, 9, 4, 1, 0, tzinfo=UTC)
    rule = AlertRule(
        rule_code=HTDY_ALERT_RULE_CODE,
        enabled=True,
        scope_product_frequencies={"rb": ["60m"]},
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
        @staticmethod
        def bars_until(_query, *, trading_day, end, limit):
            del trading_day, end, limit
            raise MarketReadWindowError("MARKET_READ_WINDOW_INCOMPLETE")

    class Sender:
        calls = 0

        def send(self, _message):
            self.calls += 1
            raise AssertionError("incomplete input must not notify")

    class Evaluator:
        calls = 0

        def evaluate_candidates(self, _market_read, _window):
            self.calls += 1
            raise AssertionError("incomplete input must not reach the kernel")

    evaluator = Evaluator()
    sender = Sender()
    runtime = AlertRuntime(
        session_factory=Session,
        market_read_factory=lambda _session: MarketRead(),
        evaluators={HTDY_ALERT_RULE_CODE: evaluator},
        sender=sender,  # type: ignore[arg-type]
        operational_products=("rb",),
        taxonomy={},
        clock=lambda: bar_at + timedelta(seconds=1),
    )
    payload = {
        "bar_end": bar_at.isoformat(),
        "trading_day": bar_at.date().isoformat(),
        "open": "1", "high": "1", "low": "1", "close": "1", "volume": "1",
        "turnover": None, "open_interest": None,
    }

    runtime.process_message("live:bar:rb:60m", payload)

    rule_status = runtime._current_runtime_status()["rule_status"][HTDY_ALERT_RULE_CODE]
    assert rule_status["error_type"] == "evaluation_failed"
    assert rule_status["last_event_at"] is None
    assert evaluator.calls == sender.calls == 0


def test_subing_event_persistence_failure_is_not_retried_by_duplicate() -> None:
    first_bar_at = datetime(2026, 9, 4, 1, 0, tzinfo=UTC)
    rule = AlertRule(
        rule_code=SUBING_THS_ALERT_RULE_CODE,
        enabled=True,
        scope_product_frequencies={"rb": ["15m"]},
    )
    persistence_attempts = 0

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def scalars(self, _statement):
            return SimpleNamespace(all=lambda: [rule])

        def get(self, *_args):
            nonlocal persistence_attempts
            persistence_attempts += 1
            raise RuntimeError("isolated persistence failure")

        @staticmethod
        def in_transaction() -> bool:
            return False

    class Kernel:
        def initial_state(self):
            return 0

        def step(self, state, close, *, bar_end):
            del bar_end
            return state + 1, SimpleNamespace(
                valid=True,
                ready=True,
                result_codes=("buy",) if close == 2.0 else (),
            )

    class MarketRead:
        @staticmethod
        def assert_window_current(_window):
            return None

        def bars_until(self, _query, *, trading_day, end, limit):
            del limit
            close = 2 if end == first_bar_at else 1
            bar = CanonicalBar(
                end, trading_day, close, close, close, close, 1, None, None
            )
            return MarketReadWindow(
                "rb", "actual_dominant", "15m", trading_day, "RB2610", end,
                (bar,), ("RB2610",),
            )

        @staticmethod
        def current_contract_replay_window(window, *, after):
            return CurrentContractReplayWindow(
                window.symbol, window.frequency, window.trading_day,
                window.contract, window.cutoff, after, (window.bars[-1],),
            )

    times = iter(
        (
            first_bar_at + timedelta(minutes=1),
            first_bar_at + timedelta(minutes=2),
            first_bar_at + timedelta(minutes=16),
        )
    )
    runtime = AlertRuntime(
        session_factory=Session,
        market_read_factory=lambda _session: MarketRead(),
        evaluators={
            SUBING_THS_ALERT_RULE_CODE: SubingThs15mEvaluator(kernel=Kernel())
        },
        sender=object(),  # type: ignore[arg-type]
        operational_products=("rb",),
        taxonomy={},
        clock=lambda: next(times),
    )
    payload = {
        "bar_end": first_bar_at.isoformat(),
        "trading_day": first_bar_at.date().isoformat(),
        "open": "2", "high": "2", "low": "2", "close": "2", "volume": "1",
        "turnover": None, "open_interest": None,
    }

    runtime.process_message("live:bar:rb:15m", payload)
    failed = runtime._current_runtime_status()
    assert failed["processing_error_type"] == "processing_failed"
    assert persistence_attempts == 1

    runtime.process_message("live:bar:rb:15m", payload)
    assert runtime._current_runtime_status() == failed
    assert persistence_attempts == 1

    next_payload = {
        **payload,
        "bar_end": (first_bar_at + timedelta(minutes=15)).isoformat(),
        "open": "1", "high": "1", "low": "1", "close": "1",
    }
    runtime.process_message("live:bar:rb:15m", next_payload)
    recovered = runtime._current_runtime_status()
    assert recovered["processing_error_type"] is None
    assert recovered["last_processing_failure_at"] == failed["last_processing_failure_at"]
    assert persistence_attempts == 1


@pytest.mark.parametrize("failure_stage", ("enter", "exit"))
def test_recovery_guard_failures_keep_their_own_log_classification(
    failure_stage: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    bar_at = datetime(2026, 9, 4, 1, 0, tzinfo=UTC)

    class FailingGuard:
        def __enter__(self):
            if failure_stage == "enter":
                raise RuntimeError("isolated guard enter failure")
            return self

        def __exit__(self, *_args):
            if failure_stage == "exit":
                raise RuntimeError("isolated guard exit failure")
            return False

    runtime = AlertRuntime(
        session_factory=lambda: None,  # type: ignore[arg-type]
        market_read_factory=lambda _session: None,  # type: ignore[arg-type]
        evaluators={},
        sender=object(),  # type: ignore[arg-type]
        operational_products=("rb",),
        taxonomy={},
        clock=lambda: bar_at + timedelta(seconds=1),
        live_processing_guard=lambda _symbol: FailingGuard(),
    )
    monkeypatch.setattr(runtime, "_process_live_guarded", lambda _trigger: None)
    payload = {
        "bar_end": bar_at.isoformat(),
        "trading_day": bar_at.date().isoformat(),
        "open": "1", "high": "1", "low": "1", "close": "1", "volume": "1",
        "turnover": None, "open_interest": None,
    }

    runtime.process_message("live:bar:rb:15m", payload)

    messages = tuple(record.message for record in caplog.records)
    assert "ALERT_RECOVERY_GUARD_UNAVAILABLE" in messages
    assert "ALERT_PROCESSING_FAILED" not in messages
    assert runtime._current_runtime_status()["processing_error_type"] == "processing_failed"


@pytest.mark.parametrize(
    ("failure_stage", "expected_log"),
    (("database", "ALERT_PROCESSING_FAILED"), ("evaluator", "ALERT_RULE_PROCESSING_FAILED")),
)
def test_internal_failures_are_not_classified_as_recovery_guard_failures(
    failure_stage: str,
    expected_log: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    bar_at = datetime(2026, 9, 4, 1, 0, tzinfo=UTC)
    rule = AlertRule(
        rule_code=HTDY_ALERT_RULE_CODE,
        enabled=True,
        scope_product_frequencies={"rb": ["15m"]},
    )

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def scalars(self, _statement):
            if failure_stage == "database":
                raise RuntimeError("isolated database failure")
            return SimpleNamespace(all=lambda: [rule])

        @staticmethod
        def in_transaction() -> bool:
            return False

    class MarketRead:
        @staticmethod
        def assert_window_current(_window):
            return None

        @staticmethod
        def bars_until(_query, *, trading_day, end, limit):
            del limit
            bar = CanonicalBar(end, trading_day, 1, 1, 1, 1, 1, None, None)
            return MarketReadWindow(
                "rb", "actual_dominant", "15m", trading_day, "RB2610", end,
                (bar,), ("RB2610",),
            )

    class Evaluator:
        @staticmethod
        def evaluate_candidates(_market_read, _window):
            raise RuntimeError("isolated evaluator failure")

    runtime = AlertRuntime(
        session_factory=Session,
        market_read_factory=lambda _session: MarketRead(),
        evaluators={HTDY_ALERT_RULE_CODE: Evaluator()},
        sender=object(),  # type: ignore[arg-type]
        operational_products=("rb",),
        taxonomy={},
        clock=lambda: bar_at + timedelta(seconds=1),
        live_processing_guard=lambda _symbol: nullcontext(),
    )
    payload = {
        "bar_end": bar_at.isoformat(),
        "trading_day": bar_at.date().isoformat(),
        "open": "1", "high": "1", "low": "1", "close": "1", "volume": "1",
        "turnover": None, "open_interest": None,
    }

    runtime.process_message("live:bar:rb:15m", payload)

    messages = tuple(record.message for record in caplog.records)
    assert expected_log in messages
    assert "ALERT_RECOVERY_GUARD_UNAVAILABLE" not in messages
    assert runtime._current_runtime_status()["processing_error_type"] == "processing_failed"


def test_internal_status_failure_is_not_classified_as_recovery_guard_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bar_at = datetime(2026, 9, 4, 1, 0, tzinfo=UTC)
    rule = AlertRule(
        rule_code=HTDY_ALERT_RULE_CODE,
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
        @staticmethod
        def assert_window_current(_window):
            return None

        def bars_until(self, _query, *, trading_day, end, limit):
            del limit
            bar = CanonicalBar(end, trading_day, 1, 1, 1, 1, 1, None, None)
            return MarketReadWindow(
                "rb", "actual_dominant", "15m", trading_day, "RB2610", end,
                (bar,), ("RB2610",),
            )

    class Evaluator:
        @staticmethod
        def evaluate_candidates(_market_read, _window):
            return ()

    class FailingStatusStore:
        @staticmethod
        def read():
            return empty_alert_runtime_status()

        @staticmethod
        def update(_changes):
            raise ConnectionError("isolated status failure")

    runtime = AlertRuntime(
        session_factory=Session,
        market_read_factory=lambda _session: MarketRead(),
        evaluators={HTDY_ALERT_RULE_CODE: Evaluator()},
        sender=object(),  # type: ignore[arg-type]
        operational_products=("rb",),
        taxonomy={},
        runtime_status_store=FailingStatusStore(),
        clock=lambda: bar_at + timedelta(seconds=1),
        live_processing_guard=lambda _symbol: nullcontext(),
    )
    payload = {
        "bar_end": bar_at.isoformat(),
        "trading_day": bar_at.date().isoformat(),
        "open": "1", "high": "1", "low": "1", "close": "1", "volume": "1",
        "turnover": None, "open_interest": None,
    }

    with pytest.raises(ConnectionError, match="isolated status failure"):
        runtime.process_message("live:bar:rb:15m", payload)

    messages = tuple(record.message for record in caplog.records)
    assert "ALERT_PROCESSING_FAILED" in messages
    assert "ALERT_RECOVERY_GUARD_UNAVAILABLE" not in messages


@pytest.mark.parametrize("failure_mode", ("always", "once"))
def test_event_commit_then_status_failure_keeps_event_and_blocks_sender(
    failure_mode: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    bar_at = datetime(2026, 9, 4, 1, 0, tzinfo=UTC)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    AlertRule.__table__.create(engine)
    AlertEvent.__table__.create(engine)
    with OrmSession(engine) as session:
        session.add(
            AlertRule(
                rule_code=HTDY_ALERT_RULE_CODE,
                enabled=True,
                scope_product_frequencies={"rb": ["15m"]},
            )
        )
        session.commit()

    class MarketRead:
        @staticmethod
        def assert_window_current(_window):
            return None

        @staticmethod
        def bars_until(_query, *, trading_day, end, limit):
            del limit
            bar = CanonicalBar(end, trading_day, 1, 1, 1, 1, 1, None, None)
            return MarketReadWindow(
                "rb", "actual_dominant", "15m", trading_day, "RB2610", end,
                (bar,), ("RB2610",),
            )

    class Evaluator:
        @staticmethod
        def evaluate_candidates(_market_read, window):
            return (
                AlertObservationCandidate(
                    window.cutoff,
                    window.trading_day,
                    window.contract,
                    ("buy",),
                ),
            )

    class Sender:
        calls = 0

        def send(self, _message):
            self.calls += 1
            return ProviderAcceptance("accepted")

    class FailingStatusStore:
        def __init__(self) -> None:
            self.status = empty_alert_runtime_status()
            self.updates = 0

        def read(self):
            return self.status

        def update(self, changes):
            self.updates += 1
            if failure_mode == "always" or self.updates == 1:
                raise ConnectionError("isolated status failure")
            self.status = {**self.status, **changes}
            return self.status

    sender = Sender()
    status_store = FailingStatusStore()
    runtime = AlertRuntime(
        session_factory=lambda: OrmSession(engine),
        market_read_factory=lambda _session: MarketRead(),
        evaluators={HTDY_ALERT_RULE_CODE: Evaluator()},
        sender=sender,
        operational_products=("rb",),
        taxonomy={"rb": SimpleNamespace(name="螺纹钢")},
        runtime_status_store=status_store,
        clock=lambda: bar_at + timedelta(seconds=1),
        live_processing_guard=lambda _symbol: nullcontext(),
    )
    payload = {
        "bar_end": bar_at.isoformat(),
        "trading_day": bar_at.date().isoformat(),
        "open": "1", "high": "1", "low": "1", "close": "1", "volume": "1",
        "turnover": None, "open_interest": None,
    }

    if failure_mode == "always":
        with pytest.raises(ConnectionError, match="isolated status failure"):
            runtime.process_message("live:bar:rb:15m", payload)
    else:
        runtime.process_message("live:bar:rb:15m", payload)

    with OrmSession(engine) as session:
        assert session.scalar(select(func.count()).select_from(AlertEvent)) == 1
    messages = tuple(record.message for record in caplog.records)
    expected_log = (
        "ALERT_PROCESSING_FAILED"
        if failure_mode == "always"
        else "ALERT_RULE_PROCESSING_FAILED"
    )
    assert expected_log in messages
    assert "ALERT_RECOVERY_GUARD_UNAVAILABLE" not in messages
    assert sender.calls == 0
    engine.dispose()


@pytest.mark.parametrize("frequency", ("1d", "1w"))
@pytest.mark.parametrize("failure_mode", ("always", "once"))
def test_canonical_event_commit_then_status_failure_blocks_sender(
    frequency: str,
    failure_mode: str,
) -> None:
    """Catches releasing a canonical message before its rule status is recorded."""
    trading_day = date(2026, 9, 11)
    bar_at = datetime(2026, 9, 11, 7, tzinfo=UTC)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    AlertRule.__table__.create(engine)
    AlertEvent.__table__.create(engine)
    with OrmSession(engine) as session:
        session.add(
            AlertRule(
                rule_code=HTDY_ALERT_RULE_CODE,
                enabled=True,
                scope_product_frequencies={"rb": [frequency]},
            )
        )
        session.commit()

    window = MarketReadWindow(
        "rb",
        "actual_dominant",
        frequency,
        trading_day,
        "RB2610",
        bar_at,
        (CanonicalBar(bar_at, trading_day, 1, 1, 1, 1, 1, None, None),),
        ("RB2610",),
    )

    class MarketRead:
        @staticmethod
        def latest_canonical_window(_query, *, trading_day, limit):
            assert trading_day == window.trading_day
            assert limit == 64
            return window

    class Evaluator:
        @staticmethod
        def evaluate_candidates(_market_read, candidate_window):
            return (
                AlertObservationCandidate(
                    candidate_window.cutoff,
                    candidate_window.trading_day,
                    candidate_window.contract,
                    ("buy",),
                ),
            )

    class Sender:
        calls = 0

        def send(self, _message):
            self.calls += 1
            return ProviderAcceptance("accepted")

    class FailingStatusStore:
        def __init__(self) -> None:
            self.status = empty_alert_runtime_status()
            self.updates = 0

        def read(self):
            return self.status

        def update(self, changes):
            self.updates += 1
            if failure_mode == "always" or self.updates == 1:
                raise ConnectionError("isolated canonical status failure")
            self.status = {**self.status, **changes}
            return self.status

    sender = Sender()
    runtime = AlertRuntime(
        session_factory=lambda: OrmSession(engine),
        market_read_factory=lambda _session: MarketRead(),
        evaluators={HTDY_ALERT_RULE_CODE: Evaluator()},
        sender=sender,
        operational_products=("rb",),
        taxonomy={"rb": SimpleNamespace(name="螺纹钢")},
        runtime_status_store=FailingStatusStore(),
        clock=lambda: bar_at + timedelta(seconds=1),
    )

    if failure_mode == "always":
        with pytest.raises(
            ConnectionError, match="isolated canonical status failure"
        ):
            runtime.process_message(
                "market:state",
                {
                    "reason": "canonical_updated",
                    "trading_day": trading_day.isoformat(),
                },
            )
    else:
        runtime.process_message(
            "market:state",
            {
                "reason": "canonical_updated",
                "trading_day": trading_day.isoformat(),
            },
        )

    with OrmSession(engine) as session:
        assert session.scalar(select(func.count()).select_from(AlertEvent)) == 1
    assert sender.calls == 0
    engine.dispose()


def test_unscoped_canonical_update_does_not_clear_processing_failure() -> None:
    """Catches treating a canonical notification with zero evaluations as success."""
    trading_day = date(2026, 9, 11)
    rule = AlertRule(
        rule_code=HTDY_ALERT_RULE_CODE,
        enabled=True,
        scope_product_frequencies={"rb": ["15m"]},
    )

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def in_transaction():
            return False

        @staticmethod
        def scalars(_statement):
            return SimpleNamespace(all=lambda: [rule])

    class MarketRead:
        @staticmethod
        def latest_canonical_window(*_args, **_kwargs):
            raise AssertionError("unscoped canonical path must not read")

    now = datetime(2026, 9, 11, 8, tzinfo=UTC)
    runtime = AlertRuntime(
        session_factory=Session,
        market_read_factory=lambda _session: MarketRead(),
        evaluators={HTDY_ALERT_RULE_CODE: object()},  # type: ignore[dict-item]
        sender=object(),  # type: ignore[arg-type]
        operational_products=("rb",),
        taxonomy={},
        clock=lambda: now,
    )
    runtime._record_processing_result(
        processing_now=now,
        bar_at=now,
        failed=True,
    )
    failed = dict(runtime._current_runtime_status())

    runtime.process_message(
        "market:state",
        {"reason": "canonical_updated", "trading_day": trading_day.isoformat()},
    )

    current = runtime._current_runtime_status()
    assert current["processing_error_type"] == failed["processing_error_type"]
    assert current["last_processing_success_at"] == failed[
        "last_processing_success_at"
    ]


def test_canonical_status_failure_discards_only_its_unapproved_message() -> None:
    """Catches mixing a failed item's message into another item's approved batch."""
    trading_day = date(2026, 9, 11)
    bar_at = datetime(2026, 9, 11, 7, tzinfo=UTC)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    AlertRule.__table__.create(engine)
    AlertEvent.__table__.create(engine)
    with OrmSession(engine) as session:
        session.add(
            AlertRule(
                rule_code=HTDY_ALERT_RULE_CODE,
                enabled=True,
                scope_product_frequencies={"jm": ["1d"], "rb": ["1d"]},
            )
        )
        session.commit()

    class MarketRead:
        @staticmethod
        def latest_canonical_window(query, *, trading_day, limit):
            assert limit == 64
            contract = f"{query.symbol.upper()}2610"
            bar = CanonicalBar(
                bar_at,
                trading_day,
                1,
                1,
                1,
                1,
                1,
                None,
                None,
            )
            return MarketReadWindow(
                query.symbol,
                "actual_dominant",
                "1d",
                trading_day,
                contract,
                bar_at,
                (bar,),
                (contract,),
            )

    class Evaluator:
        @staticmethod
        def evaluate_candidates(_market_read, window):
            return (
                AlertObservationCandidate(
                    window.cutoff,
                    window.trading_day,
                    window.contract,
                    ("buy",),
                ),
            )

    class Sender:
        def __init__(self) -> None:
            self.symbols: list[str] = []

        def send(self, message):
            self.symbols.append(message.symbol)
            return ProviderAcceptance("accepted")

    class FailSecondRuleStatus:
        def __init__(self) -> None:
            self.status = empty_alert_runtime_status()
            self.rule_updates = 0

        def read(self):
            return self.status

        def update(self, changes):
            if "rule_status" in changes:
                self.rule_updates += 1
                if self.rule_updates == 2:
                    raise ConnectionError("isolated second item status failure")
            self.status = {**self.status, **changes}
            return self.status

    sender = Sender()
    runtime = AlertRuntime(
        session_factory=lambda: OrmSession(engine),
        market_read_factory=lambda _session: MarketRead(),
        evaluators={HTDY_ALERT_RULE_CODE: Evaluator()},
        sender=sender,
        operational_products=("rb", "jm"),
        taxonomy={
            "jm": SimpleNamespace(name="焦煤"),
            "rb": SimpleNamespace(name="螺纹钢"),
        },
        runtime_status_store=FailSecondRuleStatus(),
        clock=lambda: bar_at + timedelta(seconds=1),
    )

    runtime.process_message(
        "market:state",
        {"reason": "canonical_updated", "trading_day": trading_day.isoformat()},
    )

    with OrmSession(engine) as session:
        assert session.scalar(select(func.count()).select_from(AlertEvent)) == 2
    assert sender.symbols == ["jm"]
    engine.dispose()


@pytest.mark.parametrize("frequency", ("1d", "1w"))
@pytest.mark.parametrize("recovers", (False, True), ids=("persistent", "recovers"))
def test_canonical_typed_evaluation_failure_preserves_history_and_can_recover(
    frequency: str,
    recovers: bool,
) -> None:
    trading_day = date(2026, 9, 11)
    bar_at = datetime(2026, 9, 11, 7, tzinfo=UTC)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    AlertRule.__table__.create(engine)
    AlertEvent.__table__.create(engine)
    with OrmSession(engine) as session:
        session.add(
            AlertRule(
                rule_code=HTDY_ALERT_RULE_CODE,
                enabled=True,
                scope_product_frequencies={"rb": [frequency]},
            )
        )
        session.commit()

    window = MarketReadWindow(
        "rb",
        "actual_dominant",
        frequency,
        trading_day,
        "RB2610",
        bar_at,
        (CanonicalBar(bar_at, trading_day, 1, 1, 1, 1, 1, None, None),),
        ("RB2610",),
    )

    class MarketRead:
        @staticmethod
        def latest_canonical_window(_query, *, trading_day, limit):
            assert trading_day == window.trading_day
            assert limit == 64
            return window

    class Evaluator:
        calls = 0

        def evaluate_candidates(self, _market_read, _window):
            self.calls += 1
            if self.calls == 1 or not recovers:
                raise AlertEvaluationError("ALERT_EVALUATION_FAILED")
            return ()

    evaluator = Evaluator()
    times = iter(
        (
            bar_at + timedelta(seconds=1),
            bar_at + timedelta(seconds=2),
        )
    )
    runtime = AlertRuntime(
        session_factory=lambda: OrmSession(engine),
        market_read_factory=lambda _session: MarketRead(),
        evaluators={HTDY_ALERT_RULE_CODE: evaluator},
        sender=object(),  # type: ignore[arg-type]
        operational_products=("rb",),
        taxonomy={},
        clock=lambda: next(times),
    )
    payload = {
        "reason": "canonical_updated",
        "trading_day": trading_day.isoformat(),
    }

    runtime.process_message("market:state", payload)
    first = runtime._current_runtime_status()["rule_status"][HTDY_ALERT_RULE_CODE]
    assert first["error_type"] == "evaluation_failed"
    first_failure = first["last_failure_at"]

    runtime.process_message("market:state", payload)
    second = runtime._current_runtime_status()["rule_status"][HTDY_ALERT_RULE_CODE]
    if recovers:
        assert second["last_failure_at"] == first_failure
    else:
        assert second["last_failure_at"] != first_failure
    assert second["error_type"] == (None if recovers else "evaluation_failed")
    assert second["last_evaluated_bar_at"] == (
        bar_at.isoformat() if recovers else None
    )
    engine.dispose()


@pytest.mark.parametrize("frequency", ("1d", "1w"))
def test_duplicate_canonical_update_neither_recommits_nor_resends(
    frequency: str,
) -> None:
    trading_day = date(2026, 9, 11)
    bar_at = datetime(2026, 9, 11, 7, tzinfo=UTC)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    AlertRule.__table__.create(engine)
    AlertEvent.__table__.create(engine)
    with OrmSession(engine) as session:
        session.add(
            AlertRule(
                rule_code=HTDY_ALERT_RULE_CODE,
                enabled=True,
                scope_product_frequencies={"rb": [frequency]},
            )
        )
        session.commit()

    window = MarketReadWindow(
        "rb",
        "actual_dominant",
        frequency,
        trading_day,
        "RB2610",
        bar_at,
        (CanonicalBar(bar_at, trading_day, 1, 1, 1, 1, 1, None, None),),
        ("RB2610",),
    )

    class MarketRead:
        @staticmethod
        def latest_canonical_window(_query, *, trading_day, limit):
            assert trading_day == window.trading_day
            assert limit == 64
            return window

    class Evaluator:
        @staticmethod
        def evaluate_candidates(_market_read, _window):
            return (
                AlertObservationCandidate(
                    window.cutoff,
                    window.trading_day,
                    window.contract,
                    ("buy",),
                ),
            )

    class Sender:
        calls = 0

        def send(self, _message):
            self.calls += 1
            return ProviderAcceptance("accepted")

    sender = Sender()
    runtime = AlertRuntime(
        session_factory=lambda: OrmSession(engine),
        market_read_factory=lambda _session: MarketRead(),
        evaluators={HTDY_ALERT_RULE_CODE: Evaluator()},
        sender=sender,
        operational_products=("rb",),
        taxonomy={"rb": SimpleNamespace(name="螺纹钢")},
        clock=lambda: bar_at + timedelta(seconds=1),
    )
    payload = {
        "reason": "canonical_updated",
        "trading_day": trading_day.isoformat(),
    }

    runtime.process_message("market:state", payload)
    runtime.process_message("market:state", payload)

    with OrmSession(engine) as session:
        assert session.scalar(select(func.count()).select_from(AlertEvent)) == 1
    assert sender.calls == 1
    engine.dispose()


@pytest.mark.parametrize("frequency", ("1d", "1w"))
def test_duplicate_canonical_update_does_not_clear_prior_status_failure(
    frequency: str,
) -> None:
    """A committed duplicate is a skip, not proof that the failed status write recovered."""
    trading_day = date(2026, 9, 11)
    bar_at = datetime(2026, 9, 11, 7, tzinfo=UTC)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    AlertRule.__table__.create(engine)
    AlertEvent.__table__.create(engine)
    with OrmSession(engine) as session:
        session.add(
            AlertRule(
                rule_code=HTDY_ALERT_RULE_CODE,
                enabled=True,
                scope_product_frequencies={"rb": [frequency]},
            )
        )
        session.commit()

    window = MarketReadWindow(
        "rb",
        "actual_dominant",
        frequency,
        trading_day,
        "RB2610",
        bar_at,
        (CanonicalBar(bar_at, trading_day, 1, 1, 1, 1, 1, None, None),),
        ("RB2610",),
    )

    class MarketRead:
        @staticmethod
        def latest_canonical_window(_query, *, trading_day, limit):
            assert trading_day == window.trading_day
            assert limit == 64
            return window

    class Evaluator:
        @staticmethod
        def evaluate_candidates(_market_read, _window):
            return (
                AlertObservationCandidate(
                    window.cutoff,
                    window.trading_day,
                    window.contract,
                    ("buy",),
                ),
            )

    class Sender:
        calls = 0

        def send(self, _message):
            self.calls += 1
            return ProviderAcceptance("accepted")

    class FailFirstRuleStatus:
        def __init__(self) -> None:
            self.status = empty_alert_runtime_status()
            self.failed = False

        def read(self):
            return self.status

        def update(self, changes):
            if "rule_status" in changes and not self.failed:
                self.failed = True
                raise ConnectionError("isolated first rule status failure")
            self.status = {**self.status, **changes}
            return self.status

    sender = Sender()
    status_store = FailFirstRuleStatus()
    runtime = AlertRuntime(
        session_factory=lambda: OrmSession(engine),
        market_read_factory=lambda _session: MarketRead(),
        evaluators={HTDY_ALERT_RULE_CODE: Evaluator()},
        sender=sender,
        operational_products=("rb",),
        taxonomy={"rb": SimpleNamespace(name="螺纹钢")},
        runtime_status_store=status_store,
        clock=lambda: bar_at + timedelta(seconds=1),
    )
    payload = {
        "reason": "canonical_updated",
        "trading_day": trading_day.isoformat(),
    }

    runtime.process_message("market:state", payload)
    failed_status = dict(runtime._current_runtime_status())
    assert failed_status["processing_error_type"] == "processing_failed"

    runtime.process_message("market:state", payload)

    assert runtime._current_runtime_status() == failed_status
    with OrmSession(engine) as session:
        assert session.scalar(select(func.count()).select_from(AlertEvent)) == 1
    assert sender.calls == 0
    engine.dispose()
