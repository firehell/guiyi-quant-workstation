from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from app.market_data.domain import CanonicalBar, MarketSeriesResult


def test_market_series_result_has_no_digest_contract() -> None:
    bar = CanonicalBar(datetime(2025, 1, 2, 7, tzinfo=UTC), date(2025, 1, 2), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"), None, None)
    result = MarketSeriesResult(
        request_identity={"series_kind": "continuous"},
        bars=(bar,),
        coverage=(bar.bar_end, bar.bar_end),
        resolved_contract_segments=(),
    )

    assert result.coverage == (bar.bar_end, bar.bar_end)
    assert not hasattr(result, "partition_digests")
    assert not hasattr(result, "main_map_digest")
