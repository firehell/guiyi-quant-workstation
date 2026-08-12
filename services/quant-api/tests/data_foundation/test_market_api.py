from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import app
from app.market_data.domain import (
    CanonicalBar,
    MarketSeriesPageResult,
    ResolvedContractSegment,
    SeriesKind,
)
from app.market_data.market_data_service import MarketDataError


class FakeService:
    def query_page(self, request):
        bar = CanonicalBar(
            datetime(2025, 1, 2, 7, tzinfo=UTC),
            date(2025, 1, 2),
            Decimal("100"),
            Decimal("101"),
            Decimal("99"),
            Decimal("100"),
            Decimal("10"),
            Decimal("1000"),
            Decimal("20"),
        )
        return MarketSeriesPageResult(
            request_identity={
                "series_kind": request.series_kind.value,
                "symbol": request.symbol,
                "contract": request.contract,
                "frequency": request.frequency.value,
                "before": request.before.isoformat() if request.before else None,
                "limit": request.limit,
            },
            bars=(bar,),
            canonical_coverage=(bar.bar_end, bar.bar_end),
            has_more_before=True,
            next_before=bar.bar_end,
            resolved_contract_segments=(
                ResolvedContractSegment("JM2509", date(2025, 1, 2), date(2025, 1, 2)),
            ),
        )


def test_market_bars_page_has_cursor_contract_and_default_limit(monkeypatch) -> None:
    fake = FakeService()
    monkeypatch.setattr("app.api.market.build_market_data_service", lambda _session: fake)

    response = TestClient(app).get(
        "/api/v1/market/bars/page",
        params={
            "series_kind": "actual_dominant",
            "symbol": "jm",
            "frequency": "1d",
            "before": "2025-01-03T00:00:00Z",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "request",
        "bars",
        "canonical_coverage",
        "page",
        "resolved_contract_segments",
    }
    assert payload["request"]["limit"] == 1200
    assert payload["request"]["before"] == "2025-01-03T00:00:00+00:00"
    assert payload["page"] == {
        "has_more_before": True,
        "next_before": "2025-01-02T07:00:00Z",
    }


def test_market_bars_page_validates_contract_and_limit(monkeypatch) -> None:
    monkeypatch.setattr("app.api.market.build_market_data_service", lambda _session: FakeService())
    client = TestClient(app)
    base = {"symbol": "jm", "frequency": "1d"}

    missing_contract = client.get(
        "/api/v1/market/bars/page",
        params={**base, "series_kind": "contract"},
    )
    invalid_limit = client.get(
        "/api/v1/market/bars/page",
        params={**base, "series_kind": "continuous", "limit": 2001},
    )

    assert missing_contract.status_code == 422
    assert invalid_limit.status_code == 422


class FakeResearchService:
    def __init__(self, *, failure: MarketDataError | None = None) -> None:
        self.failure = failure
        self.requests = []

    def product_snapshot(self, identity):
        self.requests.append(identity)
        if self.failure is not None:
            raise self.failure
        bar = CanonicalBar(
            datetime(2025, 1, 2, 7, tzinfo=UTC),
            date(2025, 1, 2),
            Decimal("100"),
            Decimal("101"),
            Decimal("99"),
            Decimal("100"),
            Decimal("10"),
            Decimal("1000"),
            Decimal("20"),
        )
        return SimpleNamespace(
            symbol="jm",
            product_name="焦煤",
            sector="black",
            exchange="DCE",
            series_kind=SeriesKind.ACTUAL_DOMINANT,
            contract=None,
            as_of=date(2025, 1, 2),
            current_dominant="JM2509",
            dominant_mapping_date=date(2025, 1, 2),
            metrics=SimpleNamespace(
                daily_trend="up",
                weekly_trend="neutral",
                position20=Decimal("0.5"),
                distance_to_20d_high=Decimal("-0.1"),
                distance_to_20d_low=Decimal("0.2"),
                volume_ratio20=Decimal("2"),
                oi_change_1d=Decimal("0.1"),
                turnover_change_5d=Decimal("0.3"),
                atr14_percentile252=Decimal("0.8"),
            ),
            recent_daily=(bar,),
        )


def test_product_research_api_supports_actual_dominant_and_continuous(monkeypatch) -> None:
    fake = FakeResearchService()
    monkeypatch.setattr("app.api.market.build_market_research_service", lambda _session: fake, raising=False)
    client = TestClient(app)

    actual = client.get(
        "/api/v1/market/research/product",
        params={"symbol": "jm", "series_kind": "actual_dominant"},
    )
    continuous = client.get(
        "/api/v1/market/research/product",
        params={"symbol": "jm", "series_kind": "continuous"},
    )

    assert actual.status_code == 200
    assert continuous.status_code == 200
    assert actual.json()["symbol"] == "jm"
    assert actual.json()["recent_daily"][0]["close"] == "100"
    assert [item.series_kind.value for item in fake.requests] == ["actual_dominant", "continuous"]


def test_product_research_api_rejects_contract_without_contract(monkeypatch) -> None:
    monkeypatch.setattr("app.api.market.build_market_research_service", lambda _session: FakeResearchService(), raising=False)

    response = TestClient(app).get(
        "/api/v1/market/research/product",
        params={"symbol": "jm", "series_kind": "contract"},
    )

    assert response.status_code == 422


def test_product_research_api_maps_market_errors_without_internal_details(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.market.build_market_research_service",
        lambda _session: FakeResearchService(failure=MarketDataError("QUERY_WINDOW_EMPTY")),
        raising=False,
    )

    response = TestClient(app).get(
        "/api/v1/market/research/product",
        params={"symbol": "jm", "series_kind": "actual_dominant"},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "QUERY_WINDOW_EMPTY"}}


class FakeRadarService:
    def snapshot(self):
        metrics = SimpleNamespace(
            price_change_1d=Decimal("0.03"),
            price_change_5d=Decimal("0.05"),
            volume_ratio20=Decimal("1.7"),
            oi_change_1d=Decimal("0.08"),
            atr14_percentile252=Decimal("0.82"),
            position20=Decimal("0.91"),
        )
        item = SimpleNamespace(
            symbol="jm",
            product_name="焦煤",
            sector="black",
            metrics=metrics,
            turnover=Decimal("1000"),
            reason_codes=(
                "price_move_up",
                "volume_expansion",
                "oi_increase",
                "high_volatility",
            ),
        )
        sector = SimpleNamespace(
            sector="black",
            total_count=1,
            participant_count=1,
            up_count=1,
            down_count=0,
            median_price_change_1d=Decimal("0.03"),
            attention_count=1,
        )
        return SimpleNamespace(
            status="ready",
            expected_as_of=date(2025, 1, 2),
            active_count=60,
            participant_count=60,
            stale=(),
            unavailable=(),
            items=(item,),
            attention=(item,),
            sector_summary=(sector,),
        )


def test_market_radar_api_returns_explicit_freshness_and_transparent_reasons(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.market.build_market_radar_service",
        lambda _session: FakeRadarService(),
        raising=False,
    )

    response = TestClient(app).get("/api/v1/market/research/radar")

    assert response.status_code == 200
    payload = response.json()
    assert payload["expected_as_of"] == "2025-01-02"
    assert payload["active_count"] == 60
    assert payload["participant_count"] == 60
    assert payload["summary"] == {
        "up_count": 1,
        "down_count": 0,
        "volume_expansion_count": 1,
        "oi_increase_count": 1,
        "high_volatility_count": 1,
    }
    assert payload["attention"][0]["reason_codes"] == [
        "price_move_up",
        "volume_expansion",
        "oi_increase",
        "high_volatility",
    ]
