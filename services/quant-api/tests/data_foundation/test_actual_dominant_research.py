from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.market_data.actual_dominant_research import (
    ActualDominantResearchSegmentLoader,
    ActualDominantResearchSegmentIdentityError,
    ActualDominantResearchSourceTradingDayMissingError,
    ActualDominantStitchedResearchLoader,
)
from app.market_data.domain import (
    ActualDominantRecentBarsQuery,
    ActualDominantTradingDayQuery,
    BarFrequency,
    CanonicalBar,
    MarketSeriesPageResult,
    MarketSeriesResult,
    ResolvedContractSegment,
)
from app.market_data.market_data_service import (
    ActualDominantSourceTradingDayMissingError,
    DominantContractSegmentSummary,
)


_DAY_ONE = date(2026, 8, 3)
_DAY_TWO = date(2026, 8, 4)
_DAY_THREE = date(2026, 8, 5)
_DAY_FOUR = date(2026, 8, 6)
_FREQUENCIES = (BarFrequency.M5, BarFrequency.M15)
_STITCHED_SOURCE_DAY = date(2026, 8, 21)
_STITCHED_CURRENT_START = date(2026, 8, 12)


class _WindowAwareMarketData:
    def __init__(
        self,
        *,
        probe: dict[BarFrequency, MarketSeriesResult],
        full: dict[BarFrequency, MarketSeriesResult],
        true_segments: tuple[DominantContractSegmentSummary, ...],
    ) -> None:
        self._probe = probe
        self._full = full
        self._true_segments = true_segments
        self._query_counts = dict.fromkeys(probe.keys() | full.keys(), 0)
        self.queries: list[ActualDominantTradingDayQuery] = []
        self.segment_requests: list[tuple[str, date]] = []
        self.authoritative_requests: list[tuple[str, date, date]] = []

    def query_actual_dominant_trading_days(
        self,
        request: ActualDominantTradingDayQuery,
    ) -> MarketSeriesResult:
        self.queries.append(request)
        count = self._query_counts[request.frequency]
        self._query_counts[request.frequency] = count + 1
        return (self._probe if count == 0 else self._full)[request.frequency]

    def dominant_segment_for_day(
        self,
        symbol: str,
        trading_day: date,
    ) -> DominantContractSegmentSummary:
        self.segment_requests.append((symbol, trading_day))
        return next(
            segment
            for segment in self._true_segments
            if segment.start_trading_day <= trading_day <= segment.end_trading_day
        )

    def actual_dominant_segments(
        self,
        symbol: str,
        since: date,
        through: date,
    ) -> tuple[ResolvedContractSegment, ...]:
        self.authoritative_requests.append((symbol, since, through))
        return tuple(
            ResolvedContractSegment(
                segment.contract,
                segment.start_trading_day,
                segment.end_trading_day,
            )
            for segment in self._true_segments
            if segment.symbol == symbol
            and segment.end_trading_day >= since
            and segment.start_trading_day <= through
        )


class _StitchedMarketData:
    def __init__(
        self,
        *,
        results: dict[BarFrequency, MarketSeriesPageResult],
        summary: DominantContractSegmentSummary,
        failures: dict[BarFrequency, Exception] | None = None,
    ) -> None:
        self._results = results
        self._summary = summary
        self._failures = failures or {}
        self.queries: list[ActualDominantRecentBarsQuery] = []
        self.segment_requests: list[tuple[str, date]] = []

    def query_actual_dominant_recent_bars(
        self,
        request: ActualDominantRecentBarsQuery,
    ) -> MarketSeriesPageResult:
        self.queries.append(request)
        failure = self._failures.get(request.frequency)
        if failure is not None:
            raise failure
        return self._results[request.frequency]

    def dominant_segment_for_day(
        self,
        symbol: str,
        trading_day: date,
    ) -> DominantContractSegmentSummary:
        self.segment_requests.append((symbol, trading_day))
        return self._summary


