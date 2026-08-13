from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from app.market_data.domain import BarFrequency, CanonicalBar
from app.market_data.subing_calibration import (
    DirectionalSide,
    build_outcomes_at,
    build_research_samples,
    candidate_quantiles,
    evaluate_threshold,
)
from app.market_data.subing_research import (
    MacdCross,
    PriceSide,
    SubingFactorResult,
    SubingFactorSnapshot,
    SubingFactorStatus,
)


_DAY = date(2026, 8, 3)
_SEGMENT_START = date(2026, 8, 1)
_START = datetime(2026, 8, 3, 1, tzinfo=UTC)


def _bar(
    index: int,
    *,
    close: str,
    high: str,
    low: str,
    trading_day: date = _DAY,
) -> CanonicalBar:
    value = Decimal(close)
    return CanonicalBar(
        bar_end=_START + timedelta(minutes=5 * index),
        trading_day=trading_day,
        open=value,
        high=Decimal(high),
        low=Decimal(low),
        close=value,
        volume=Decimal("100"),
        turnover=None,
        open_interest=None,
    )


def _factor(
    bar: CanonicalBar,
    *,
    timeframe: BarFrequency = BarFrequency.M5,
    contract: str = "JM2609",
    segment_start: date = _SEGMENT_START,
    ema21: str = "90",
    slope5: str = "2",
    slope10: str = "1",
    price_side: PriceSide = PriceSide.ABOVE,
) -> SubingFactorResult:
    return SubingFactorResult(
        status=SubingFactorStatus.READY,
        snapshot=SubingFactorSnapshot(
            timeframe=timeframe,
            bar_end=bar.bar_end,
            trading_day=bar.trading_day,
            contract=contract,
            segment_start_trading_day=segment_start,
            bar_source="canonical",
            close=bar.close,
            ema21=Decimal(ema21),
            price_side=price_side,
            slope_5_raw=Decimal("1"),
            slope_10_raw=Decimal("1"),
            slope_5_bps_per_bar=Decimal(slope5),
            slope_10_bps_per_bar=Decimal(slope10),
            macd_dif=Decimal("1"),
            macd_dea=Decimal("0"),
            macd_histogram=Decimal("2"),
            macd_cross=MacdCross.GOLDEN,
            macd_cross_level=Decimal("0.5"),
            macd_zero_distance_abs=Decimal("0.5"),
            macd_zero_distance_bps=Decimal("50"),
            volume=Decimal("100"),
            previous_volume=Decimal("100"),
            volume_ratio_prev=Decimal("1"),
        ),
    )


def _series(*, timeframe: BarFrequency = BarFrequency.M5):
    bars = (
        _bar(0, close="100", high="101", low="99"),
        _bar(1, close="101", high="103", low="99"),
        _bar(2, close="102", high="105", low="98"),
        _bar(3, close="103", high="104", low="100"),
        _bar(4, close="104", high="106", low="101"),
        _bar(5, close="105", high="107", low="102"),
        _bar(6, close="106", high="108", low="103"),
        _bar(7, close="107", high="109", low="104"),
        _bar(8, close="108", high="110", low="105"),
    )
    return bars, tuple(_factor(bar, timeframe=timeframe) for bar in bars)


def test_build_outcomes_uses_exact_long_and_short_3k_formulas() -> None:
    bars, factors = _series()

    long_outcome = build_outcomes_at(
        factors, bars, index=0, direction=DirectionalSide.LONG, horizons=(3,)
    )[3]
    short_outcome = build_outcomes_at(
        factors, bars, index=0, direction=DirectionalSide.SHORT, horizons=(3,)
    )[3]

    assert long_outcome is not None
    assert long_outcome.directional_return_bps == Decimal("300")
    assert long_outcome.mfe_bps == Decimal("500")
    assert long_outcome.mae_bps == Decimal("-200")
    assert long_outcome.ema21_failure is False
    assert short_outcome is not None
    assert short_outcome.directional_return_bps == Decimal("-300")
    assert short_outcome.mfe_bps == Decimal("200")
    assert short_outcome.mae_bps == Decimal("-500")


def test_intraday_outcomes_never_cross_trading_day_or_rank1_segment() -> None:
    bars, factors = _series()
    next_day_bar = replace(bars[3], trading_day=date(2026, 8, 4))
    next_segment = _factor(
        next_day_bar,
        contract="JM2701",
        segment_start=date(2026, 8, 4),
    )

    day_poison = build_outcomes_at(
        factors,
        (*bars[:3], next_day_bar, *bars[4:]),
        index=0,
        direction=DirectionalSide.LONG,
        horizons=(3,),
    )
    segment_poison = build_outcomes_at(
        (*factors[:3], next_segment, *factors[4:]),
        (*bars[:3], next_day_bar, *bars[4:]),
        index=0,
        direction=DirectionalSide.LONG,
        horizons=(3,),
    )

    assert day_poison[3] is None
    assert segment_poison[3] is None


