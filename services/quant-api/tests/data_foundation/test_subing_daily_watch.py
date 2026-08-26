from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.market_data.actual_dominant_research import (
    ActualDominantResearchSegmentIdentityError,
    ActualDominantStitchedResearchLoader,
    ActualDominantStitchedResearchSeries,
)
from app.market_data.domain import (
    ActualDominantRecentBarsQuery,
    BarFrequency,
    CanonicalBar,
    MarketSeriesPageResult,
    ResolvedContractSegment,
)
from app.market_data.market_data_service import (
    DominantContractSegmentSummary,
    MarketDataError,
)
from app.market_data.subing_daily_watch import (
    SubingDailyWatchBuilder,
    SubingDailyWatchDecision,
    SubingDailyWatchError,
    SubingDailyWatchProduct,
    classify_daily_watch,
)
from app.market_data.subing_ema_trend import (
    PriceSide,
    SubingStitchedEmaTrendSnapshot,
)


_SOURCE_DAY = date(2026, 8, 21)
_TARGET_DAY = date(2026, 8, 24)
_GENERATED_AT = datetime(2026, 8, 21, 18, 30, tzinfo=UTC)


def _trend(
    timeframe: BarFrequency,
    *,
    direction: str,
    contract: str = "A2609",
    segment_start: date = date(2026, 7, 1),
) -> SubingStitchedEmaTrendSnapshot:
    if direction == "long":
        close = Decimal("102")
        ema21 = Decimal("100")
        price_side = PriceSide.ABOVE
        slope_5 = Decimal("1")
        slope_10 = Decimal("2")
    elif direction == "short":
        close = Decimal("98")
        ema21 = Decimal("100")
        price_side = PriceSide.BELOW
        slope_5 = Decimal("-1")
        slope_10 = Decimal("-2")
    elif direction == "neutral":
        close = Decimal("100")
        ema21 = Decimal("100")
        price_side = PriceSide.EQUAL
        slope_5 = Decimal("1")
        slope_10 = Decimal("2")
    else:
        raise AssertionError(f"unsupported test direction: {direction}")
    return SubingStitchedEmaTrendSnapshot(
        timeframe=timeframe,
        bar_end=datetime(2026, 8, 21, 7, tzinfo=UTC),
        trading_day=_SOURCE_DAY,
        contract=contract,
        current_segment_start_trading_day=segment_start,
        warmup_start_trading_day=date(2026, 6, 1),
        warmup_bar_count=30,
        warmup_segment_count=2,
        history_mode="rank1_stitched_raw",
        close=close,
        ema21=ema21,
        price_side=price_side,
        slope_5_raw=slope_5,
        slope_10_raw=slope_10,
        slope_5_bps_per_bar=slope_5,
        slope_10_bps_per_bar=slope_10,
    )


@pytest.mark.parametrize(
    ("daily", "hourly", "decision", "reason_codes"),
    [
        (
            _trend(BarFrequency.D1, direction="long"),
            _trend(BarFrequency.H1, direction="long"),
            SubingDailyWatchDecision.LONG_WATCH,
            ("D1_H1_LONG_ALIGNED",),
        ),
        (
            _trend(BarFrequency.D1, direction="short"),
            _trend(BarFrequency.H1, direction="short"),
            SubingDailyWatchDecision.SHORT_WATCH,
            ("D1_H1_SHORT_ALIGNED",),
        ),
        (
            _trend(BarFrequency.D1, direction="neutral"),
            _trend(BarFrequency.H1, direction="long"),
            SubingDailyWatchDecision.EXCLUDED,
            ("D1_TREND_NEUTRAL",),
        ),
        (
            _trend(BarFrequency.D1, direction="long"),
            _trend(BarFrequency.H1, direction="neutral"),
            SubingDailyWatchDecision.EXCLUDED,
            ("H1_TREND_NEUTRAL",),
        ),
        (
            _trend(BarFrequency.D1, direction="long"),
            _trend(BarFrequency.H1, direction="short"),
            SubingDailyWatchDecision.EXCLUDED,
            ("D1_H1_DIRECTION_MISMATCH",),
        ),
    ],
)
def test_classifier_uses_only_sign_alignment(
    daily: SubingStitchedEmaTrendSnapshot,
    hourly: SubingStitchedEmaTrendSnapshot,
    decision: SubingDailyWatchDecision,
    reason_codes: tuple[str, ...],
) -> None:
    """Catches admitting a watch when D1 and H1 signs are not aligned."""
    result = classify_daily_watch(daily, hourly)

    assert result.decision is decision
    assert result.reason_codes == reason_codes