def test_stitched_loader_accepts_different_histories_and_preserves_pages() -> None:
    previous = ResolvedContractSegment(
        "RB2605",
        date(2026, 7, 23),
        date(2026, 8, 11),
    )
    current = ResolvedContractSegment(
        "RB2610",
        _STITCHED_CURRENT_START,
        date(2026, 8, 31),
    )
    daily = _page_result(
        _bars(
            BarFrequency.D1,
            tuple(
                date(2026, 7, 23) + timedelta(days=index)
                for index in range(30)
            ),
        ),
        (previous, current),
    )
    hourly = _page_result(
        _bars(
            BarFrequency.H1,
            tuple(
                _STITCHED_CURRENT_START + timedelta(days=index // 3)
                for index in range(30)
            ),
        ),
        (current,),
    )
    market_data = _StitchedMarketData(
        results={BarFrequency.D1: daily, BarFrequency.H1: hourly},
        summary=DominantContractSegmentSummary(
            "rb",
            "RB2610",
            _STITCHED_CURRENT_START,
            date(2026, 8, 31),
        ),
    )

    loaded = ActualDominantStitchedResearchLoader(market_data).load(
        symbol="rb",
        frequencies=(BarFrequency.D1, BarFrequency.H1),
        through=_STITCHED_SOURCE_DAY,
        limit=30,
    )

    assert loaded.results[BarFrequency.D1] is daily
    assert loaded.results[BarFrequency.H1] is hourly
    assert loaded.current_segment == current
    assert market_data.queries == [
        ActualDominantRecentBarsQuery(
            "rb", BarFrequency.D1, _STITCHED_SOURCE_DAY, 30
        ),
        ActualDominantRecentBarsQuery(
            "rb", BarFrequency.H1, _STITCHED_SOURCE_DAY, 30
        ),
    ]
    assert market_data.segment_requests == [("rb", _STITCHED_SOURCE_DAY)]


def test_stitched_loader_rejects_empty_frequencies_before_market_read() -> None:
    market_data = _StitchedMarketData(
        results={},
        summary=DominantContractSegmentSummary(
            "rb",
            "RB2610",
            _STITCHED_CURRENT_START,
            date(2026, 8, 31),
        ),
    )

    with pytest.raises(
        ActualDominantResearchSegmentIdentityError,
        match="rank1 stitched identity is missing or inconsistent",
    ):
        ActualDominantStitchedResearchLoader(market_data).load(
            symbol="rb",
            frequencies=(),
            through=_STITCHED_SOURCE_DAY,
            limit=30,
        )

    assert market_data.queries == []
    assert market_data.segment_requests == []


@pytest.mark.parametrize("frequency", (BarFrequency.D1, BarFrequency.H1))
def test_stitched_loader_types_each_missing_source_day_bar(
    frequency: BarFrequency,
) -> None:
    current = ResolvedContractSegment(
        "RB2610",
        _STITCHED_CURRENT_START,
        date(2026, 8, 31),
    )
    results = {
        item: _page_result(
            _bars(item, (_STITCHED_SOURCE_DAY,)),
            (current,),
        )
        for item in (BarFrequency.D1, BarFrequency.H1)
    }
    market_data = _StitchedMarketData(
        results=results,
        summary=DominantContractSegmentSummary(
            "rb",
            "RB2610",
            _STITCHED_CURRENT_START,
            date(2026, 8, 31),
        ),
        failures={frequency: ActualDominantSourceTradingDayMissingError()},
    )

    with pytest.raises(ActualDominantResearchSourceTradingDayMissingError):
        ActualDominantStitchedResearchLoader(market_data).load(
            symbol="rb",
            frequencies=(BarFrequency.D1, BarFrequency.H1),
            through=_STITCHED_SOURCE_DAY,
        )


def test_stitched_loader_requires_same_current_owner_across_frequencies() -> None:
    daily_segment = ResolvedContractSegment(
        "RB2610", _STITCHED_CURRENT_START, date(2026, 8, 31)
    )
    hourly_segment = ResolvedContractSegment(
        "RB2605", date(2026, 7, 23), date(2026, 8, 31)
    )
    market_data = _StitchedMarketData(
        results={
            BarFrequency.D1: _page_result(
                _bars(BarFrequency.D1, (_STITCHED_SOURCE_DAY,)),
                (daily_segment,),
            ),
            BarFrequency.H1: _page_result(
                _bars(BarFrequency.H1, (_STITCHED_SOURCE_DAY,)),
                (hourly_segment,),
            ),
        },
        summary=DominantContractSegmentSummary(
            "rb",
            "RB2610",
            _STITCHED_CURRENT_START,
            date(2026, 8, 31),
        ),
    )

    with pytest.raises(
        ActualDominantResearchSegmentIdentityError,
        match="rank1 stitched identity is missing or inconsistent",
    ):
        ActualDominantStitchedResearchLoader(market_data).load(
            symbol="rb",
            frequencies=(BarFrequency.D1, BarFrequency.H1),
            through=_STITCHED_SOURCE_DAY,
        )


@pytest.mark.parametrize(
    "summary",
    (
        DominantContractSegmentSummary(
            "rb", "RB2605", date(2026, 7, 23), date(2026, 8, 31)
        ),
        DominantContractSegmentSummary(
            "rb", "RB2610", date(2026, 7, 23), date(2026, 8, 20)
        ),
    ),
)
def test_stitched_loader_requires_source_day_summary_identity(
    summary: DominantContractSegmentSummary,
) -> None:
    current = ResolvedContractSegment(
        "RB2610", _STITCHED_CURRENT_START, date(2026, 8, 31)
    )
    market_data = _StitchedMarketData(
        results={
            frequency: _page_result(
                _bars(frequency, (_STITCHED_SOURCE_DAY,)),
                (current,),
            )
            for frequency in (BarFrequency.D1, BarFrequency.H1)
        },
        summary=summary,
    )

    with pytest.raises(
        ActualDominantResearchSegmentIdentityError,
        match="rank1 stitched identity is missing or inconsistent",
    ):
        ActualDominantStitchedResearchLoader(market_data).load(
            symbol="rb",
            frequencies=(BarFrequency.D1, BarFrequency.H1),
            through=_STITCHED_SOURCE_DAY,
        )


def test_loader_reads_one_full_causal_prefix_from_authoritative_start() -> None:
    true_segments = (
        DominantContractSegmentSummary("jm", "JM2609", _DAY_ONE, _DAY_TWO),
        DominantContractSegmentSummary("jm", "JM2701", _DAY_THREE, _DAY_FOUR),
    )
    restored_segments = tuple(
        ResolvedContractSegment(
            segment.contract,
            segment.start_trading_day,
            segment.end_trading_day,
        )
        for segment in true_segments
    )
    full = {
        frequency: _result(
            _bars(frequency, (_DAY_ONE, _DAY_TWO, _DAY_THREE)),
            restored_segments,
        )
        for frequency in _FREQUENCIES
    }
    market_data = _WindowAwareMarketData(
        probe=full,
        full={},
        true_segments=true_segments,
    )

    loaded = ActualDominantResearchSegmentLoader(market_data).load(
        symbol="jm",
        frequencies=_FREQUENCIES,
        since=_DAY_TWO,
        through=_DAY_THREE,
    )

    assert loaded.results == full
    assert loaded.authoritative_segments == restored_segments
    assert market_data.queries == [
        ActualDominantTradingDayQuery("jm", BarFrequency.M5, _DAY_ONE, _DAY_THREE),
        ActualDominantTradingDayQuery("jm", BarFrequency.M15, _DAY_ONE, _DAY_THREE),
    ]
    assert market_data.segment_requests == []


def test_loader_rejects_empty_frequency_request_before_market_read() -> None:
    market_data = _WindowAwareMarketData(
        probe={},
        full={},
        true_segments=(),
    )

    with pytest.raises(
        ValueError,
        match="rank1 segment identity is missing or inconsistent",
    ):
        ActualDominantResearchSegmentLoader(market_data).load(
            symbol="jm",
            frequencies=(),
            since=_DAY_ONE,
            through=_DAY_TWO,
        )

    assert market_data.queries == []
    assert market_data.segment_requests == []


def test_loader_rejects_duplicate_frequencies_before_any_market_read() -> None:
    market_data = _WindowAwareMarketData(
        probe={},
        full={},
        true_segments=(),
    )

    with pytest.raises(
        ActualDominantResearchSegmentIdentityError,
        match="rank1 frequency identity is duplicated",
    ):
        ActualDominantResearchSegmentLoader(market_data).load(
            symbol="jm",
            frequencies=(BarFrequency.M5, BarFrequency.M5),
            since=_DAY_ONE,
            through=_DAY_TWO,
        )

    assert market_data.authoritative_requests == []
    assert market_data.queries == []


@pytest.mark.parametrize("frequency", (BarFrequency.D1, BarFrequency.H1))
def test_loader_rejects_nonweekly_empty_exception_before_owner_or_market_read(
    frequency: BarFrequency,
) -> None:
    """Only the documented W1 exception may be requested at this shared boundary."""
    market_data = _WindowAwareMarketData(
        probe={},
        full={},
        true_segments=(),
    )

    with pytest.raises(
        ActualDominantResearchSegmentIdentityError,
        match="rank1 empty-frequency identity is invalid",
    ):
        ActualDominantResearchSegmentLoader(market_data).load(
            symbol="jm",
            frequencies=(frequency,),
            since=_DAY_ONE,
            through=_DAY_TWO,
            allow_empty_frequencies=(frequency,),
        )

    assert market_data.authoritative_requests == []
    assert market_data.queries == []


class _UnavailableMarketData:
    def actual_dominant_segments(
        self,
        symbol: str,
        since: date,
        through: date,
    ) -> tuple[ResolvedContractSegment, ...]:
        return (ResolvedContractSegment("JM2609", since, through),)

    def query_actual_dominant_trading_days(
        self,
        request: ActualDominantTradingDayQuery,
    ) -> MarketSeriesResult:
        raise FileNotFoundError("/private/canonical/jm-secret.parquet")

    def dominant_segment_for_day(
        self,
        symbol: str,
        trading_day: date,
    ) -> DominantContractSegmentSummary:
        raise AssertionError("source query must fail first")


def test_loader_preserves_source_failure_for_consumer_adapters() -> None:
    with pytest.raises(FileNotFoundError) as captured:
        ActualDominantResearchSegmentLoader(_UnavailableMarketData()).load(
            symbol="jm",
            frequencies=(BarFrequency.M5,),
            since=_DAY_ONE,
            through=_DAY_TWO,
        )

    assert str(captured.value) == "/private/canonical/jm-secret.parquet"
    assert captured.value.__cause__ is None


def test_loader_supports_one_frequency_without_cross_frequency_assumption() -> None:
    segment = ResolvedContractSegment("JM2609", _DAY_ONE, _DAY_TWO)
    summary = DominantContractSegmentSummary(
        "jm", "JM2609", _DAY_ONE, _DAY_TWO
    )
    result = _result(
        _bars(BarFrequency.M15, (_DAY_ONE, _DAY_TWO)),
        (segment,),
    )
    market_data = _WindowAwareMarketData(
        probe={BarFrequency.M15: result},
        full={BarFrequency.M15: result},
        true_segments=(summary,),
    )

    loaded = ActualDominantResearchSegmentLoader(market_data).load(
        symbol="jm",
        frequencies=(BarFrequency.M15,),
        since=_DAY_ONE,
        through=_DAY_TWO,
    )

    assert loaded.authoritative_segments == (segment,)
    assert tuple(loaded.results) == (BarFrequency.M15,)
    assert market_data.queries == [
        ActualDominantTradingDayQuery("jm", BarFrequency.M15, _DAY_ONE, _DAY_TWO),
    ]


def test_loader_fails_closed_when_frequency_owner_conflicts_with_authority() -> None:
    true_segments = (
        DominantContractSegmentSummary("jm", "JM2609", _DAY_ONE, _DAY_TWO),
        DominantContractSegmentSummary("jm", "JM2701", _DAY_THREE, _DAY_FOUR),
    )
    market_data = _WindowAwareMarketData(
        probe={
            BarFrequency.M5: _result(
                _bars(BarFrequency.M5, (_DAY_TWO,)),
                (ResolvedContractSegment("JM2609", _DAY_TWO, _DAY_TWO),),
            ),
            BarFrequency.M15: _result(
                _bars(BarFrequency.M15, (_DAY_TWO,)),
                (ResolvedContractSegment("JM2701", _DAY_TWO, _DAY_TWO),),
            ),
        },
        full={},
        true_segments=true_segments,
    )

    with pytest.raises(
        ActualDominantResearchSegmentIdentityError,
        match="rank1 segment identity conflicts with containing summary",
    ):
        ActualDominantResearchSegmentLoader(market_data).load(
            symbol="jm",
            frequencies=_FREQUENCIES,
            since=_DAY_TWO,
            through=_DAY_THREE,
        )


def test_loader_accepts_sc2302_absent_from_weekly_owner_subset() -> None:
    sc2302_start = date(2023, 1, 3)
    sc2302_end = date(2023, 1, 4)
    sc2303_start = date(2023, 1, 5)
    first_complete_week = date(2023, 1, 6)
    sc2303_end = date(2023, 1, 31)
    authoritative = (
        DominantContractSegmentSummary(
            "sc", "SC2302", sc2302_start, sc2302_end
        ),
        DominantContractSegmentSummary(
            "sc", "SC2303", sc2303_start, sc2303_end
        ),
    )
    expected_segments = tuple(
        ResolvedContractSegment(
            segment.contract,
            segment.start_trading_day,
            segment.end_trading_day,
        )
        for segment in authoritative
    )
    results = {
        BarFrequency.D1: _result(
            _bars(
                BarFrequency.D1,
                (sc2302_start, sc2302_end, sc2303_start, first_complete_week),
            ),
            (
                ResolvedContractSegment("SC2302", sc2302_start, sc2302_end),
                ResolvedContractSegment(
                    "SC2303", sc2303_start, first_complete_week
                ),
            ),
        ),
        BarFrequency.W1: _result(
            _bars(BarFrequency.W1, (first_complete_week,)),
            (
                ResolvedContractSegment(
                    "SC2303", first_complete_week, first_complete_week
                ),
            ),
        ),
        BarFrequency.H1: _result(
            _bars(
                BarFrequency.H1,
                (sc2302_start, sc2302_end, sc2303_start, first_complete_week),
            ),
            (
                ResolvedContractSegment("SC2302", sc2302_start, sc2302_end),
                ResolvedContractSegment(
                    "SC2303", sc2303_start, first_complete_week
                ),
            ),
        ),
    }
    market_data = _WindowAwareMarketData(
        probe=results,
        full={},
        true_segments=authoritative,
    )

    loaded = ActualDominantResearchSegmentLoader(market_data).load(
        symbol="sc",
        frequencies=(BarFrequency.D1, BarFrequency.W1, BarFrequency.H1),
        since=sc2302_start,
        through=first_complete_week,
    )

    assert loaded.results == results
    assert loaded.authoritative_segments == expected_segments
    assert market_data.queries == [
        ActualDominantTradingDayQuery(
            "sc", frequency, sc2302_start, first_complete_week
        )
        for frequency in (BarFrequency.D1, BarFrequency.W1, BarFrequency.H1)
    ]


def test_loader_validates_sparse_weekly_owner_segments_bar_by_bar() -> None:
    authoritative = (
        DominantContractSegmentSummary("sc", "SC2302", _DAY_ONE, _DAY_ONE),
        DominantContractSegmentSummary("sc", "SC2303", _DAY_TWO, _DAY_TWO),
        DominantContractSegmentSummary("sc", "SC2302", _DAY_THREE, _DAY_THREE),
    )
    weekly = _result(
        _bars(BarFrequency.W1, (_DAY_ONE, _DAY_THREE)),
        (ResolvedContractSegment("SC2302", _DAY_ONE, _DAY_THREE),),
    )
    market_data = _WindowAwareMarketData(
        probe={BarFrequency.W1: weekly},
        full={},
        true_segments=authoritative,
    )

    loaded = ActualDominantResearchSegmentLoader(market_data).load(
        symbol="sc",
        frequencies=(BarFrequency.W1,),
        since=_DAY_ONE,
        through=_DAY_THREE,
    )

    assert loaded.results[BarFrequency.W1] is weekly
    assert tuple(segment.contract for segment in loaded.authoritative_segments) == (
        "SC2302",
        "SC2303",
        "SC2302",
    )


@pytest.mark.parametrize(
    ("segments", "message"),
    (
        (
            (ResolvedContractSegment("JM2609", _DAY_ONE, _DAY_ONE),),
            "rank1 segment identity is incomplete for 5m",
        ),
        (
            (
                ResolvedContractSegment("JM2609", _DAY_ONE, _DAY_TWO),
                ResolvedContractSegment("JM2701", _DAY_TWO, _DAY_TWO),
            ),
            "rank1 segments overlap",
        ),
    ),
)
def test_loader_fails_closed_for_segment_gap_or_overlap(
    segments: tuple[ResolvedContractSegment, ...],
    message: str,
) -> None:
    bars = _bars(BarFrequency.M5, (_DAY_ONE, _DAY_TWO))
    market_data = _WindowAwareMarketData(
        probe={
            BarFrequency.M5: _result(bars, segments),
            BarFrequency.M15: _result(
                _bars(BarFrequency.M15, (_DAY_ONE, _DAY_TWO)),
                segments,
            ),
        },
        full={},
        true_segments=(
            DominantContractSegmentSummary("jm", "JM2609", _DAY_ONE, _DAY_TWO),
        ),
    )

    with pytest.raises(ValueError, match=message):
        ActualDominantResearchSegmentLoader(market_data).load(
            symbol="jm",
            frequencies=_FREQUENCIES,
            since=_DAY_ONE,
            through=_DAY_TWO,
        )


def test_loader_reports_actual_frequency_for_cross_frequency_gap() -> None:
    complete_segment = (
        ResolvedContractSegment("JM2609", _DAY_ONE, _DAY_TWO),
    )
    incomplete_segment = (
        ResolvedContractSegment("JM2609", _DAY_ONE, _DAY_ONE),
    )
    market_data = _WindowAwareMarketData(
        probe={
            BarFrequency.M5: _result(
                _bars(BarFrequency.M5, (_DAY_ONE, _DAY_TWO)),
                complete_segment,
            ),
            BarFrequency.M15: _result(
                _bars(BarFrequency.M15, (_DAY_ONE, _DAY_TWO)),
                incomplete_segment,
            ),
        },
        full={},
        true_segments=(
            DominantContractSegmentSummary("jm", "JM2609", _DAY_ONE, _DAY_TWO),
        ),
    )

    with pytest.raises(
        ValueError,
        match="rank1 segment identity is incomplete for 15m",
    ):
        ActualDominantResearchSegmentLoader(market_data).load(
            symbol="jm",
            frequencies=_FREQUENCIES,
            since=_DAY_ONE,
            through=_DAY_TWO,
        )


def test_generic_loader_reports_the_actual_single_frequency_gap() -> None:
    incomplete_segment = (
        ResolvedContractSegment("JM2609", _DAY_ONE, _DAY_ONE),
    )
    market_data = _WindowAwareMarketData(
        probe={
            BarFrequency.M15: _result(
                _bars(BarFrequency.M15, (_DAY_ONE, _DAY_TWO)),
                incomplete_segment,
            ),
        },
        full={},
        true_segments=(
            DominantContractSegmentSummary(
                "jm", "JM2609", _DAY_ONE, _DAY_TWO
            ),
        ),
    )

    with pytest.raises(
        ValueError,
        match="rank1 segment identity is incomplete for 15m",
    ):
        ActualDominantResearchSegmentLoader(market_data).load(
            symbol="jm",
            frequencies=(BarFrequency.M15,),
            since=_DAY_ONE,
            through=_DAY_TWO,
        )


def test_loader_rejects_reversed_raw_segment_order() -> None:
    reversed_segments = (
        ResolvedContractSegment("JM2701", _DAY_THREE, _DAY_FOUR),
        ResolvedContractSegment("JM2609", _DAY_ONE, _DAY_TWO),
    )
    market_data = _WindowAwareMarketData(
        probe={
            BarFrequency.M5: _result(
                _bars(BarFrequency.M5, (_DAY_ONE, _DAY_THREE)),
                reversed_segments,
            ),
        },
        full={},
        true_segments=(
            DominantContractSegmentSummary(
                "jm", "JM2609", _DAY_ONE, _DAY_TWO
            ),
            DominantContractSegmentSummary(
                "jm", "JM2701", _DAY_THREE, _DAY_FOUR
            ),
        ),
    )

    with pytest.raises(ValueError, match="rank1 segment summaries overlap"):
        ActualDominantResearchSegmentLoader(market_data).load(
            symbol="jm",
            frequencies=(BarFrequency.M5,),
            since=_DAY_ONE,
            through=_DAY_THREE,
        )


def _bars(
    frequency: BarFrequency,
    trading_days: tuple[date, ...],
) -> tuple[CanonicalBar, ...]:
    counts: dict[date, int] = {}
    minute_step = 5 if frequency is BarFrequency.M5 else 15
    bars: list[CanonicalBar] = []
    for trading_day in trading_days:
        index = counts.get(trading_day, 0)
        counts[trading_day] = index + 1
        close = Decimal("100") + Decimal(index)
        bars.append(
            CanonicalBar(
                bar_end=datetime.combine(trading_day, datetime.min.time(), UTC)
                + timedelta(minutes=minute_step * (index + 1)),
                trading_day=trading_day,
                open=close,
                high=close + Decimal("1"),
                low=close - Decimal("1"),
                close=close,
                volume=Decimal("100"),
                turnover=None,
                open_interest=None,
            )
        )
    return tuple(bars)


def _result(
    bars: tuple[CanonicalBar, ...],
    segments: tuple[ResolvedContractSegment, ...],
) -> MarketSeriesResult:
    return MarketSeriesResult(
        request_identity={},
        bars=bars,
        coverage=(bars[0].bar_end, bars[-1].bar_end),
        resolved_contract_segments=segments,
    )


def _page_result(
    bars: tuple[CanonicalBar, ...],
    segments: tuple[ResolvedContractSegment, ...],
) -> MarketSeriesPageResult:
    return MarketSeriesPageResult(
        request_identity={},
        bars=bars,
        canonical_coverage=(bars[0].bar_end, bars[-1].bar_end),
        has_more_before=False,
        next_before=None,
        resolved_contract_segments=segments,
    )
