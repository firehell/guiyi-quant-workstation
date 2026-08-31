from __future__ import annotations

import math
from collections.abc import Sequence

from .models import (
    AtrSmoothingPolicy,
    AtrState,
    IndicatorPoint,
    IndicatorSeries,
    parameters_hash,
)


ATR_VERSION = "v1-draft"


def initial_atr_state(
    period: int,
    *,
    smoothing_policy: AtrSmoothingPolicy,
    round_digits: int = 6,
) -> AtrState:
    _validate_atr_period(period, smoothing_policy, round_digits)
    return AtrState(
        period=period,
        smoothing_policy=smoothing_policy,
        count=0,
        seed_values=(),
        previous_close=None,
        previous_atr=None,
        round_digits=round_digits,
    )


def step_atr(
    state: AtrState,
    *,
    high: float | int | None,
    low: float | int | None,
    close: float | int | None,
    bar_end: str | None,
) -> tuple[AtrState, IndicatorPoint]:
    """Advance one ATR observation while preserving the selected seed policy."""

    count = state.count + 1
    high_value = _finite_float(high)
    low_value = _finite_float(low)
    close_value = _finite_float(close)
    if high_value is None or low_value is None or close_value is None:
        return (
            AtrState(
                period=state.period,
                smoothing_policy=state.smoothing_policy,
                count=count,
                seed_values=(),
                previous_close=None,
                previous_atr=None,
                round_digits=state.round_digits,
            ),
            IndicatorPoint(
                bar_end=bar_end,
                value=None,
                ready=True,
                valid=False,
                reason="input_invalid",
            ),
        )

    true_range = _true_range(high_value, low_value, state.previous_close)
    seed_values = (*state.seed_values, true_range)[-state.period :]
    previous_atr = state.previous_atr

    if state.smoothing_policy == "wilder_sma_seed":
        if previous_atr is None:
            if len(seed_values) < state.period:
                return (
                    AtrState(
                        period=state.period,
                        smoothing_policy=state.smoothing_policy,
                        count=count,
                        seed_values=seed_values,
                        previous_close=close_value,
                        previous_atr=None,
                        round_digits=state.round_digits,
                    ),
                    IndicatorPoint(
                        bar_end=bar_end,
                        value=None,
                        ready=False,
                        valid=True,
                        reason="warming_up",
                    ),
                )
            previous_atr = sum(seed_values) / state.period
        else:
            previous_atr = (
                previous_atr * (state.period - 1) + true_range
            ) / state.period
    elif state.smoothing_policy == "wilder_first_tr":
        previous_atr = (
            true_range
            if previous_atr is None
            else (previous_atr * (state.period - 1) + true_range) / state.period
        )
    else:
        alpha = 2 / (state.period + 1)
        previous_atr = (
            true_range
            if previous_atr is None
            else (true_range - previous_atr) * alpha + previous_atr
        )

    return (
        AtrState(
            period=state.period,
            smoothing_policy=state.smoothing_policy,
            count=count,
            seed_values=seed_values,
            previous_close=close_value,
            previous_atr=previous_atr,
            round_digits=state.round_digits,
        ),
        IndicatorPoint(
            bar_end=bar_end,
            value=round(previous_atr, state.round_digits),
            ready=True,
            valid=True,
        ),
    )


def atr_series(
    highs: Sequence[float | int | None],
    lows: Sequence[float | int | None],
    closes: Sequence[float | int | None],
    period: int,
    *,
    smoothing_policy: AtrSmoothingPolicy,
    bar_ends: Sequence[str | None] | None = None,
    round_digits: int = 6,
) -> IndicatorSeries:
    """Calculate ATR with explicit smoothing policies.

    `wilder_sma_seed` reproduces the current Web ATR display. `wilder_first_tr`
    and `ema_first_tr` preserve the Python strategy variants found during the
    V1-B audit, without migrating any caller.
    """

    _validate_atr_params(highs, lows, closes, period, smoothing_policy, bar_ends, round_digits)

    params = {"period": period, "smoothing_policy": smoothing_policy, "round_digits": round_digits}
    points: list[IndicatorPoint] = []
    state = initial_atr_state(
        period,
        smoothing_policy=smoothing_policy,
        round_digits=round_digits,
    )

    for index, (raw_high, raw_low, raw_close) in enumerate(zip(highs, lows, closes, strict=True)):
        state, point = step_atr(
            state,
            high=raw_high,
            low=raw_low,
            close=raw_close,
            bar_end=_bar_end(bar_ends, index),
        )
        points.append(point)

    return IndicatorSeries(
        indicator_code="atr",
        indicator_version=ATR_VERSION,
        parameters=params,
        parameters_hash=parameters_hash(params),
        points=points,
        repainting_risk="none",
        calculation_basis={
            "input_fields": ("high", "low", "close"),
            "closed_bar_only": True,
            "alignment": "one_point_per_input_bar",
            "true_range": "max(high-low, abs(high-previous_close), abs(low-previous_close))",
            "smoothing_policy": smoothing_policy,
            "warmup_bars": period - 1 if smoothing_policy == "wilder_sma_seed" else 0,
        },
    )


def _validate_atr_params(
    highs: Sequence[float | int | None],
    lows: Sequence[float | int | None],
    closes: Sequence[float | int | None],
    period: int,
    smoothing_policy: AtrSmoothingPolicy,
    bar_ends: Sequence[str | None] | None,
    round_digits: int,
) -> None:
    _validate_atr_period(period, smoothing_policy, round_digits)
    if len(highs) != len(lows) or len(highs) != len(closes):
        raise ValueError("highs, lows, and closes length must match")
    if bar_ends is not None and len(bar_ends) != len(highs):
        raise ValueError("bar_ends length must match highs length")


def _validate_atr_period(
    period: int,
    smoothing_policy: AtrSmoothingPolicy,
    round_digits: int,
) -> None:
    if period <= 0:
        raise ValueError("ATR period must be positive")
    if smoothing_policy not in ("wilder_sma_seed", "wilder_first_tr", "ema_first_tr"):
        raise ValueError("smoothing_policy must be 'wilder_sma_seed', 'wilder_first_tr', or 'ema_first_tr'")
    if round_digits < 0:
        raise ValueError("round_digits must be non-negative")


def _true_range(high: float, low: float, previous_close: float | None) -> float:
    if previous_close is None:
        return high - low
    return max(high - low, abs(high - previous_close), abs(low - previous_close))


def _finite_float(value: float | int | None) -> float | None:
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _bar_end(bar_ends: Sequence[str | None] | None, index: int) -> str | None:
    if bar_ends is None:
        return None
    return bar_ends[index]
