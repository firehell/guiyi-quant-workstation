from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.data_core.contracts import BarFrequency, BarQuery, DataCoreError, DatasetKind
from app.services.market_data_service import MarketDataService


def _query() -> BarQuery:
    return BarQuery(
        dataset_kind=DatasetKind.CONTINUOUS,
        symbol="jm",
        contract_or_series="JM.MAIN",
        frequency=BarFrequency.M1,
        start=datetime(2026, 7, 1, tzinfo=UTC),
        end=datetime(2026, 7, 2, tzinfo=UTC),
    )


class _Reader:
    def __init__(self, result: object) -> None:
        self.result = result
        self.queries: list[BarQuery] = []

    def get_bars(self, query: BarQuery) -> object:
        self.queries.append(query)
        return self.result


def test_market_data_service_forwards_one_exact_canonical_query() -> None:
    expected = object()
    reader = _Reader(expected)
    service = MarketDataService(object(), canonical_reader=reader)  # type: ignore[arg-type]

    assert service.get_bars(_query()) is expected
    assert reader.queries == [_query()]


def test_market_data_service_rejects_legacy_request_shape() -> None:
    service = MarketDataService(object(), canonical_reader=_Reader(object()))  # type: ignore[arg-type]

    with pytest.raises(DataCoreError) as error:
        service.get_bars(object())  # type: ignore[arg-type]

    assert error.value.facts["reason"] == "canonical_bar_query_required"


def test_market_data_service_rejects_legacy_constructor_options() -> None:
    with pytest.raises(DataCoreError) as error:
        MarketDataService(object(), resolver=object())  # type: ignore[arg-type]

    assert error.value.facts["reason"] == "legacy_market_options_retired"


def test_market_data_service_rejects_retired_product_before_reader_access() -> None:
    reader = _Reader(object())
    service = MarketDataService(object(), canonical_reader=reader)  # type: ignore[arg-type]
    query = BarQuery(
        dataset_kind=DatasetKind.CONTINUOUS,
        symbol="jr",
        contract_or_series="JR.MAIN",
        frequency=BarFrequency.M1,
        start=datetime(2026, 7, 1, tzinfo=UTC),
        end=datetime(2026, 7, 2, tzinfo=UTC),
    )

    with pytest.raises(DataCoreError) as error:
        service.get_bars(query)

    assert error.value.facts == {"reason": "product_retired", "symbol": "jr"}
    assert reader.queries == []
