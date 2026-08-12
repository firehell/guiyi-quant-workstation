from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app
from app.market_data.domain import (
    CanonicalBar,
    MarketSeriesPageResult,
    ResolvedContractSegment,
)


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
