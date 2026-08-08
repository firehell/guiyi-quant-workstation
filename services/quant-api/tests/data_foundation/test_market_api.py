from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app
from app.market_data.domain import (
    CanonicalBar,
    DatasetKey,
    MarketSeriesResult,
    PartitionDigest,
    ResolvedContractSegment,
)


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
        key = DatasetKey("contract", "jm", "JM2509", "1d")
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
            partition_digests=(PartitionDigest(key, 2025, 1, "a" * 64, "b" * 64),),
            resolved_contract_segments=(
                ResolvedContractSegment("JM2509", date(2025, 1, 2), date(2025, 1, 2)),
            ),
            main_map_digest="c" * 64,
        )


def test_market_bars_uses_new_series_query_and_has_no_legacy_fields(monkeypatch) -> None:
    monkeypatch.setattr("app.api.market.build_market_data_service", lambda _session: FakeService())
    client = TestClient(app)

    response = client.get(
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
    assert set(payload) == {
        "request",
        "bars",
        "coverage",
        "partition_digests",
        "resolved_contract_segments",
        "main_map_digest",
    }
    serialized = response.text
    for retired in (
        "profile_id",
        "data_role",
        "market_data_file_id",
        "binding_snapshot",
        "quality_report",
        "access_mode",
        "strict_research_ready",
    ):
        assert retired not in serialized


def test_contract_query_requires_contract_and_continuous_rejects_it(monkeypatch) -> None:
    monkeypatch.setattr("app.api.market.build_market_data_service", lambda _session: FakeService())
    client = TestClient(app)
    base = {
        "symbol": "jm",
        "frequency": "1d",
        "start": "2025-01-01T00:00:00Z",
        "end": "2025-01-03T00:00:00Z",
    }

    missing = client.get(
        "/api/v1/market/bars/canonical",
        params={**base, "series_kind": "contract"},
    )
    ambiguous = client.get(
        "/api/v1/market/bars/canonical",
        params={**base, "series_kind": "continuous", "contract": "JM2509"},
    )

    assert missing.status_code == 422
    assert ambiguous.status_code == 422
