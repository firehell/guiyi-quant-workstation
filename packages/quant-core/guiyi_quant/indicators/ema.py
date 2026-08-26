from __future__ import annotations

import math
from collections.abc import Sequence

from .models import (
    EmaState,
    IndicatorPoint,
    IndicatorSeries,
    SeedPolicy,
    parameters_hash,
)


EMA_VERSION = "v1"


def initial_ema_state(
    period: int,
    *,
    seed_policy: SeedPolicy = "sma_window",
    round_digits: int = 6,
) -> EmaState:
    if period <= 0:
        raise ValueError("EMA period must be positive")
    if round_digits < 0:
        raise ValueError("round_digits must be non-negative")
    return EmaState(
        period=period,
        seed_policy=seed_policy,
        count=0,
        seed_values=(),
        previous=None,
        round_digits=round_digits,
    )


def step_ema(
    state: EmaState,
    value: float | int | None,
    *,
    bar_end: str | None,
) -> tuple[EmaState, IndicatorPoint]:
    """Advance one EMA observation without retaining an unbounded history."""

    number = _finite_float(value)
    count = state.count + 1
    warmed = state.seed_policy == "first_value" or count >= state.period
    if number is None:
        return (
            EmaState(
                period=state.period,
                seed_policy=state.seed_policy,
                count=count,
                seed_values=(),
                previous=None,
                round_digits=state.round_digits,
            ),
            IndicatorPoint(
                bar_end=bar_end,
                value=None,
                ready=warmed,
                valid=False,
                reason="input_invalid",
            ),
        )

    alpha = 2 / (state.period + 1)
    if state.seed_policy == "first_value":
        previous = (
            number
            if state.previous is None
            else (number - state.previous) * alpha + state.previous
        )
        return (
            EmaState(
                period=state.period,
                seed_policy=state.seed_policy,
                count=count,
                seed_values=(),
                previous=previous,
                round_digits=state.round_digits,
            ),
            IndicatorPoint(
                bar_end=bar_end,
                value=round(previous, state.round_digits),
                ready=True,
                valid=True,
            ),
        )

    seed_values = (*state.seed_values, number)[-state.period :]
    sma_previous = state.previous
    if sma_previous is None:
        next_state = EmaState(
            period=state.period,
            seed_policy=state.seed_policy,
            count=count,
            seed_values=seed_values,
            previous=None,
            round_digits=state.round_digits,
        )
        if len(seed_values) < state.period:
            return (
                next_state,
                IndicatorPoint(
                    bar_end=bar_end,
                    value=None,
                    ready=warmed,
                    valid=not warmed,
                    reason="seed_window_invalid" if warmed else "warming_up",
                ),
            )
        sma_previous = sum(seed_values) / state.period
    else:
        sma_previous = (number - sma_previous) * alpha + sma_previous

    return (
        EmaState(
            period=state.period,
            seed_policy=state.seed_policy,
            count=count,
            seed_values=(),
            previous=sma_previous,
            round_digits=state.round_digits,
        ),
        IndicatorPoint(
            bar_end=bar_end,
            value=round(sma_previous, state.round_digits),
            ready=True,
            valid=True,
        ),
    )


def ema_series(
    values: Sequence[float | int | None],
    period: int,
    *,
    bar_ends: Sequence[str | None] | None = None,
    seed_policy: SeedPolicy = "sma_window",
    indicator_code: str | None = None,
    round_digits: int = 6,
) -> IndicatorSeries:
    """Calculate an EMA series aligned one-to-one with the input values.

    The default `sma_window` seed intentionally matches the current Web EMA
    implementation: the first ready value is the simple average of the first
    `period` closes, then the recursive EMA uses alpha = 2 / (period + 1).
    """

    if bar_ends is not None and len(bar_ends) != len(values):
        raise ValueError("bar_ends length must match values length")

    code = indicator_code or f"ema{period}"
    params = {
        "period": period,
        "seed_policy": seed_policy,
        "round_digits": round_digits,
    }
    alpha = 2 / (period + 1)
    state = initial_ema_state(
        period,
        seed_policy=seed_policy,
        round_digits=round_digits,
    )
    points: list[IndicatorPoint] = []

    for index, raw_value in enumerate(values):
        state, point = step_ema(
            state,
            raw_value,
            bar_end=_bar_end(bar_ends, index),
        )
        points.append(point)

    return IndicatorSeries(
        indicator_code=code,
        indicator_version=EMA_VERSION,
        parameters=params,
        parameters_hash=parameters_hash(params),
        points=points,
        repainting_risk="none",
        calculation_basis={
            "input_field": "close",
            "alpha": alpha,
            "closed_bar_only": True,
            "alignment": "one_point_per_input_bar",
            "warmup_bars": _warmup_bars(period, seed_policy),
        },
    )


def _finite_float(value: float | int | None) -> float | None:
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _bar_end(bar_ends: Sequence[str | None] | None, index: int) -> str | None:
    if bar_ends is None:
        return None
    return bar_ends[index]


def _warmup_bars(period: int, seed_policy: SeedPolicy) -> int:
    if seed_policy == "first_value":
        return 0
    return period - 1
