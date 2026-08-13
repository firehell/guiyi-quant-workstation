from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from statistics import median, quantiles

from .domain import BarFrequency, CanonicalBar
from .subing_research import (
    PriceSide,
    SubingFactorResult,
    SubingFactorSnapshot,
    SubingFactorStatus,
)


class DirectionalSide(StrEnum):
    LONG = "long"
    SHORT = "short"


@dataclass(frozen=True, slots=True)
class SubingOutcome:
    horizon: int
    directional_return_bps: Decimal
    mfe_bps: Decimal
    mae_bps: Decimal
    ema21_failure: bool


@dataclass(frozen=True, slots=True)
class SubingResearchSample:
    factor: SubingFactorSnapshot
    direction: DirectionalSide
    studied_value: Decimal
    outcomes: Mapping[int, SubingOutcome | None]


@dataclass(frozen=True, slots=True)
class HorizonEvaluation:
    sample_count: int
    median_directional_return_bps: Decimal | None
    median_mfe_bps: Decimal | None
    median_mae_bps: Decimal | None
    ema21_failure_rate: Decimal | None


@dataclass(frozen=True, slots=True)
class ThresholdEvaluation:
    threshold: Decimal
    sample_count: int
    horizons: Mapping[int, HorizonEvaluation]


@dataclass(frozen=True, slots=True)
class CalibrationReport:
    sample_count: int
    product_sample_counts: Mapping[str, int]
    candidate_thresholds: tuple[Decimal, ...] | None = None
    candidate_evaluations: tuple[ThresholdEvaluation, ...] = ()
    threshold_evaluation: ThresholdEvaluation | None = None


DirectionSelector = Callable[[int, SubingFactorSnapshot], DirectionalSide | None]
ValueSelector = Callable[[SubingFactorSnapshot], Decimal]


def build_outcomes_at(
    factor_results: Sequence[SubingFactorResult],
    bars: Sequence[CanonicalBar],
    *,
    index: int,
    direction: DirectionalSide,
    horizons: Sequence[int] = (3, 5, 8),
) -> dict[int, SubingOutcome | None]:
    if len(factor_results) != len(bars):
        raise ValueError("factor_results and bars must be aligned")
    if index < 0 or index >= len(bars):
        raise ValueError("index is outside the aligned series")
    requested = _validated_horizons(horizons)
    entry = _ready_snapshot(factor_results[index])
    if (
        entry is None
        or entry.bar_end != bars[index].bar_end
        or entry.trading_day != bars[index].trading_day
        or entry.close != bars[index].close
    ):
        raise ValueError("entry factor must be ready and aligned with its bar")
    if entry.timeframe not in {
        BarFrequency.M5,
        BarFrequency.M15,
        BarFrequency.D1,
    }:
        raise ValueError("entry factor timeframe must be 5m, 15m, or 1d")
    side = DirectionalSide(direction)

    return {
        horizon: _outcome_for_horizon(
            factor_results,
            bars,
            index=index,
            horizon=horizon,
            entry=entry,
            direction=side,
        )
        for horizon in requested
    }


def build_research_samples(
    factor_results: Sequence[SubingFactorResult],
    bars: Sequence[CanonicalBar],
    *,
    horizons: Sequence[int] = (3, 5, 8),
    direction_selector: DirectionSelector,
    value_selector: ValueSelector | None = None,
) -> tuple[SubingResearchSample, ...]:
    if len(factor_results) != len(bars):
        raise ValueError("factor_results and bars must be aligned")
    studied_value = value_selector or (
        lambda factor: abs(factor.slope_5_bps_per_bar)
    )
    samples: list[SubingResearchSample] = []
    for index, result in enumerate(factor_results):
        factor = _ready_snapshot(result)
        if factor is None:
            continue
        direction = direction_selector(index, factor)
        if direction is None:
            continue
        value = studied_value(factor)
        value = _validated_decimal(value, field="studied_value")
        samples.append(
            SubingResearchSample(
                factor=factor,
                direction=DirectionalSide(direction),
                studied_value=value,
                outcomes=build_outcomes_at(
                    factor_results,
                    bars,
                    index=index,
                    direction=direction,
                    horizons=horizons,
                ),
            )
        )
    return tuple(samples)


def slope_direction(
    _index: int, factor: SubingFactorSnapshot
) -> DirectionalSide | None:
    if (
        factor.price_side is PriceSide.ABOVE
        and factor.slope_5_bps_per_bar > 0
        and factor.slope_10_bps_per_bar > 0
    ):
        return DirectionalSide.LONG
    if (
        factor.price_side is PriceSide.BELOW
        and factor.slope_5_bps_per_bar < 0
        and factor.slope_10_bps_per_bar < 0
    ):
        return DirectionalSide.SHORT
    return None


def candidate_quantiles(
    product_values: Mapping[str, Sequence[Decimal]],
    *,
    percentiles: tuple[int, int, int] = (10, 20, 30),
) -> dict[str, tuple[Decimal, Decimal, Decimal] | None]:
    requested = _validated_percentiles(percentiles)
    if not isinstance(product_values, Mapping):
        raise TypeError("product_values must be a mapping")
    if any(not isinstance(product, str) or not product.strip() for product in product_values):
        raise ValueError("product names must be non-empty strings")
    return {
        product: _candidate_quantiles_for_product(values, percentiles=requested)
        for product, values in product_values.items()
    }


