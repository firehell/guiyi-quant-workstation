from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.market_data.domain import (
    ActualDominantTradingDayQuery,
    BarFrequency,
    CanonicalBar,
    ContractTradingDayQuery,
    MarketSeriesResult,
    ResolvedContractSegment,
)
from app.market_data.newow.trend_detail_query import NewowTrendDetailQuery
from app.market_data.newow.trend_detail_service import (
    NewowTrendDetailError,
    NewowTrendDetailService,
)
from app.market_data.market_data_service import DominantContractSegmentSummary


_START = date(2026, 1, 5)


def _bar(day: date, close: int) -> CanonicalBar:
    value = Decimal(close)
    return CanonicalBar(
        bar_end=datetime.combine(day, datetime.min.time(), UTC) + timedelta(hours=7),
        trading_day=day,
        open=value,
        high=value + 1,
        low=value - 1,
        close=value,
        volume=Decimal("100"),
        turnover=None,
        open_interest=Decimal("200"),
    )


class _FakeMarketData:
    def __init__(
        self,
        *,
        actual: tuple[CanonicalBar, ...],
        segments: tuple[ResolvedContractSegment, ...],
        physical: dict[str, tuple[CanonicalBar, ...]],
    ) -> None:
        self.actual = actual
        self.segments = segments
        self.physical = physical
        self.actual_requests: list[ActualDominantTradingDayQuery] = []
        self.contract_requests: list[ContractTradingDayQuery] = []

    def query_actual_dominant_trading_days(
        self, request: ActualDominantTradingDayQuery
    ) -> MarketSeriesResult:
        self.actual_requests.append(request)
        bars = tuple(bar for bar in self.actual if request.since <= bar.trading_day <= request.through)
        return MarketSeriesResult({}, bars, None, self.segments, (request.since, request.through))

    def dominant_segment_for_day(
        self, symbol: str, trading_day: date
    ) -> DominantContractSegmentSummary:
        segment = next(
            segment
            for segment in self.segments
            if segment.start_trading_day <= trading_day <= segment.end_trading_day
        )
        return DominantContractSegmentSummary(
            symbol,
            segment.contract,
            segment.start_trading_day,
            segment.end_trading_day,
        )

    def query_contract_trading_days(
        self, request: ContractTradingDayQuery
    ) -> MarketSeriesResult:
        self.contract_requests.append(request)
        bars = tuple(bar for bar in self.physical[request.contract] if request.since <= bar.trading_day <= request.through)
        return MarketSeriesResult({}, bars, None, (), (request.since, request.through))


def _service(*, split: bool = False, prewarm: int = 3) -> tuple[NewowTrendDetailService, _FakeMarketData]:
    days = tuple(_START + timedelta(days=index) for index in range(8))
    first = ResolvedContractSegment("RB2605", days[prewarm], days[4 if split else 7])
    segments = (first,)
    actual = tuple(_bar(day, 100 + index) for index, day in enumerate(days[prewarm : 5 if split else 8], prewarm))
    physical = {"RB2605": tuple(_bar(day, 100 + index) for index, day in enumerate(days[: 5 if split else 8]))}
    if split:
        second = ResolvedContractSegment("RB2610", days[5], days[7])
        segments = (first, second)
        actual += tuple(_bar(day, 200 + index) for index, day in enumerate(days[5:], 5))
        physical["RB2610"] = tuple(
            _bar(day, 200 + index) for index, day in enumerate(days[5:], 5)
        )
    market_data = _FakeMarketData(actual=actual, segments=segments, physical=physical)
    return NewowTrendDetailService(market_data), market_data


def test_detail_uses_only_d1_actual_dominant_and_same_contract_prefix() -> None:
    service, market_data = _service()

    result = service.query(NewowTrendDetailQuery("rb", _START + timedelta(days=3), _START + timedelta(days=7)))

    assert result.instrument.product == "rb"
    assert result.instrument.frequency == "1d"
    assert result.instrument.series_kind == "actual_dominant"
    assert [bar.trading_day for bar in result.bars] == [_START + timedelta(days=index) for index in range(3, 8)]
    assert all(frame.bar.observation_eligible for frame in result.frames)
    assert market_data.actual_requests[0].frequency is BarFrequency.D1
    assert market_data.contract_requests == [
        ContractTradingDayQuery("rb", "RB2605", BarFrequency.D1, date(2000, 1, 1), _START + timedelta(days=7))
    ]


def test_detail_builds_explicit_seam_and_resets_at_physical_rollover() -> None:
    service, _ = _service(split=True)

    result = service.query(NewowTrendDetailQuery("rb", _START + timedelta(days=3), _START + timedelta(days=7)))

    assert [(seam.previous_contract, seam.next_contract) for seam in result.seams] == [("RB2605", "RB2610")]
    assert result.seams[0].next_bar_end == _bar(_START + timedelta(days=5), 205).bar_end
    assert all(not frame.rollover_started for frame in result.frames)
    assert len({bar.segment_id for bar in result.bars}) == 2
    assert result.cup_overlays == ()


def test_detail_rejects_invalid_query_and_visible_range_before_market_read() -> None:
    service, market_data = _service()

    for product, since, through, code in (
        ("", _START, _START, "NEWOW_DETAIL_QUERY_INVALID"),
        ("rb", _START + timedelta(days=1), _START, "NEWOW_DETAIL_QUERY_INVALID"),
        ("rb", _START, _START + timedelta(days=366), "NEWOW_DETAIL_VISIBLE_RANGE_EXCEEDED"),
    ):
        with pytest.raises(NewowTrendDetailError, match=code):
            service.query(NewowTrendDetailQuery.unchecked(product, since, through))

    assert market_data.actual_requests == []
    assert market_data.contract_requests == []


@pytest.mark.parametrize("bad_index, code", ((1, "NEWOW_DETAIL_DUPLICATE_BAR"), (2, "NEWOW_DETAIL_OUT_OF_ORDER_BAR")))
def test_detail_rejects_noncanonical_physical_prefix_order(bad_index: int, code: str) -> None:
    service, market_data = _service()
    bars = list(market_data.physical["RB2605"])
    bars[bad_index] = bars[0] if bad_index == 1 else bars[2].__class__(
        bars[0].bar_end, bars[2].trading_day, bars[2].open, bars[2].high, bars[2].low, bars[2].close, bars[2].volume, bars[2].turnover, bars[2].open_interest
    )
    market_data.physical["RB2605"] = tuple(bars)

    with pytest.raises(NewowTrendDetailError, match=code):
        service.query(NewowTrendDetailQuery("rb", _START + timedelta(days=3), _START + timedelta(days=7)))


def test_detail_is_overlap_invariant_and_returns_immutable_stable_tuples() -> None:
    service, _ = _service(split=True)

    wide = service.query(NewowTrendDetailQuery("rb", _START + timedelta(days=3), _START + timedelta(days=7)))
    narrow = service.query(NewowTrendDetailQuery("rb", _START + timedelta(days=5), _START + timedelta(days=7)))

    assert tuple(frame.bar.bar_end for frame in narrow.frames) == tuple(frame.bar.bar_end for frame in wide.frames[-3:])
    assert tuple(type(value) for value in (wide.bars, wide.frames, wide.markers, wide.cup_overlays, wide.seams, wide.warnings)) == (tuple,) * 6
    assert wide.warnings == ("NEWOW_WARMUP_INCOMPLETE",)
    assert wide == service.query(NewowTrendDetailQuery("rb", _START + timedelta(days=3), _START + timedelta(days=7)))
