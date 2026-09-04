from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import MappingProxyType

from app.market_data.actual_dominant_research import ActualDominantResearchSeries
from app.market_data.domain import (
    BarFrequency,
    CanonicalBar,
    MarketSeriesPageResult,
    MarketSeriesResult,
    ResolvedContractSegment,
    SeriesPageQuery,
)
from app.market_data.newow.futures_evidence_service import (
    build_newow_futures_evidence_inputs,
)


def _bar(day: date, value: int) -> CanonicalBar:
    price = Decimal(value)
    return CanonicalBar(
        datetime(day.year, day.month, day.day, 7, tzinfo=UTC),
        day,
        price,
        price + 1,
        price - 1,
        price,
        Decimal(100),
        Decimal(1000),
        Decimal(500),
    )


class _PrefixReader:
    def __init__(self, pages: dict[str, tuple[CanonicalBar, ...]]) -> None:
        self.pages = pages
        self.requests: list[SeriesPageQuery] = []

    def query_page(self, request: SeriesPageQuery) -> MarketSeriesPageResult:
        self.requests.append(request)
        bars = self.pages[request.contract or ""]
        return MarketSeriesPageResult(
            {
                "series_kind": "contract",
                "symbol": request.symbol,
                "contract": request.contract,
                "frequency": request.frequency.value,
                "before": request.before.isoformat() if request.before else None,
                "limit": request.limit,
            },
            bars,
            (bars[0].bar_end, bars[-1].bar_end),
            False,
            None,
            (),
        )


def test_loads_prefix_only_for_segments_observed_by_each_frequency() -> None:
    first_day = date(2026, 1, 5)
    segments = (
        ResolvedContractSegment("RB2605", first_day, first_day),
        ResolvedContractSegment(
            "RB2610", first_day + timedelta(days=1), first_day + timedelta(days=3)
        ),
    )
    weekly_bar = _bar(first_day + timedelta(days=3), 103)
    weekly = MarketSeriesResult(
        {
            "series_kind": "actual_dominant",
            "symbol": "rb",
            "contract": None,
            "frequency": "1w",
        },
        (weekly_bar,),
        (weekly_bar.bar_end, weekly_bar.bar_end),
        (ResolvedContractSegment("RB2610", weekly_bar.trading_day, weekly_bar.trading_day),),
        (first_day, first_day + timedelta(days=3)),
    )
    loaded = ActualDominantResearchSeries(
        MappingProxyType({BarFrequency.W1: weekly}), segments
    )
    reader = _PrefixReader(
        {
            "RB2610": (
                _bar(first_day - timedelta(days=7), 90),
                weekly_bar,
            )
        }
    )

    result = build_newow_futures_evidence_inputs(
        reader,
        loaded,
        expected_product="rb",
        frequencies=(BarFrequency.W1,),
    )

    assert tuple(result) == (BarFrequency.W1,)
    evidence = result[BarFrequency.W1]
    assert tuple(bar.physical_contract for bar in evidence.execution_bars) == (
        "RB2610",
    )
    assert len(evidence.strategy_replay_segments) == 1
    assert reader.requests[0].contract == "RB2610"
    assert reader.requests[0].limit == 2000
    assert reader.requests[0].before == weekly_bar.bar_end + timedelta(microseconds=1)