@pytest.mark.parametrize(
    "daily",
    [
        replace(
            _trend(BarFrequency.D1, direction="long"),
            close=Decimal("100"),
            ema21=Decimal("100"),
            price_side=PriceSide.EQUAL,
        ),
        replace(
            _trend(BarFrequency.D1, direction="long"),
            slope_5_bps_per_bar=Decimal(0),
        ),
        replace(
            _trend(BarFrequency.D1, direction="long"),
            slope_10_bps_per_bar=Decimal(0),
        ),
        replace(
            _trend(BarFrequency.D1, direction="long"),
            slope_5_bps_per_bar=Decimal("-1"),
        ),
    ],
)
def test_classifier_treats_equal_zero_or_conflicting_daily_fact_as_neutral(
    daily: SubingStitchedEmaTrendSnapshot,
) -> None:
    """Catches equality, zero slope, or conflicting slopes becoming directional."""
    result = classify_daily_watch(
        daily,
        _trend(BarFrequency.H1, direction="long"),
    )

    assert result.decision is SubingDailyWatchDecision.EXCLUDED
    assert result.reason_codes == ("D1_TREND_NEUTRAL",)


class _FakeStitchedLoader:
    def __init__(
        self,
        outcomes: dict[str, ActualDominantStitchedResearchSeries | Exception],
    ) -> None:
        self.outcomes = outcomes
        self.requests: list[tuple[str, tuple[BarFrequency, ...], date, int]] = []

    def load(
        self,
        *,
        symbol: str,
        frequencies: Sequence[BarFrequency],
        through: date,
        limit: int = 30,
    ) -> ActualDominantStitchedResearchSeries:
        self.requests.append((symbol, tuple(frequencies), through, limit))
        outcome = self.outcomes[symbol]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _FakeStitchedReader:
    def __init__(
        self,
        *,
        results: dict[BarFrequency, MarketSeriesPageResult],
        current_segment: ResolvedContractSegment,
    ) -> None:
        self._results = results
        self._current_segment = current_segment

    def query_actual_dominant_recent_bars(
        self,
        request: ActualDominantRecentBarsQuery,
    ) -> MarketSeriesPageResult:
        return self._results[request.frequency]

    def dominant_segment_for_day(
        self,
        symbol: str,
        trading_day: date,
    ) -> DominantContractSegmentSummary:
        return DominantContractSegmentSummary(
            symbol=symbol,
            contract=self._current_segment.contract,
            start_trading_day=self._current_segment.start_trading_day,
            end_trading_day=self._current_segment.end_trading_day,
        )


