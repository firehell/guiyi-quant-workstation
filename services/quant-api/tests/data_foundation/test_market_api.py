from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app
from app.market_data.domain import CanonicalBar, MarketSeriesResult, ResolvedContractSegment


class FakeService:
    def query(self, request):
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
        return MarketSeriesResult(
            request_identity={
                "series_kind": request.series_kind.value,
                "symbol": request.symbol,
                "contract": request.contract,
                "frequency": request.frequency.value,
                "start": request.start.isoformat(),
                "end": request.end.isoformat(),
            },
            bars=(bar,),
            coverage=(bar.bar_end, bar.bar_end),
            resolved_contract_segments=(
                ResolvedContractSegment("JM2509", date(2025, 1, 2), date(2025, 1, 2)),
            ),
        )


def test_market_bars_has_only_minimal_query_contract(monkeypatch) -> None:
    monkeypatch.setattr("app.api.market.build_market_data_service", lambda _session: FakeService())

    response = TestClient(app).get(
        "/api/v1/market/bars/canonical",
        params={
            "series_kind": "actual_dominant",
            "symbol": "jm",
            "frequency": "1d",
            "start": "2025-01-01T00:00:00Z",
            "end": "2025-01-03T00:00:00Z",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"request", "bars", "coverage", "resolved_contract_segments"}
    assert payload["coverage"] == {
        "start": "2025-01-02T07:00:00Z",
        "end": "2025-01-02T07:00:00Z",
    }
    assert payload["request"]["contract"] is None
    serialized = response.text.lower()
    assert "digest" not in serialized
    assert "manifest" not in serialized


def test_contract_query_requires_contract_and_continuous_rejects_it(monkeypatch) -> None:
    monkeypatch.setattr("app.api.market.build_market_data_service", lambda _session: FakeService())
    client = TestClient(app)
    base = {
        "symbol": "jm",
        "frequency": "1d",
        "start": "2025-01-01T00:00:00Z",
        "end": "2025-01-03T00:00:00Z",
    }

    missing = client.get("/api/v1/market/bars/canonical", params={**base, "series_kind": "contract"})
    ambiguous = client.get(
        "/api/v1/market/bars/canonical",
        params={**base, "series_kind": "continuous", "contract": "JM2509"},
    )

    assert missing.status_code == 422
    assert ambiguous.status_code == 422
