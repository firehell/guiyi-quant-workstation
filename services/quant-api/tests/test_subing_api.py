from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app
from app.market_data.market_data_service import MarketDataError
from app.market_data.subing_read_service import SubingReadSnapshot
from app.market_data.subing_research import (
    MacdCross,
    PriceSide,
    SubingFactorResult,
    SubingFactorSnapshot,
    SubingFactorStatus,
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
            calibration_state="pending",
            primary=SubingFactorResult(SubingFactorStatus.READY, factor),
            companion=SubingFactorResult(
                SubingFactorStatus.INSUFFICIENT_DATA,
                None,
            ),
        )


def test_subing_api_returns_nested_factor_contract_without_signal(monkeypatch) -> None:
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
    assert payload["calibration_state"] == "pending"
    assert payload["primary"]["status"] in {"ready", "insufficient_data"}
    assert payload["primary"]["snapshot"]["slope_5_bps_per_bar"] == "12.06"
    assert payload["primary"]["snapshot"]["volume_ratio_prev"] == "3.42"
    assert payload["companion"] == {
        "status": "insufficient_data",
        "snapshot": None,
    }
    assert "signal" not in payload


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
