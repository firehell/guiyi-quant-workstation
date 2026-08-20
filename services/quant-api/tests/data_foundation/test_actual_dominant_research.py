from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.market_data.actual_dominant_research import (
    ActualDominantResearchSegmentLoader,
    ActualDominantResearchSegmentIdentityError,
)
from app.market_data.domain import (
    ActualDominantTradingDayQuery,
    BarFrequency,
    CanonicalBar,
    MarketSeriesResult,
    ResolvedContractSegment,
)
from app.market_data.market_data_service import DominantContractSegmentSummary


_DAY_ONE = date(2026, 8, 3)
_DAY_TWO = date(2026, 8, 4)
_DAY_THREE = date(2026, 8, 5)
_DAY_FOUR = date(2026, 8, 6)
_FREQUENCIES = (BarFrequency.M5, BarFrequency.M15)


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
        self._query_counts = dict.fromkeys(_FREQUENCIES, 0)
        self.queries: list[ActualDominantTradingDayQuery] = []
        self.segment_requests: list[tuple[str, date]] = []

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


def test_loader_restores_true_segments_and_reads_full_causal_prefix() -> None:
    clipped_segments = (
        ResolvedContractSegment("JM2609", _DAY_TWO, _DAY_TWO),
        ResolvedContractSegment("JM2701", _DAY_THREE, _DAY_THREE),
    )
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
    probe = {
        frequency: _result(
            _bars(frequency, (_DAY_TWO, _DAY_THREE)),
            clipped_segments,
        )
        for frequency in _FREQUENCIES
    }
    full = {
        frequency: _result(
            _bars(frequency, (_DAY_ONE, _DAY_TWO, _DAY_THREE)),
            restored_segments,
        )
        for frequency in _FREQUENCIES
    }
    market_data = _WindowAwareMarketData(
        probe=probe,
        full=full,
        true_segments=true_segments,
    )

    loaded = ActualDominantResearchSegmentLoader(market_data).load(
        symbol="jm",
        frequencies=_FREQUENCIES,
        since=_DAY_TWO,
        through=_DAY_THREE,
    )

    assert loaded.results == full
    assert loaded.segments == restored_segments
    assert market_data.queries == [
        ActualDominantTradingDayQuery("jm", BarFrequency.M5, _DAY_TWO, _DAY_THREE),
        ActualDominantTradingDayQuery("jm", BarFrequency.M15, _DAY_TWO, _DAY_THREE),
        ActualDominantTradingDayQuery("jm", BarFrequency.M5, _DAY_ONE, _DAY_THREE),
        ActualDominantTradingDayQuery("jm", BarFrequency.M15, _DAY_ONE, _DAY_THREE),
    ]
    assert set(market_data.segment_requests) == {
        ("jm", _DAY_ONE),
        ("jm", _DAY_TWO),
        ("jm", _DAY_THREE),
    }


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


class _UnavailableMarketData:
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

    assert loaded.segments == (segment,)
    assert tuple(loaded.results) == (BarFrequency.M15,)
    assert market_data.queries == [
        ActualDominantTradingDayQuery(
            "jm", BarFrequency.M15, _DAY_ONE, _DAY_TWO
        ),
        ActualDominantTradingDayQuery(
            "jm", BarFrequency.M15, _DAY_ONE, _DAY_TWO
        ),
    ]


def test_loader_fails_closed_when_frequency_segment_identities_differ() -> None:
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
                _bars(BarFrequency.M15, (_DAY_THREE,)),
                (ResolvedContractSegment("JM2701", _DAY_THREE, _DAY_THREE),),
            ),
        },
        full={},
        true_segments=true_segments,
    )

    with pytest.raises(
        ActualDominantResearchSegmentIdentityError,
        match="rank1 segment identity is missing or inconsistent",
    ):
        ActualDominantResearchSegmentLoader(market_data).load(
            symbol="jm",
            frequencies=_FREQUENCIES,
            since=_DAY_TWO,
            through=_DAY_THREE,
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
            DominantContractSegmentSummary("jm", "JM2701", _DAY_TWO, _DAY_TWO),
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


def test_loader_fails_closed_when_probe_and_full_identities_diverge() -> None:
    true_segment = DominantContractSegmentSummary(
        "jm", "JM2609", _DAY_ONE, _DAY_TWO
    )
    probe_segment = (ResolvedContractSegment("JM2609", _DAY_TWO, _DAY_TWO),)
    full_segment = (ResolvedContractSegment("JM2701", _DAY_ONE, _DAY_TWO),)
    market_data = _WindowAwareMarketData(
        probe={
            frequency: _result(_bars(frequency, (_DAY_TWO,)), probe_segment)
            for frequency in _FREQUENCIES
        },
        full={
            frequency: _result(
                _bars(frequency, (_DAY_ONE, _DAY_TWO)),
                full_segment,
            )
            for frequency in _FREQUENCIES
        },
        true_segments=(true_segment,),
    )

    with pytest.raises(ValueError, match="rank1 segment identity"):
        ActualDominantResearchSegmentLoader(market_data).load(
            symbol="jm",
            frequencies=_FREQUENCIES,
            since=_DAY_TWO,
            through=_DAY_TWO,
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
