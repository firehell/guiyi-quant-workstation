from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.market_data.domain import BarFrequency
from app.market_data.market_data_service import MarketDataError
from app.market_data.subing_calibration import SubingCalibrationError
from app.market_data.subing_lifecycle import (
    EntryProgress,
    LifecycleAvailability,
    LifecycleStage,
    SubingLifecycleSnapshot,
    SubingOpportunityKey,
)
from app.market_data.subing_read_service import SubingReadSnapshot
from app.market_data.subing_research import (
    MacdCross,
    PriceSide,
    SubingConditionResult,
    SubingConditionState,
    SubingDirection,
    SubingFactorResult,
    SubingFactorSnapshot,
    SubingFactorStatus,
    SubingSignalEvaluation,
    SubingSignalResolution,
    SubingSignalStatus,
)


class _FakeSubingReadService:
    def __init__(self, failure: MarketDataError | None = None) -> None:
        self._failure = failure

    def snapshot(self, request, now) -> SubingReadSnapshot:
        if self._failure is not None:
            raise self._failure
        factor = SubingFactorSnapshot(
            timeframe=request.frequency,
            bar_end=datetime(2026, 8, 13, 2, 25, tzinfo=UTC),
            trading_day=date(2026, 8, 13),
            contract="JM2609",
            segment_start_trading_day=date(2026, 8, 3),
            bar_source="live",
            close=Decimal("100.5"),
            ema21=Decimal("99.5"),
            price_side=PriceSide.ABOVE,
            slope_5_raw=Decimal("0.12"),
            slope_10_raw=Decimal("0.08"),
            slope_5_bps_per_bar=Decimal("12.06"),
            slope_10_bps_per_bar=Decimal("8.04"),
            macd_dif=Decimal("0.7"),
            macd_dea=Decimal("0.5"),
            macd_histogram=Decimal("0.4"),
            macd_cross=MacdCross.GOLDEN,
            macd_cross_level=Decimal("0.6"),
            macd_zero_distance_abs=Decimal("0.6"),
            macd_zero_distance_bps=Decimal("59.70"),
            volume=Decimal("342"),
            previous_volume=Decimal("100"),
            volume_ratio_prev=Decimal("3.42"),
        )
        lifecycle = (
            _intraday_only_lifecycle()
            if request.frequency is BarFrequency.D1
            else _setup_lifecycle()
        )
        return SubingReadSnapshot(
            symbol=request.symbol,
            product_name="焦煤",
            frequency=request.frequency,
            actual_contract="JM2609",
            dominant_mapping_date=date(2026, 8, 13),
            segment_start_trading_day=date(2026, 8, 3),
            source_mode="canonical_live",
            live_observation="available",
            live_reason=None,
            macd_policy_id="web_macd_legacy_v1",
            signal_macd_policy_id="subing_macd_sma_window_scale2_v1",
            calibration_state="accepted",
            calibration_id="subing_intraday_v1",
            primary=SubingFactorResult(SubingFactorStatus.READY, factor),
            companion=SubingFactorResult(
                SubingFactorStatus.INSUFFICIENT_DATA,
                None,
            ),
            primary_signal=_matched_signal(request.frequency),
            resolved_signal=_matched_signal(request.frequency),
            lifecycle=lifecycle,
        )


