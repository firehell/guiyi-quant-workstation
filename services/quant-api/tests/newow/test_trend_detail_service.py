from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.market_data.domain import (
    ActualDominantTradingDayQuery,
    BarFrequency,
    CanonicalBar,
    MarketSeriesPageResult,
    MarketSeriesResult,
    ResolvedContractSegment,
    SeriesKind,
    SeriesPageQuery,
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


def test_detail_query_uses_public_invalid_product_and_range_codes() -> None:
    with pytest.raises(ValueError, match="NEWOW_INVALID_PRODUCT"):
        NewowTrendDetailQuery("RB", _START, _START)
    with pytest.raises(ValueError, match="NEWOW_INVALID_RANGE"):
        NewowTrendDetailQuery("rb", _START + timedelta(days=1), _START)
    with pytest.raises(ValueError, match="NEWOW_INVALID_PRODUCT"):
        NewowTrendDetailQuery("r钢", _START, _START)


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
        self.page_requests: list[SeriesPageQuery] = []

    def query_actual_dominant_trading_days(
        self, request: ActualDominantTradingDayQuery
    ) -> MarketSeriesResult:
        self.actual_requests.append(request)
        bars = tuple(
            bar
            for bar in self.actual
            if request.since <= bar.trading_day <= request.through
        )
        return MarketSeriesResult(
            {}, bars, None, self.segments, (request.since, request.through)
        )

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

    def query_page(self, request: SeriesPageQuery) -> MarketSeriesPageResult:
        self.page_requests.append(request)
        assert request.series_kind is SeriesKind.CONTRACT
        assert request.contract is not None
        values = tuple(
            bar
            for bar in self.physical[request.contract]
            if request.before is None or bar.bar_end < request.before
        )
        page = values[-request.limit :]
        return MarketSeriesPageResult(
            {
                "series_kind": "contract",
                "contract": request.contract,
                "frequency": "1d",
            },
            page,
            (page[0].bar_end, page[-1].bar_end) if page else None,
            len(values) > request.limit,
            page[0].bar_end if len(values) > request.limit else None,
            (),
        )

    def query_contract_trading_days(self, request: object) -> MarketSeriesResult:
        raise AssertionError("detail service must use query_page")


def _service(
    *, split: bool = False, prewarm: int = 3
) -> tuple[NewowTrendDetailService, _FakeMarketData]:
    days = tuple(_START + timedelta(days=index) for index in range(8))
    first = ResolvedContractSegment("RB2605", days[prewarm], days[4 if split else 7])
    segments = (first,)
    actual = tuple(
        _bar(day, 100 + index)
        for index, day in enumerate(days[prewarm : 5 if split else 8], prewarm)
    )
    physical = {
        "RB2605": tuple(
            _bar(day, 100 + index)
            for index, day in enumerate(days[: 5 if split else 8])
        )
    }
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

    result = service.query(
        NewowTrendDetailQuery(
            "rb", _START + timedelta(days=3), _START + timedelta(days=7)
        )
    )

    assert result.instrument.product == "rb"
    assert result.instrument.frequency == "1d"
    assert result.instrument.series_kind == "actual_dominant"
    assert [bar.trading_day for bar in result.bars] == [
        _START + timedelta(days=index) for index in range(3, 8)
    ]
    assert all(frame.bar.observation_eligible for frame in result.frames)
    assert market_data.actual_requests[0].frequency is BarFrequency.D1
    assert market_data.page_requests == [
        SeriesPageQuery(
            SeriesKind.CONTRACT,
            "rb",
            BarFrequency.D1,
            _bar(_START + timedelta(days=7), 107).bar_end + timedelta(microseconds=1),
            2000,
            "RB2605",
        )
    ]


def test_detail_builds_explicit_seam_and_resets_at_physical_rollover() -> None:
    service, _ = _service(split=True)

    result = service.query(
        NewowTrendDetailQuery(
            "rb", _START + timedelta(days=3), _START + timedelta(days=7)
        )
    )

    assert [
        (seam.previous_contract, seam.next_contract) for seam in result.rollover_seams
    ] == [("RB2605", "RB2610")]
    assert (
        result.rollover_seams[0].next_bar_end
        == _bar(_START + timedelta(days=5), 205).bar_end
    )
    assert result.rollover_seams[0].trading_day == _START + timedelta(days=5)
    assert all(not frame.rollover_started for frame in result.frames)
    assert len({bar.segment_id for bar in result.bars}) == 2
    assert result.cup_handles == ()


def test_detail_rejects_invalid_query_and_visible_range_before_market_read() -> None:
    service, market_data = _service()

    for product, since, through, code in (
        ("", _START, _START, "NEWOW_INVALID_PRODUCT"),
        ("rb", _START + timedelta(days=1), _START, "NEWOW_INVALID_RANGE"),
    ):
        with pytest.raises(NewowTrendDetailError, match=code):
            service.query(NewowTrendDetailQuery.unchecked(product, since, through))

    assert market_data.actual_requests == []
    assert market_data.page_requests == []


@pytest.mark.parametrize("bad_index", (1, 2))
def test_detail_rejects_noncanonical_physical_prefix_order(bad_index: int) -> None:
    service, market_data = _service()
    bars = list(market_data.physical["RB2605"])
    bars[bad_index] = (
        bars[0]
        if bad_index == 1
        else bars[2].__class__(
            bars[0].bar_end,
            bars[2].trading_day,
            bars[2].open,
            bars[2].high,
            bars[2].low,
            bars[2].close,
            bars[2].volume,
            bars[2].turnover,
            bars[2].open_interest,
        )
    )
    market_data.physical["RB2605"] = tuple(bars)

    with pytest.raises(NewowTrendDetailError, match="NEWOW_DATA_OUT_OF_ORDER"):
        service.query(
            NewowTrendDetailQuery(
                "rb", _START + timedelta(days=3), _START + timedelta(days=7)
            )
        )


def test_detail_normalizes_core_converter_value_error_to_public_identity_error() -> (
    None
):
    service, market_data = _service()
    bad = list(market_data.physical["RB2605"])
    source = bad[0]
    bad[0] = CanonicalBar(
        source.bar_end,
        source.trading_day,
        Decimal("0"),
        source.high,
        Decimal("0"),
        Decimal("0"),
        source.volume,
        source.turnover,
        source.open_interest,
    )
    market_data.physical["RB2605"] = tuple(bad)

    with pytest.raises(NewowTrendDetailError, match="NEWOW_DATA_IDENTITY_INVALID"):
        service.query(
            NewowTrendDetailQuery(
                "rb", _START + timedelta(days=3), _START + timedelta(days=7)
            )
        )


def test_detail_is_overlap_invariant_and_returns_immutable_stable_tuples() -> None:
    service, _ = _service(split=True)

    wide = service.query(
        NewowTrendDetailQuery(
            "rb", _START + timedelta(days=3), _START + timedelta(days=7)
        )
    )
    narrow = service.query(
        NewowTrendDetailQuery(
            "rb", _START + timedelta(days=5), _START + timedelta(days=7)
        )
    )

    assert tuple(frame.bar.bar_end for frame in narrow.frames) == tuple(
        frame.bar.bar_end for frame in wide.frames[-3:]
    )
    assert (
        tuple(
            type(value)
            for value in (
                wide.bars,
                wide.frames,
                wide.markers,
                wide.cup_handles,
                wide.rollover_seams,
                wide.warnings,
            )
        )
        == (tuple,) * 6
    )
    assert wide.warnings == (
        "NEWOW_TREND_WARMUP_INSUFFICIENT",
        "NEWOW_D123_WARMUP_INSUFFICIENT",
        "NEWOW_CUP_WARMUP_INSUFFICIENT",
    )
    assert wide == service.query(
        NewowTrendDetailQuery(
            "rb", _START + timedelta(days=3), _START + timedelta(days=7)
        )
    )


def test_cross_rollover_overlap_keeps_calculation_identity_and_engine_facts_stable() -> (
    None
):
    service, _ = _service(split=True)
    wide = service.query(
        NewowTrendDetailQuery(
            "rb", _START + timedelta(days=3), _START + timedelta(days=7)
        )
    )
    narrow = service.query(
        NewowTrendDetailQuery(
            "rb", _START + timedelta(days=5), _START + timedelta(days=7)
        )
    )

    assert wide.calculation_identity == narrow.calculation_identity
    assert wide.request_identity != narrow.request_identity
    assert tuple(bar.source_identity for bar in wide.bars[-3:]) == tuple(
        bar.source_identity for bar in narrow.bars
    )
    assert wide.frames[-3:] == narrow.frames
    assert (
        tuple(marker for frame in wide.frames[-3:] for marker in frame.markers)
        == narrow.markers
    )
    assert wide.cup_handles == narrow.cup_handles


def test_detail_stops_after_actual_read_when_visible_actual_bars_exceed_1500() -> None:
    days = tuple(_START + timedelta(days=index) for index in range(1501))
    segment = ResolvedContractSegment("RB2605", days[0], days[-1])
    actual = tuple(_bar(day, 100 + index) for index, day in enumerate(days))
    market_data = _FakeMarketData(
        actual=actual,
        segments=(segment,),
        physical={"RB2605": actual},
    )
    service = NewowTrendDetailService(market_data)

    with pytest.raises(NewowTrendDetailError, match="NEWOW_RANGE_TOO_LARGE"):
        service.query(NewowTrendDetailQuery("rb", days[0], days[-1]))

    assert market_data.actual_requests
    assert market_data.page_requests == []


def test_warmup_acceptance_c_prerank_atr_does_not_make_cup_geometry_ready() -> None:
    days = tuple(_START + timedelta(days=index) for index in range(130))
    physical = tuple(_bar(day, 100 + index) for index, day in enumerate(days))
    segment = ResolvedContractSegment("RB2605", days[-1], days[-1])
    service = NewowTrendDetailService(
        _FakeMarketData(
            actual=(physical[-1],),
            segments=(segment,),
            physical={"RB2605": physical},
        )
    )

    result = service.query(NewowTrendDetailQuery("rb", days[-1], days[-1]))

    assert result.warnings == ("NEWOW_CUP_WARMUP_INSUFFICIENT",)


def _single_segment_result(*, count: int, eligible_start: int = 0):
    days = tuple(_START + timedelta(days=index) for index in range(count))
    physical = tuple(_bar(day, 100 + index) for index, day in enumerate(days))
    segment = ResolvedContractSegment("RB2605", days[eligible_start], days[-1])
    actual = physical[eligible_start:]
    return NewowTrendDetailService(
        _FakeMarketData(actual=actual, segments=(segment,), physical={"RB2605": physical})
    ).query(NewowTrendDetailQuery("rb", days[eligible_start], days[-1]))


def test_warmup_acceptance_a_all_kernels_unavailable() -> None:
    assert set(_single_segment_result(count=5).warnings) == {
        "NEWOW_TREND_WARMUP_INSUFFICIENT",
        "NEWOW_D123_WARMUP_INSUFFICIENT",
        "NEWOW_CUP_WARMUP_INSUFFICIENT",
    }


def test_warmup_acceptance_b_only_d123_is_unavailable_after_trend_and_cup_ready() -> None:
    assert _single_segment_result(count=40).warnings == ("NEWOW_D123_WARMUP_INSUFFICIENT",)


def test_warmup_acceptance_d_early_history_does_not_leave_current_warning() -> None:
    assert _single_segment_result(count=130).warnings == ()


def test_warmup_acceptance_e_no_signal_is_not_unavailable() -> None:
    result = _single_segment_result(count=130)
    assert result.warnings == ()
    assert not result.markers
    assert not result.cup_handles


def test_detail_fails_closed_when_same_contract_prefix_exceeds_one_2000_bar_page() -> (
    None
):
    days = tuple(_START + timedelta(days=index) for index in range(2001))
    segment = ResolvedContractSegment("RB2605", days[-1], days[-1])
    physical = tuple(_bar(day, 100 + index) for index, day in enumerate(days))
    market_data = _FakeMarketData(
        actual=(physical[-1],),
        segments=(segment,),
        physical={"RB2605": physical},
    )

    with pytest.raises(NewowTrendDetailError, match="NEWOW_DATA_IDENTITY_INVALID"):
        NewowTrendDetailService(market_data).query(
            NewowTrendDetailQuery("rb", days[-1], days[-1])
        )

    assert len(market_data.page_requests) == 1
    assert market_data.page_requests[0].limit == 2000


def test_detail_is_stateless_and_calculation_identity_never_binds_request_dates() -> (
    None
):
    service, market_data = _service()

    first = service.query(
        NewowTrendDetailQuery(
            "rb", _START + timedelta(days=3), _START + timedelta(days=6)
        )
    )
    second = service.query(
        NewowTrendDetailQuery(
            "rb", _START + timedelta(days=4), _START + timedelta(days=7)
        )
    )

    assert first.calculation_identity == second.calculation_identity
    assert first.request_identity != second.request_identity
    assert all(bar.source_identity == first.calculation_identity for bar in first.bars)
    assert tuple(service.__dict__) == ("_market_data", "_taxonomy")
    assert len(market_data.page_requests) == 2
