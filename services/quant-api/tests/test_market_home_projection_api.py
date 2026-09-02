from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app
from app.market_data.market_home_overview import MarketHomeOverviewError
from app.schemas.market import (
    MarketHomeItemOut,
    MarketHomeOverviewResponse,
    MarketHomeSectorOut,
    MarketHomeSummaryOut,
)


class _Projection:
    def __init__(self, value: MarketHomeOverviewResponse | Exception) -> None:
        self.value = value
        self.read_calls = 0

    def read(self) -> MarketHomeOverviewResponse:
        self.read_calls += 1
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


def _response() -> MarketHomeOverviewResponse:
    as_of = date(2026, 9, 2)
    return MarketHomeOverviewResponse(
        status="ready",
        target_as_of=as_of,
        data_as_of=as_of,
        freshness="fresh",
        active_count=1,
        participant_count=1,
        stale_count=0,
        unavailable_count=0,
        summary=MarketHomeSummaryOut(
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
        items=[
            MarketHomeItemOut(
                symbol="jm",
                product_name="焦煤",
                sector="black",
                exchange="DCE",
                actual_contract="JM2701",
                dominant_mapping_date=as_of,
                data_as_of=as_of,
                close=Decimal("1234.5"),
                price_change_1d=Decimal("0.01"),
                price_change_5d=None,
                volume_ratio20=Decimal("1.2"),
                oi_change_1d=None,
                atr14_percentile252=None,
                daily_trend="up",
                weekly_trend="up",
                reason_codes=["price_up", "periods_aligned_up"],
            )
        ],
        sectors=[
            MarketHomeSectorOut(
                sector="black",
                active_count=1,
                participant_count=1,
                median_price_change_1d=Decimal("0.01"),
            )
        ],
    )


def test_home_overview_router_reads_projection_once(monkeypatch) -> None:
    projection = _Projection(_response())
    monkeypatch.setattr(
        "app.api.market.build_market_home_projection",
        lambda _session: projection,
        raising=False,
    )

    response = TestClient(app).get("/api/v1/market/research/home-overview")

    assert response.status_code == 200
    assert projection.read_calls == 1
    assert response.json()["target_as_of"] == "2026-09-02"


def test_home_overview_router_preserves_typed_compute_error(monkeypatch) -> None:
    projection = _Projection(
        MarketHomeOverviewError("MARKET_HOME_DATA_INTEGRITY_ERROR")
    )
    monkeypatch.setattr(
        "app.api.market.build_market_home_projection",
        lambda _session: projection,
        raising=False,
    )

    response = TestClient(app).get("/api/v1/market/research/home-overview")

    assert response.status_code == 409
    assert response.json() == {
        "detail": {"code": "MARKET_HOME_DATA_INTEGRITY_ERROR"}
    }