def test_subing_api_returns_factor_and_distinct_primary_resolved_signals(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.api.market.build_subing_read_service",
        lambda _session: _FakeSubingReadService(),
        raising=False,
    )

    response = TestClient(app).get(
        "/api/v1/market/research/subing",
        params={"symbol": "JM", "frequency": "5m"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["symbol"] == "jm"
    assert payload["actual_contract"] == "JM2609"
    assert payload["frequency"] == "5m"
    assert payload["calibration_state"] == "accepted"
    assert payload["calibration_id"] == "subing_intraday_v1"
    assert payload["macd_policy_id"] == "web_macd_legacy_v1"
    assert payload["signal_macd_policy_id"] == "subing_macd_sma_window_scale2_v1"
    assert payload["primary"]["status"] in {"ready", "insufficient_data"}
    assert payload["primary"]["snapshot"]["slope_5_bps_per_bar"] == "12.06"
    assert payload["primary"]["snapshot"]["volume_ratio_prev"] == "3.42"
    assert payload["companion"] == {
        "status": "insufficient_data",
        "snapshot": None,
    }
    assert payload["primary_signal"] == {
        "status": "matched",
        "direction": "long",
        "trigger_timeframe": "5m",
        "lower_tf_confirmation": False,
        "resolution": None,
        "conditions": [{"code": "PRIMARY_MACD_CROSS", "state": "pass"}],
        "error_code": None,
    }
    assert payload["resolved_signal"] == payload["primary_signal"]
    assert set(payload) == {
        "symbol",
        "product_name",
        "frequency",
        "actual_contract",
        "dominant_mapping_date",
        "segment_start_trading_day",
        "source_mode",
        "live_observation",
        "live_reason",
        "macd_policy_id",
        "signal_macd_policy_id",
        "calibration_state",
        "calibration_id",
        "primary",
        "companion",
        "primary_signal",
        "resolved_signal",
        "lifecycle",
    }
    condition_codes = {
        condition["code"] for condition in payload["primary_signal"]["conditions"]
    }
    assert not any("ZERO" in code or "BAND" in code for code in condition_codes)


def test_subing_api_adds_a_research_only_lifecycle_projection(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.market.build_subing_read_service",
        lambda _session: _FakeSubingReadService(),
        raising=False,
    )

    payload = (
        TestClient(app)
        .get(
            "/api/v1/market/research/subing",
            params={"symbol": "jm", "frequency": "5m"},
        )
        .json()
    )

    assert payload["lifecycle"] == {
        "formula_version": "subing_lifecycle_v2_structure_binding_v1",
        "policy_id": "subing_lifecycle_v2_research_v1",
        "research_only": True,
        "observed_at": "2026-08-13T02:25:00Z",
        "anchor_bar_end": "2026-08-13T02:15:00Z",
        "availability": "ready",
        "unavailable_reason": None,
        "direction": "long",
        "stage": "setup_armed",
        "opportunity_key": (
            "subing_lifecycle_v2_research_v1:JM:JM2609:2026-08-03:long:"
            "2026-08-13T02:20:00+00:00"
        ),
        "entry_progress": "waiting_trigger",
        "trigger_kind": None,
        "trigger_timeframe": None,
        "triggered_at": None,
        "confirmation_source": None,
        "confirmed_at": None,
        "hold_count": 0,
        "hold_required": 3,
        "trigger_reference_pivot": None,
        "bound_reference_pivot": None,
        "rebreak_reference_price": None,
        "retest_at": None,
        "retest_rebreak_count": 0,
        "volume_ratio_prev": "3.42",
        "open_interest_delta": "12.50",
        "current_risk_codes": [],
        "risk_progress": None,
        "lower_tf_risk_count": 0,
        "last_confirmed_stage": "setup_armed",
        "last_confirmed_at": "2026-08-13T02:25:00Z",
        "latest_transition": None,
        "crossed_trading_day": False,
        "boundary_reset": None,
        "formal_v1_matched": False,
    }
    assert "result_codes" not in payload


def test_subing_api_uses_one_lifecycle_identity_for_5m_and_15m(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.market.build_subing_read_service",
        lambda _session: _FakeSubingReadService(),
        raising=False,
    )
    client = TestClient(app)

    five_minute = client.get(
        "/api/v1/market/research/subing",
        params={"symbol": "jm", "frequency": "5m"},
    ).json()
    fifteen_minute = client.get(
        "/api/v1/market/research/subing",
        params={"symbol": "jm", "frequency": "15m"},
    ).json()

    assert five_minute["lifecycle"]["opportunity_key"] == fifteen_minute["lifecycle"][
        "opportunity_key"
    ]
    assert five_minute["lifecycle"]["stage"] == fifteen_minute["lifecycle"]["stage"]


def test_subing_api_projects_daily_lifecycle_as_intraday_only(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.market.build_subing_read_service",
        lambda _session: _FakeSubingReadService(),
        raising=False,
    )

    payload = (
        TestClient(app)
        .get(
            "/api/v1/market/research/subing",
            params={"symbol": "jm", "frequency": "1d"},
        )
        .json()
    )

    assert payload["lifecycle"]["availability"] == "unavailable"
    assert payload["lifecycle"]["unavailable_reason"] == "SUBING_LIFECYCLE_INTRADAY_ONLY"
    assert payload["lifecycle"]["research_only"] is True


@pytest.mark.parametrize("requested", [BarFrequency.M5, BarFrequency.M15])
def test_subing_api_keeps_requested_primary_when_resolved_15m_wins(
    monkeypatch,
    requested: BarFrequency,
) -> None:
    class _ResolvedService(_FakeSubingReadService):
        def snapshot(self, request, now) -> SubingReadSnapshot:
            snapshot = super().snapshot(request, now)
            return replace(
                snapshot,
                resolved_signal=SubingSignalEvaluation(
                    status=SubingSignalStatus.MATCHED,
                    direction=SubingDirection.LONG,
                    trigger_timeframe=BarFrequency.M15,
                    bar_end=datetime(2026, 8, 13, 2, 30, tzinfo=UTC),
                    lower_tf_confirmation=True,
                    resolution=SubingSignalResolution.HIGHER_TIMEFRAME_WINS,
                    conditions=(),
                ),
            )

    monkeypatch.setattr(
        "app.api.market.build_subing_read_service",
        lambda _session: _ResolvedService(),
        raising=False,
    )

    payload = (
        TestClient(app)
        .get(
            "/api/v1/market/research/subing",
            params={"symbol": "jm", "frequency": requested.value},
        )
        .json()
    )

    assert payload["frequency"] == requested.value
    assert payload["primary_signal"]["trigger_timeframe"] == requested.value
    assert payload["resolved_signal"]["trigger_timeframe"] == "15m"
    assert payload["resolved_signal"]["lower_tf_confirmation"] is True
    assert payload["resolved_signal"]["resolution"] == "higher_timeframe_wins"


def test_subing_api_exposes_only_symbol_and_frequency_query_parameters() -> None:
    operation = app.openapi()["paths"]["/api/v1/market/research/subing"]["get"]

    assert [parameter["name"] for parameter in operation["parameters"]] == [
        "symbol",
        "frequency",
    ]


def test_subing_api_rejects_unsupported_frequency(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.market.build_subing_read_service",
        lambda _session: _FakeSubingReadService(),
        raising=False,
    )

    response = TestClient(app).get(
        "/api/v1/market/research/subing",
        params={"symbol": "jm", "frequency": "30m"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "INVALID_SUBING_REQUEST"}}


def test_subing_api_rejects_malformed_symbol_before_service_lookup(monkeypatch) -> None:
    class _UnexpectedService:
        def snapshot(self, request, now):
            raise AssertionError("malformed symbols must not reach dominant lookup")

    monkeypatch.setattr(
        "app.api.market.build_subing_read_service",
        lambda _session: _UnexpectedService(),
        raising=False,
    )

    response = TestClient(app).get(
        "/api/v1/market/research/subing",
        params={"symbol": "###", "frequency": "5m"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "INVALID_SUBING_REQUEST"}}


def test_subing_api_maps_market_errors_without_internal_details(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.market.build_subing_read_service",
        lambda _session: _FakeSubingReadService(
            MarketDataError("DOMINANT_CONTEXT_MISSING")
        ),
        raising=False,
    )

    response = TestClient(app).get(
        "/api/v1/market/research/subing",
        params={"symbol": "jm", "frequency": "15m"},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "DOMINANT_CONTEXT_MISSING"}}


def test_subing_api_maps_malformed_calibration_to_stable_fail_closed_error(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.api.market.build_subing_read_service",
        lambda _session: (_ for _ in ()).throw(SubingCalibrationError()),
        raising=False,
    )

    response = TestClient(app, raise_server_exceptions=False).get(
        "/api/v1/market/research/subing",
        params={"symbol": "jm", "frequency": "5m"},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "SUBING_CALIBRATION_INVALID"}}