def _candidate_quantiles_for_product(
    values: Sequence[Decimal],
    *,
    percentiles: tuple[int, int, int],
) -> tuple[Decimal, Decimal, Decimal] | None:
    if not values:
        return None
    normalized = tuple(
        _validated_decimal(value, field="candidate value") for value in values
    )
    if len(normalized) == 1:
        return (normalized[0], normalized[0], normalized[0])
    cuts = quantiles(normalized, n=100, method="inclusive")
    return tuple(cuts[percentile - 1] for percentile in percentiles)  # type: ignore[return-value]


def evaluate_threshold(
    samples: Sequence[SubingResearchSample],
    threshold: Decimal,
    *,
    horizons: Sequence[int] = (3, 5, 8),
    include_at_or_below: bool = False,
) -> ThresholdEvaluation:
    value = _validated_decimal(threshold, field="threshold")
    requested = _validated_horizons(horizons)
    selected = tuple(
        sample
        for sample in samples
        if (
            sample.studied_value <= value
            if include_at_or_below
            else sample.studied_value > value
        )
    )
    return ThresholdEvaluation(
        threshold=value,
        sample_count=len(selected),
        horizons={
            horizon: _evaluate_horizon(selected, horizon) for horizon in requested
        },
    )


def _outcome_for_horizon(
    factor_results: Sequence[SubingFactorResult],
    bars: Sequence[CanonicalBar],
    *,
    index: int,
    horizon: int,
    entry: SubingFactorSnapshot,
    direction: DirectionalSide,
) -> SubingOutcome | None:
    final_index = index + horizon
    if final_index >= len(bars):
        return None
    future_bars = bars[index + 1 : final_index + 1]
    if len(future_bars) != horizon:
        return None
    ready_factor_bars = tuple(
        (factor, bar)
        for result, bar in zip(
            factor_results[index + 1 : final_index + 1],
            future_bars,
            strict=True,
        )
        if (factor := _ready_snapshot(result)) is not None
    )
    if any(
        factor.bar_end != bar.bar_end
        or factor.trading_day != bar.trading_day
        or factor.close != bar.close
        or factor.timeframe is not entry.timeframe
        or factor.contract != entry.contract
        or factor.segment_start_trading_day != entry.segment_start_trading_day
        for factor, bar in ready_factor_bars
    ):
        return None
    if entry.timeframe in {BarFrequency.M5, BarFrequency.M15} and any(
        bar.trading_day != entry.trading_day for bar in future_bars
    ):
        return None

    entry_close = entry.close
    if entry_close == 0:
        return None
    sign = Decimal(1) if direction is DirectionalSide.LONG else Decimal(-1)
    final_close = future_bars[-1].close
    directional_return = sign * (final_close - entry_close) / entry_close * Decimal(10000)
    ready_factors = tuple(factor for factor, _bar in ready_factor_bars)
    if direction is DirectionalSide.LONG:
        mfe = (max(bar.high for bar in future_bars) - entry_close) / entry_close * Decimal(10000)
        mae = (min(bar.low for bar in future_bars) - entry_close) / entry_close * Decimal(10000)
        ema21_failure = any(
            factor.close < factor.ema21 for factor in ready_factors
        )
    else:
        mfe = (entry_close - min(bar.low for bar in future_bars)) / entry_close * Decimal(10000)
        mae = (entry_close - max(bar.high for bar in future_bars)) / entry_close * Decimal(10000)
        ema21_failure = any(
            factor.close > factor.ema21 for factor in ready_factors
        )
    return SubingOutcome(
        horizon=horizon,
        directional_return_bps=directional_return,
        mfe_bps=mfe,
        mae_bps=mae,
        ema21_failure=ema21_failure,
    )


def _evaluate_horizon(
    samples: Sequence[SubingResearchSample], horizon: int
) -> HorizonEvaluation:
    outcomes = tuple(
        outcome
        for sample in samples
        if (outcome := sample.outcomes.get(horizon)) is not None
    )
    if not outcomes:
        return HorizonEvaluation(0, None, None, None, None)
    count = len(outcomes)
    return HorizonEvaluation(
        sample_count=count,
        median_directional_return_bps=median(
            outcome.directional_return_bps for outcome in outcomes
        ),
        median_mfe_bps=median(outcome.mfe_bps for outcome in outcomes),
        median_mae_bps=median(outcome.mae_bps for outcome in outcomes),
        ema21_failure_rate=(
            Decimal(sum(outcome.ema21_failure for outcome in outcomes))
            / Decimal(count)
        ),
    )


def _ready_snapshot(result: SubingFactorResult) -> SubingFactorSnapshot | None:
    if result.status is not SubingFactorStatus.READY:
        return None
    return result.snapshot


def _validated_horizons(horizons: Sequence[int]) -> tuple[int, ...]:
    requested = tuple(horizons)
    if not requested or len(set(requested)) != len(requested):
        raise ValueError("horizons must be non-empty and unique")
    if any(type(horizon) is not int or horizon <= 0 for horizon in requested):
        raise ValueError("horizons must contain positive integers")
    return requested


def _validated_percentiles(
    percentiles: tuple[int, int, int],
) -> tuple[int, int, int]:
    if (
        len(percentiles) != 3
        or len(set(percentiles)) != len(percentiles)
        or any(type(percentile) is not int or not 1 <= percentile <= 99 for percentile in percentiles)
    ):
        raise ValueError("percentiles must contain three unique integers from 1 to 99")
    return percentiles


def _validated_decimal(value: Decimal, *, field: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field} must be Decimal")
    if not value.is_finite() or value < 0:
        raise ValueError(f"{field} must be finite and non-negative")
    return value
