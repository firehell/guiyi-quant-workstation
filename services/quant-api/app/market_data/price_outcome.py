"""Shared exact Decimal arithmetic for price-only directional outcomes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from statistics import median

from .domain import CanonicalBar


class PriceDirection(StrEnum):
    LONG = "long"
    SHORT = "short"


class PriceOutcomeError(ValueError):
    code = "PRICE_OUTCOME_ENTRY_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class PriceDirectionalOutcome:
    horizon: int
    directional_return_bps: Decimal
    mfe_bps: Decimal
    mae_bps: Decimal


@dataclass(frozen=True, slots=True)
class PriceHorizonEvaluation:
    sample_count: int
    median_directional_return_bps: Decimal | None
    median_mfe_bps: Decimal | None
    median_mae_bps: Decimal | None


def summarize_price_outcomes(
    outcomes: Sequence[PriceDirectionalOutcome],
) -> PriceHorizonEvaluation:
    if not outcomes:
        return PriceHorizonEvaluation(0, None, None, None)
    return PriceHorizonEvaluation(
        sample_count=len(outcomes),
        median_directional_return_bps=median(
            outcome.directional_return_bps for outcome in outcomes
        ),
        median_mfe_bps=median(outcome.mfe_bps for outcome in outcomes),
        median_mae_bps=median(outcome.mae_bps for outcome in outcomes),
    )


def build_price_outcomes_at(
    bars: Sequence[CanonicalBar],
    *,
    index: int,
    direction: PriceDirection,
    horizons: Sequence[int] = (3, 5, 8),
    same_trading_day_only: bool,
) -> Mapping[int, PriceDirectionalOutcome | None]:
    """Evaluate future bars supplied by a caller for exactly one rank-1 segment."""

    if any(not isinstance(bar, CanonicalBar) for bar in bars):
        raise TypeError("bars must contain CanonicalBar values")
    if type(index) is not int or not 0 <= index < len(bars):
        raise ValueError("index is outside the series")
    if type(same_trading_day_only) is not bool:
        raise TypeError("same_trading_day_only must be bool")
    requested = _validated_horizons(horizons)
    side = PriceDirection(direction)
    if bars[index].close <= 0:
        raise PriceOutcomeError()

    return {
        horizon: _outcome_for_horizon(
            bars,
            index=index,
            direction=side,
            horizon=horizon,
            same_trading_day_only=same_trading_day_only,
        )
        for horizon in requested
    }


def _outcome_for_horizon(
    bars: Sequence[CanonicalBar],
    *,
    index: int,
    direction: PriceDirection,
    horizon: int,
    same_trading_day_only: bool,
) -> PriceDirectionalOutcome | None:
    final_index = index + horizon
    if final_index >= len(bars):
        return None
    future = bars[index + 1 : final_index + 1]
    if len(future) != horizon:
        return None
    entry = bars[index]
    if same_trading_day_only and any(
        bar.trading_day != entry.trading_day for bar in future
    ):
        return None
    entry_close = entry.close
    if direction is PriceDirection.LONG:
        directional_return = (
            (future[-1].close - entry_close) / entry_close * Decimal(10000)
        )
        mfe = (max(bar.high for bar in future) - entry_close) / entry_close * Decimal(
            10000
        )
        mae = (min(bar.low for bar in future) - entry_close) / entry_close * Decimal(
            10000
        )
    else:
        directional_return = (
            (entry_close - future[-1].close) / entry_close * Decimal(10000)
        )
        mfe = (entry_close - min(bar.low for bar in future)) / entry_close * Decimal(
            10000
        )
        mae = (entry_close - max(bar.high for bar in future)) / entry_close * Decimal(
            10000
        )
    return PriceDirectionalOutcome(
        horizon=horizon,
        directional_return_bps=directional_return,
        mfe_bps=mfe,
        mae_bps=mae,
    )


def _validated_horizons(horizons: Sequence[int]) -> tuple[int, ...]:
    requested = tuple(horizons)
    if not requested or len(set(requested)) != len(requested):
        raise ValueError("horizons must be non-empty and unique")
    if any(type(horizon) is not int or horizon <= 0 for horizon in requested):
        raise ValueError("horizons must contain positive integers")
    return requested