def test_daily_outcomes_may_cross_day_but_not_rank1_segment() -> None:
    bars, factors = _series(timeframe=BarFrequency.D1)
    later = tuple(
        replace(bar, trading_day=_DAY + timedelta(days=index))
        for index, bar in enumerate(bars)
    )
    daily_factors = tuple(
        _factor(bar, timeframe=BarFrequency.D1) for bar in later
    )

    outcomes = build_outcomes_at(
        daily_factors,
        later,
        index=0,
        direction=DirectionalSide.LONG,
        horizons=(3,),
    )
    changed_segment = replace(
        daily_factors[3].snapshot,
        contract="JM2701",
        segment_start_trading_day=date(2026, 8, 6),
    )
    assert changed_segment is not None
    poison = build_outcomes_at(
        (
            *daily_factors[:3],
            SubingFactorResult(SubingFactorStatus.READY, changed_segment),
            *daily_factors[4:],
        ),
        later,
        index=0,
        direction=DirectionalSide.LONG,
        horizons=(3,),
    )

    assert outcomes[3] is not None
    assert poison[3] is None


def test_research_samples_use_only_the_explicit_direction_selector() -> None:
    bars, factors = _series()

    samples = build_research_samples(
        factors,
        bars,
        horizons=(3, 5, 8),
        direction_selector=(
            lambda index, factor: DirectionalSide.LONG if index == 0 else None
        ),
    )

    assert len(samples) == 1
    assert samples[0].direction is DirectionalSide.LONG
    assert samples[0].studied_value == Decimal("2")
    assert samples[0].outcomes[3] is not None
    assert samples[0].outcomes[3].directional_return_bps == Decimal("300")
    assert samples[0].outcomes[5] is not None
    assert samples[0].outcomes[8] is not None


def test_slope_selector_excludes_wrong_side_or_disagreeing_slopes() -> None:
    bars, factors = _series()
    below = replace(
        factors[1].snapshot,
        price_side=PriceSide.BELOW,
        slope_5_bps_per_bar=Decimal("-2"),
        slope_10_bps_per_bar=Decimal("-1"),
    )
    assert below is not None
    disagreeing = replace(
        factors[2].snapshot,
        price_side=PriceSide.ABOVE,
        slope_5_bps_per_bar=Decimal("2"),
        slope_10_bps_per_bar=Decimal("-1"),
    )
    assert disagreeing is not None
    mixed = (
        factors[0],
        SubingFactorResult(SubingFactorStatus.READY, below),
        SubingFactorResult(SubingFactorStatus.READY, disagreeing),
        *factors[3:],
    )

    samples = build_research_samples(mixed, bars, horizons=(3, 5, 8))

    assert [sample.direction for sample in samples[:2]] == [
        DirectionalSide.LONG,
        DirectionalSide.SHORT,
    ]
    assert all(sample.factor.bar_end != bars[2].bar_end for sample in samples)


def test_candidate_quantiles_are_inclusive_and_explicitly_unavailable() -> None:
    assert candidate_quantiles(
        [Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4"), Decimal("5")]
    ) == (Decimal("1.4"), Decimal("1.8"), Decimal("2.2"))
    assert candidate_quantiles([Decimal("7.5")]) == (
        Decimal("7.5"),
        Decimal("7.5"),
        Decimal("7.5"),
    )
    assert candidate_quantiles([]) is None


def test_threshold_evaluation_reports_hand_checked_horizon_statistics() -> None:
    bars, factors = _series()
    base = build_research_samples(
        factors,
        bars,
        horizons=(3,),
        direction_selector=(
            lambda index, factor: DirectionalSide.LONG if index < 3 else None
        ),
    )
    samples = (
        replace(base[0], studied_value=Decimal("1")),
        replace(base[1], studied_value=Decimal("2")),
        replace(base[2], studied_value=Decimal("3")),
    )

    evaluation = evaluate_threshold(samples, Decimal("1"), horizons=(3,))

    assert evaluation.threshold == Decimal("1")
    assert evaluation.sample_count == 2
    assert evaluation.horizons[3].sample_count == 2
    assert evaluation.horizons[3].median_directional_return_bps == Decimal(
        "295.5736750145602795573675014"
    )
    assert evaluation.horizons[3].median_mfe_bps == Decimal(
        "492.6227916909337992622791690"
    )
    assert evaluation.horizons[3].median_mae_bps == Decimal(
        "-246.5540671714230246554067172"
    )
    assert evaluation.horizons[3].ema21_failure_rate == Decimal("0")
