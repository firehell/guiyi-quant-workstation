from __future__ import annotations

from datetime import UTC, datetime

from app.data_core.contracts import BarFrequency, BarQuery, DatasetKind
from app.services.market_data_service import MarketDataService


class _ExactReader:
    def __init__(self) -> None:
        self.seen: BarQuery | None = None

    def get_bars(self, query: BarQuery) -> dict[str, object]:
        self.seen = query
        return {"identity": query}


def test_facade_has_no_profile_or_live_compatibility_branch() -> None:
    reader = _ExactReader()
    query = BarQuery(
        dataset_kind=DatasetKind.ACTUAL_DOMINANT,
        symbol="rb",
        contract_or_series="RB2610",
        frequency=BarFrequency.M15,
        start=datetime(2026, 7, 1, tzinfo=UTC),
        end=datetime(2026, 7, 2, tzinfo=UTC),
    )
    result = MarketDataService(
        object(),  # type: ignore[arg-type]
        canonical_reader=reader,
    ).get_bars(query)

    assert result == {"identity": query}
    assert reader.seen == query
