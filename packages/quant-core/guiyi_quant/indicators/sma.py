from __future__ import annotations

import math

from .models import IndicatorPoint, SmaState


def initial_sma_state(period: int, *, round_digits: int = 6) -> SmaState:
    if period <= 0:
        raise ValueError("SMA period must be positive")
    if round_digits < 0:
        raise ValueError("round_digits must be non-negative")
    return SmaState(period=period, values=(), round_digits=round_digits)


def step_sma(
    state: SmaState,
    value: float | int | None,
    *,
    bar_end: str | None,
) -> tuple[SmaState, IndicatorPoint]:
    """Advance a bounded simple moving average."""

    number = _finite_float(value)
    if number is None:
        return (
            SmaState(
                period=state.period,
                values=(),
                round_digits=state.round_digits,
            ),
            IndicatorPoint(
                bar_end=bar_end,
                value=None,
                ready=False,
                valid=False,
                reason="input_invalid",
            ),
        )

    values = (*state.values, number)[-state.period :]
    next_state = SmaState(
        period=state.period,
        values=values,
        round_digits=state.round_digits,
    )
    if len(values) < state.period:
        return (
            next_state,
            IndicatorPoint(
                bar_end=bar_end,
                value=None,
                ready=False,
                valid=True,
                reason="warming_up",
            ),
        )
    return (
        next_state,
        IndicatorPoint(
            bar_end=bar_end,
            value=round(sum(values) / state.period, state.round_digits),
            ready=True,
            valid=True,
        ),
    )


def _finite_float(value: float | int | None) -> float | None:
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None
