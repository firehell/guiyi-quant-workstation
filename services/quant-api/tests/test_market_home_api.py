from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app
from app.market_data.market_home_overview import (
    MarketHomeItem,
    MarketHomeOverviewError,
    MarketHomeOverviewSnapshot,
    MarketHomeSectorSummary,
    MarketHomeSummary,
)
from app.market_data.market_home_projection import market_home_response
from app.schemas.market import MarketHomeOverviewResponse


def test_home_overview_is_one_bulk_typed_response(monkeypatch) -> None:
    projection = _FakeProjection(market_home_response(_snapshot()))
    monkeypatch.setattr(
        "app.api.market.build_market_home_projection", lambda _session: projection,
        raising=False,
    )

    response = TestClient(app).get("/api/v1/market/research/home-overview")

    assert response.status_code == 200
    assert projection.calls == 1
    assert response.json() == {
        "status": "ready",
        "target_as_of": "2025-02-11",
        "data_as_of": "2025-02-11",
        "freshness": "fresh",
        "active_count": 1,
        "participant_count": 1,
        "stale_count": 0,
        "unavailable_count": 0,
        "summary": {
            "price_up_count": 1,
            "price_down_count": 0,
            "price_flat_count": 0,
            "daily_up_count": 1,
            "daily_down_count": 0,
            "daily_neutral_count": 0,
            "daily_unavailable_count": 0,
            "aligned_up_count": 1,
            "aligned_down_count": 0,
        },
        "items": [
            {
                "symbol": "jm",
                "product_name": "焦煤",
                "sector": "black",
                "exchange": "DCE",
                "actual_contract": "JM2505",
                "dominant_mapping_date": "2025-02-11",
                "data_as_of": "2025-02-11",
                "close": "110",
                "price_change_1d": "0.1",
                "price_change_5d": None,
                "volume_ratio20": "1.2",
                "oi_change_1d": None,
                "atr14_percentile252": None,
                "daily_trend": "up",
                "weekly_trend": "up",
                "reason_codes": [
                    "price_up",
                    "daily_up",
                    "weekly_up",
                    "periods_aligned_up",
                ],
            }
        ],
        "sectors": [
            {
                "sector": "black",
                "active_count": 1,
                "participant_count": 1,
                "median_price_change_1d": "0.1",
            }
        ],
    }


def test_home_overview_maps_domain_failure_to_typed_409(monkeypatch) -> None:
    projection = _FakeProjection(
        MarketHomeOverviewError("MARKET_HOME_DATA_INTEGRITY_ERROR")
    )
    monkeypatch.setattr(
        "app.api.market.build_market_home_projection", lambda _session: projection,
        raising=False,
    )

    response = TestClient(app).get("/api/v1/market/research/home-overview")

    assert response.status_code == 409
    assert response.json() == {
        "detail": {"code": "MARKET_HOME_DATA_INTEGRITY_ERROR"}
    }


def test_home_overview_maps_authority_loader_failure_to_typed_409(monkeypatch) -> None:
    projection = _FakeProjection(
        MarketHomeOverviewError("MARKET_HOME_AUTHORITY_UNAVAILABLE")
    )
    monkeypatch.setattr(
        "app.api.market.build_market_home_projection",
        lambda _session: projection,
        raising=False,
    )

    response = TestClient(app).get("/api/v1/market/research/home-overview")

    assert response.status_code == 409
    assert response.json() == {
        "detail": {"code": "MARKET_HOME_AUTHORITY_UNAVAILABLE"}
    }


class _FakeProjection:
    def __init__(self, value: MarketHomeOverviewResponse | Exception) -> None:
        self.value = value
        self.calls = 0

    def read(self) -> MarketHomeOverviewResponse:
        self.calls += 1
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


def _snapshot() -> MarketHomeOverviewSnapshot:
    as_of = date(2025, 2, 11)
    return MarketHomeOverviewSnapshot(
        status="ready",
        target_as_of=as_of,
        data_as_of=as_of,
        freshness="fresh",
        active_count=1,
        participant_count=1,
        stale_count=0,
        unavailable_count=0,
        summary=MarketHomeSummary(
            price_up_count=1,
            price_down_count=0,
            price_flat_count=0,
            daily_up_count=1,
            daily_down_count=0,
            daily_neutral_count=0,
            daily_unavailable_count=0,
            aligned_up_count=1,
            aligned_down_count=0,
        ),
        items=(
            MarketHomeItem(
                symbol="jm",
                product_name="焦煤",
                sector="black",
                exchange="DCE",
                actual_contract="JM2505",
                dominant_mapping_date=as_of,
                data_as_of=as_of,
                close=Decimal("110"),
                price_change_1d=Decimal("0.1"),
                price_change_5d=None,
                volume_ratio20=Decimal("1.2"),
                oi_change_1d=None,
                atr14_percentile252=None,
                daily_trend="up",
                weekly_trend="up",
                reason_codes=(
                    "price_up",
                    "daily_up",
                    "weekly_up",
                    "periods_aligned_up",
                ),
            ),
        ),
        sectors=(
            MarketHomeSectorSummary(
                sector="black",
                active_count=1,
                participant_count=1,
                median_price_change_1d=Decimal("0.1"),
            ),
        ),
    )