def _bars(
    *,
    frequency: BarFrequency,
    direction: str,
    source_day: date = _SOURCE_DAY,
    count: int = 40,
) -> tuple[CanonicalBar, ...]:
    if frequency is BarFrequency.D1:
        first_day = source_day - timedelta(days=count - 1)
        ends = tuple(
            datetime.combine(
                first_day + timedelta(days=index), datetime.min.time(), UTC
            )
            + timedelta(hours=7)
            for index in range(count)
        )
        trading_days = tuple(
            first_day + timedelta(days=index) for index in range(count)
        )
    else:
        start = datetime.combine(source_day, datetime.min.time(), UTC) - timedelta(
            hours=count - 8
        )
        ends = tuple(start + timedelta(hours=index) for index in range(count))
        trading_days = tuple(
            source_day - timedelta(days=(count - 1 - index) // 8)
            for index in range(count)
        )
    if direction == "long":
        closes = tuple(Decimal("100") + Decimal(index) for index in range(count))
    elif direction == "short":
        closes = tuple(Decimal("200") - Decimal(index) for index in range(count))
    elif direction == "neutral":
        closes = tuple(Decimal("100") for _ in range(count))
    else:
        raise AssertionError(f"unsupported test direction: {direction}")
    return tuple(
        CanonicalBar(
            bar_end=bar_end,
            trading_day=trading_day,
            open=close,
            high=close + Decimal("1"),
            low=close - Decimal("1"),
            close=close,
            volume=Decimal("100"),
            turnover=None,
            open_interest=None,
        )
        for bar_end, trading_day, close in zip(
            ends,
            trading_days,
            closes,
            strict=True,
        )
    )


def _stitched_series(
    *,
    symbol: str,
    direction: str,
    source_day: date = _SOURCE_DAY,
    daily_count: int = 40,
    hourly_count: int = 40,
    contract: str | None = None,
) -> ActualDominantStitchedResearchSeries:
    physical_contract = contract or f"{symbol.upper()}2609"
    current_segment = ResolvedContractSegment(
        physical_contract,
        source_day - timedelta(days=4),
        source_day,
    )
    results = {}
    for frequency, count in (
        (BarFrequency.D1, daily_count),
        (BarFrequency.H1, hourly_count),
    ):
        bars = _bars(
            frequency=frequency,
            direction=direction,
            source_day=source_day,
            count=count,
        )
        segments = (current_segment,)
        if bars[0].trading_day < current_segment.start_trading_day:
            previous_segment = ResolvedContractSegment(
                f"{symbol.upper()}2608",
                bars[0].trading_day,
                current_segment.start_trading_day - timedelta(days=1),
            )
            segments = (previous_segment, current_segment)
        results[frequency] = MarketSeriesPageResult(
            request_identity={
                "symbol": symbol,
                "frequency": frequency.value,
                "series_kind": "actual_dominant",
            },
            bars=bars,
            canonical_coverage=(bars[0].bar_end, bars[-1].bar_end),
            has_more_before=True,
            next_before=bars[0].bar_end,
            resolved_contract_segments=segments,
        )
    return ActualDominantStitchedResearchSeries(
        results=results,
        current_segment=current_segment,
    )


def _metadata(*symbols: str) -> dict[str, SubingDailyWatchProduct]:
    return {
        symbol: SubingDailyWatchProduct(
            symbol=symbol,
            product_name=f"Product {symbol.upper()}",
            sector="test-sector",
        )
        for symbol in symbols
    }


def _builder(
    loader: _FakeStitchedLoader,
    *,
    products: tuple[str, ...] = ("a",),
    metadata: dict[str, SubingDailyWatchProduct] | None = None,
) -> SubingDailyWatchBuilder:
    return SubingDailyWatchBuilder(
        stitched_loader=loader,
        products=products,
        product_metadata=metadata if metadata is not None else _metadata(*products),
        expected_universe_size=len(products),
    )


def test_builder_requests_stitched_history_through_source_day_with_limit_30() -> None:
    """Catches reintroducing V1's since read or a non-30-bar warm-up request."""
    loader = _FakeStitchedLoader({"a": _stitched_series(symbol="a", direction="long")})

    snapshot = _builder(loader).build(
        source_trading_day=_SOURCE_DAY,
        target_trading_day=_TARGET_DAY,
        generated_at=_GENERATED_AT,
    )

    assert loader.requests == [
        (
            "a",
            (BarFrequency.D1, BarFrequency.H1),
            _SOURCE_DAY,
            30,
        )
    ]
    item = snapshot.items[0]
    assert item.daily is not None
    assert item.hourly is not None
    assert item.daily.trading_day == _SOURCE_DAY
    assert item.hourly.trading_day == _SOURCE_DAY
    assert item.daily.contract == "A2609"
    assert item.hourly.contract == "A2609"
    assert item.daily.current_segment_start_trading_day == date(2026, 8, 17)
    assert item.hourly.current_segment_start_trading_day == date(2026, 8, 17)


def test_builder_classifies_rollover_stitched_30_bar_history() -> None:
    """Catches treating a short current segment as D1 history insufficiency."""
    loader = _FakeStitchedLoader(
        {
            "a": _stitched_series(
                symbol="a",
                direction="long",
                daily_count=30,
                hourly_count=30,
            )
        }
    )

    item = (
        _builder(loader)
        .build(
            source_trading_day=_SOURCE_DAY,
            target_trading_day=_TARGET_DAY,
            generated_at=_GENERATED_AT,
        )
        .items[0]
    )

    assert item.decision is SubingDailyWatchDecision.LONG_WATCH
    assert item.unavailable_reasons == ()
    assert item.daily is not None
    assert item.daily.warmup_bar_count == 30
    assert item.daily.warmup_segment_count == 2
    assert item.daily.current_segment_start_trading_day == date(2026, 8, 17)


def test_builder_preserves_complete_active_universe_ledger() -> None:
    """Catches dropping excluded/unavailable products or reordering the scope."""
    loader = _FakeStitchedLoader(
        {
            "a": _stitched_series(symbol="a", direction="long"),
            "b": _stitched_series(symbol="b", direction="short"),
            "c": _stitched_series(symbol="c", direction="neutral"),
            "d": MarketDataError("DATASET_OR_PARTITION_MISSING"),
        }
    )

    snapshot = _builder(loader, products=("a", "b", "c", "d")).build(
        source_trading_day=_SOURCE_DAY,
        target_trading_day=_TARGET_DAY,
        generated_at=_GENERATED_AT,
    )

    assert [item.symbol for item in snapshot.items] == ["a", "b", "c", "d"]
    assert [item.decision for item in snapshot.items] == [
        SubingDailyWatchDecision.LONG_WATCH,
        SubingDailyWatchDecision.SHORT_WATCH,
        SubingDailyWatchDecision.EXCLUDED,
        SubingDailyWatchDecision.UNAVAILABLE,
    ]
    assert snapshot.counts == {
        "universe": 4,
        "long_watch": 1,
        "short_watch": 1,
        "excluded": 1,
        "unavailable": 1,
    }
    assert snapshot.items[3].unavailable_reasons == ("DOMINANT_SEGMENT_UNAVAILABLE",)


def test_builder_rejects_duplicate_active_products() -> None:
    """Catches one active product receiving multiple ledger rows."""
    loader = _FakeStitchedLoader({"a": _stitched_series(symbol="a", direction="long")})

    with pytest.raises(SubingDailyWatchError) as raised:
        SubingDailyWatchBuilder(
            stitched_loader=loader,
            products=("a", "a"),
            product_metadata=_metadata("a"),
            expected_universe_size=2,
        )

    assert raised.value.code == "ACTIVE_OPERATIONAL_SCOPE_MISMATCH"
    assert loader.requests == []


def test_builder_keeps_missing_metadata_as_typed_unavailable() -> None:
    """Catches missing display metadata dropping an otherwise active product."""
    loader = _FakeStitchedLoader({"a": _stitched_series(symbol="a", direction="long")})

    snapshot = _builder(loader, metadata={}).build(
        source_trading_day=_SOURCE_DAY,
        target_trading_day=_TARGET_DAY,
        generated_at=_GENERATED_AT,
    )

    item = snapshot.items[0]
    assert item.decision is SubingDailyWatchDecision.UNAVAILABLE
    assert item.product_name == ""
    assert item.sector == ""
    assert item.unavailable_reasons == ("PRODUCT_METADATA_UNAVAILABLE",)
    assert loader.requests == []


def test_builder_marks_latest_fact_before_source_day_unavailable() -> None:
    """Catches silently using a stale D1/H1 observation for the target ledger."""
    stale = _stitched_series(
        symbol="a",
        direction="long",
        source_day=_SOURCE_DAY - timedelta(days=1),
    )
    current_segment = replace(
        stale.current_segment,
        end_trading_day=_SOURCE_DAY,
    )
    stale_results = {
        frequency: replace(
            result,
            resolved_contract_segments=tuple(
                current_segment if segment == stale.current_segment else segment
                for segment in result.resolved_contract_segments
            ),
        )
        for frequency, result in stale.results.items()
    }
    loader = _FakeStitchedLoader(
        {
            "a": ActualDominantStitchedResearchSeries(
                results=stale_results,
                current_segment=current_segment,
            )
        }
    )

    item = (
        _builder(loader)
        .build(
            source_trading_day=_SOURCE_DAY,
            target_trading_day=_TARGET_DAY,
            generated_at=_GENERATED_AT,
        )
        .items[0]
    )

    assert item.decision is SubingDailyWatchDecision.UNAVAILABLE
    assert item.unavailable_reasons == ("SOURCE_TRADING_DAY_MISSING",)


def test_builder_maps_real_loader_missing_source_day_to_typed_unavailable() -> None:
    """Catches the service-loader path swallowing source-day Bar absence."""
    loaded = _stitched_series(symbol="a", direction="long")
    daily = loaded.results[BarFrequency.D1]
    results = dict(loaded.results)
    results[BarFrequency.D1] = replace(daily, bars=daily.bars[:-1])
    reader = _FakeStitchedReader(
        results=results,
        current_segment=loaded.current_segment,
    )
    builder = SubingDailyWatchBuilder(
        stitched_loader=ActualDominantStitchedResearchLoader(reader),
        products=("a",),
        product_metadata=_metadata("a"),
        expected_universe_size=1,
    )

    item = builder.build(
        source_trading_day=_SOURCE_DAY,
        target_trading_day=_TARGET_DAY,
        generated_at=_GENERATED_AT,
    ).items[0]

    assert item.decision is SubingDailyWatchDecision.UNAVAILABLE
    assert item.unavailable_reasons == ("SOURCE_TRADING_DAY_MISSING",)


def test_builder_keeps_real_loader_corrupt_page_as_identity_mismatch() -> None:
    """Catches corrupt stitched identity being mislabeled as source-day absence."""
    loaded = _stitched_series(symbol="a", direction="long")
    daily = loaded.results[BarFrequency.D1]
    corrupt = replace(
        daily.bars[0],
        trading_day=_SOURCE_DAY + timedelta(days=1),
    )
    results = dict(loaded.results)
    results[BarFrequency.D1] = replace(
        daily,
        bars=(corrupt, *daily.bars[1:]),
    )
    reader = _FakeStitchedReader(
        results=results,
        current_segment=loaded.current_segment,
    )
    builder = SubingDailyWatchBuilder(
        stitched_loader=ActualDominantStitchedResearchLoader(reader),
        products=("a",),
        product_metadata=_metadata("a"),
        expected_universe_size=1,
    )

    item = builder.build(
        source_trading_day=_SOURCE_DAY,
        target_trading_day=_TARGET_DAY,
        generated_at=_GENERATED_AT,
    ).items[0]

    assert item.decision is SubingDailyWatchDecision.UNAVAILABLE
    assert item.unavailable_reasons == ("DATA_IDENTITY_MISMATCH",)


def test_builder_rejects_d1_h1_physical_contract_mismatch() -> None:
    """Catches combining trends from different physical dominant contracts."""
    loaded = _stitched_series(symbol="a", direction="long")
    hourly = loaded.results[BarFrequency.H1]
    mismatched = ResolvedContractSegment(
        "A2610",
        loaded.current_segment.start_trading_day,
        loaded.current_segment.end_trading_day,
    )
    results = dict(loaded.results)
    results[BarFrequency.H1] = replace(
        hourly,
        resolved_contract_segments=(mismatched,),
    )
    loader = _FakeStitchedLoader(
        {
            "a": ActualDominantStitchedResearchSeries(
                results=results,
                current_segment=loaded.current_segment,
            )
        }
    )

    item = (
        _builder(loader)
        .build(
            source_trading_day=_SOURCE_DAY,
            target_trading_day=_TARGET_DAY,
            generated_at=_GENERATED_AT,
        )
        .items[0]
    )

    assert item.decision is SubingDailyWatchDecision.UNAVAILABLE
    assert item.unavailable_reasons == ("DATA_IDENTITY_MISMATCH",)


def test_builder_rejects_stitched_bar_after_source_day_as_identity_mismatch() -> None:
    """Catches a future trading-day Bar entering source-day Daily Watch facts."""
    loaded = _stitched_series(symbol="a", direction="long")
    daily = loaded.results[BarFrequency.D1]
    future_bar = replace(
        daily.bars[0],
        trading_day=_SOURCE_DAY + timedelta(days=1),
    )
    results = dict(loaded.results)
    results[BarFrequency.D1] = replace(
        daily,
        bars=(future_bar, *daily.bars[1:]),
    )
    loader = _FakeStitchedLoader(
        {
            "a": ActualDominantStitchedResearchSeries(
                results=results,
                current_segment=loaded.current_segment,
            )
        }
    )

    item = (
        _builder(loader)
        .build(
            source_trading_day=_SOURCE_DAY,
            target_trading_day=_TARGET_DAY,
            generated_at=_GENERATED_AT,
        )
        .items[0]
    )

    assert item.decision is SubingDailyWatchDecision.UNAVAILABLE
    assert item.unavailable_reasons == ("DATA_IDENTITY_MISMATCH",)


def test_builder_maps_probe_identity_failure_to_typed_unavailable() -> None:
    """Catches an identity failure aborting the complete-universe ledger."""
    loader = _FakeStitchedLoader(
        {
            "a": ActualDominantResearchSegmentIdentityError(
                "rank1 segment identity is missing or inconsistent"
            )
        }
    )

    item = (
        _builder(loader)
        .build(
            source_trading_day=_SOURCE_DAY,
            target_trading_day=_TARGET_DAY,
            generated_at=_GENERATED_AT,
        )
        .items[0]
    )

    assert item.decision is SubingDailyWatchDecision.UNAVAILABLE
    assert item.unavailable_reasons == ("DATA_IDENTITY_MISMATCH",)


@pytest.mark.parametrize(
    ("daily_count", "hourly_count", "reason"),
    [
        (29, 30, "D1_HISTORY_INSUFFICIENT"),
        (30, 29, "H1_HISTORY_INSUFFICIENT"),
    ],
)
def test_builder_preserves_typed_stitched_frequency_history_insufficient(
    daily_count: int,
    hourly_count: int,
    reason: str,
) -> None:
    """Catches incomplete warm-up being classified as a directional trend."""
    loader = _FakeStitchedLoader(
        {
            "a": _stitched_series(
                symbol="a",
                direction="long",
                daily_count=daily_count,
                hourly_count=hourly_count,
            )
        }
    )

    item = (
        _builder(loader)
        .build(
            source_trading_day=_SOURCE_DAY,
            target_trading_day=_TARGET_DAY,
            generated_at=_GENERATED_AT,
        )
        .items[0]
    )

    assert item.decision is SubingDailyWatchDecision.UNAVAILABLE
    assert item.unavailable_reasons == (reason,)


def test_builder_propagates_unexpected_programming_error() -> None:
    """Catches programming defects being mislabeled as known data unavailability."""
    loader = _FakeStitchedLoader({"a": RuntimeError("unexpected bug")})

    with pytest.raises(RuntimeError, match="unexpected bug"):
        _builder(loader).build(
            source_trading_day=_SOURCE_DAY,
            target_trading_day=_TARGET_DAY,
            generated_at=_GENERATED_AT,
        )