def _matched_signal(timeframe: BarFrequency) -> SubingSignalEvaluation:
    return SubingSignalEvaluation(
        status=SubingSignalStatus.MATCHED,
        direction=SubingDirection.LONG,
        trigger_timeframe=timeframe,
        bar_end=datetime(2026, 8, 13, 2, 25, tzinfo=UTC),
        lower_tf_confirmation=False,
        resolution=None,
        conditions=(
            SubingConditionResult(
                code="PRIMARY_MACD_CROSS",
                state=SubingConditionState.PASS,
            ),
        ),
    )


def _setup_lifecycle() -> SubingLifecycleSnapshot:
    return SubingLifecycleSnapshot(
        formula_version="subing_lifecycle_v2_structure_binding_v1",
        policy_id="subing_lifecycle_v2_research_v1",
        research_only=True,
        observed_at=datetime(2026, 8, 13, 2, 25, tzinfo=UTC),
        anchor_bar_end=datetime(2026, 8, 13, 2, 15, tzinfo=UTC),
        availability=LifecycleAvailability.READY,
        unavailable_reason=None,
        direction=SubingDirection.LONG,
        stage=LifecycleStage.SETUP_ARMED,
        opportunity_key=SubingOpportunityKey(
            policy_id="subing_lifecycle_v2_research_v1",
            symbol="JM",
            contract="JM2609",
            segment_start_trading_day=date(2026, 8, 3),
            direction=SubingDirection.LONG,
            origin_at=datetime(2026, 8, 13, 2, 20, tzinfo=UTC),
        ),
        entry_progress=EntryProgress.WAITING_TRIGGER,
        volume_ratio_prev=Decimal("3.42"),
        open_interest_delta=Decimal("12.50"),
        last_confirmed_stage=LifecycleStage.SETUP_ARMED,
        last_confirmed_at=datetime(2026, 8, 13, 2, 25, tzinfo=UTC),
    )


def _intraday_only_lifecycle() -> SubingLifecycleSnapshot:
    return SubingLifecycleSnapshot(
        formula_version="subing_lifecycle_v2_structure_binding_v1",
        policy_id="subing_lifecycle_v2_research_v1",
        research_only=True,
        observed_at=datetime(2026, 8, 13, 2, 25, tzinfo=UTC),
        anchor_bar_end=None,
        availability=LifecycleAvailability.UNAVAILABLE,
        unavailable_reason="SUBING_LIFECYCLE_INTRADAY_ONLY",
        direction=SubingDirection.NONE,
        stage=LifecycleStage.IDLE,
        opportunity_key=None,
        entry_progress=None,
    )
