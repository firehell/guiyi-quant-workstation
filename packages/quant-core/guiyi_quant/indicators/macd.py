from __future__ import annotations

import math
from collections.abc import Sequence

from .models import (
    MacdState,
    HistogramScale,
    IndicatorPoint,
    IndicatorSeries,
    MacdSeries,
    SeedPolicy,
    parameters_hash,
)
from .ema import initial_ema_state, step_ema


MACD_VERSION = "v1-draft"


def initial_macd_state(
    fast: int,
    slow: int,
    signal: int,
    *,
    ema_seed_policy: SeedPolicy,
    histogram_scale: HistogramScale,
    round_digits: int = 6,
) -> MacdState:
    _validate_macd_periods(
        fast,
        slow,
        signal,
        ema_seed_policy,
        histogram_scale,
        round_digits,
    )
    return MacdState(
        fast=initial_ema_state(
            fast,
            seed_policy=ema_seed_policy,
            round_digits=round_digits,
        ),
        slow=initial_ema_state(
            slow,
            seed_policy=ema_seed_policy,
            round_digits=round_digits,
        ),
        signal=initial_ema_state(
            signal,
            seed_policy=ema_seed_policy,
            round_digits=round_digits,
        ),
        histogram_scale=histogram_scale,
        round_digits=round_digits,
    )


def step_macd(
    state: MacdState,
    close: float | int | None,
    *,
    bar_end: str | None,
) -> tuple[MacdState, tuple[IndicatorPoint, IndicatorPoint, IndicatorPoint]]:
    """Advance MACD using ready DIF observations as the compact DEA input."""

    close_value = _finite_float(close)
    fast, _ = step_ema(state.fast, close, bar_end=bar_end)
    slow, _ = step_ema(state.slow, close, bar_end=bar_end)
    signal = state.signal

    if close_value is None:
        if state.fast.seed_policy == "first_value":
            signal, _ = step_ema(signal, None, bar_end=bar_end)
        next_state = MacdState(
            fast=fast,
            slow=slow,
            signal=signal,
            histogram_scale=state.histogram_scale,
            round_digits=state.round_digits,
        )
        invalid = _invalid_point(bar_end, "input_invalid")
        return next_state, (invalid, invalid, invalid)

    if fast.previous is None or slow.previous is None:
        next_state = MacdState(
            fast=fast,
            slow=slow,
            signal=signal,
            histogram_scale=state.histogram_scale,
            round_digits=state.round_digits,
        )
        warming = _warming_point(bar_end)
        return next_state, (warming, warming, warming)

    dif_value = fast.previous - slow.previous
    signal, signal_point = step_ema(signal, dif_value, bar_end=bar_end)
    next_state = MacdState(
        fast=fast,
        slow=slow,
        signal=signal,
        histogram_scale=state.histogram_scale,
        round_digits=state.round_digits,
    )
    dif_point = IndicatorPoint(
        bar_end=bar_end,
        value=round(dif_value, state.round_digits),
        ready=True,
        valid=True,
    )
    if not signal_point.ready or not signal_point.valid or signal.previous is None:
        warming = _warming_point(bar_end)
        return next_state, (dif_point, warming, warming)

    dea_value = signal.previous
    histogram = (dif_value - dea_value) * state.histogram_scale
    return next_state, (
        dif_point,
        IndicatorPoint(
            bar_end=bar_end,
            value=round(dea_value, state.round_digits),
            ready=True,
            valid=True,
        ),
        IndicatorPoint(
            bar_end=bar_end,
            value=round(histogram, state.round_digits),
            ready=True,
            valid=True,
        ),
    )


def macd_series(
    closes: Sequence[float | int | None],
    fast: int,
    slow: int,
    signal: int,
    *,
    ema_seed_policy: SeedPolicy,
    histogram_scale: HistogramScale,
    bar_ends: Sequence[str | None] | None = None,
    round_digits: int = 6,
) -> MacdSeries:
    """Calculate MACD with explicit compatibility policies.

    `sma_window` with `histogram_scale=2` reproduces the current Web display
    style. `first_value` with `histogram_scale=1` reproduces current Python
    strategy-style MACD math without replacing any strategy call sites.
    """

    _validate_macd_params(
        closes,
        fast,
        slow,
        signal,
        ema_seed_policy,
        histogram_scale,
        bar_ends,
        round_digits,
    )

    params: dict[str, int | str] = {
        "fast": fast,
        "slow": slow,
        "signal": signal,
        "ema_seed_policy": ema_seed_policy,
        "histogram_scale": histogram_scale,
        "round_digits": round_digits,
    }
    params_hash = parameters_hash(params)
    state = initial_macd_state(
        fast,
        slow,
        signal,
        ema_seed_policy=ema_seed_policy,
        histogram_scale=histogram_scale,
        round_digits=round_digits,
    )
    dif_points: list[IndicatorPoint] = []
    dea_points: list[IndicatorPoint] = []
    histogram_points: list[IndicatorPoint] = []

    for index, close in enumerate(closes):
        state, points = step_macd(
            state,
            close,
            bar_end=_bar_end(bar_ends, index),
        )
        dif_point, dea_point, histogram_point = points
        dif_points.append(dif_point)
        dea_points.append(dea_point)
        histogram_points.append(histogram_point)

    basis: dict[str, int | str | bool] = {
        "input_field": "close",
        "closed_bar_only": True,
        "alignment": "one_point_per_input_bar",
        "ema_seed_policy": ema_seed_policy,
        "histogram_formula": f"(DIF - DEA) * {histogram_scale}",
        "warmup_bars": _macd_warmup_bars(slow, signal, ema_seed_policy),
    }
    dif_series = _indicator_series("macd_dif", params, params_hash, dif_points, basis)
    dea_series = _indicator_series("macd_dea", params, params_hash, dea_points, basis)
    histogram_series = _indicator_series(
        "macd_histogram", params, params_hash, histogram_points, basis
    )

    return MacdSeries(
        indicator_code="macd",
        indicator_version=MACD_VERSION,
        parameters=params,
        parameters_hash=params_hash,
        dif=dif_series,
        dea=dea_series,
        histogram=histogram_series,
        repainting_risk="none",
        calculation_basis=basis,
    )


def _validate_macd_params(
    closes: Sequence[float | int | None],
    fast: int,
    slow: int,
    signal: int,
    ema_seed_policy: SeedPolicy,
    histogram_scale: HistogramScale,
    bar_ends: Sequence[str | None] | None,
    round_digits: int,
) -> None:
    _validate_macd_periods(
        fast,
        slow,
        signal,
        ema_seed_policy,
        histogram_scale,
        round_digits,
    )
    if bar_ends is not None and len(bar_ends) != len(closes):
        raise ValueError("bar_ends length must match closes length")


def _validate_macd_periods(
    fast: int,
    slow: int,
    signal: int,
    ema_seed_policy: SeedPolicy,
    histogram_scale: HistogramScale,
    round_digits: int,
) -> None:
    if fast <= 0 or slow <= 0 or signal <= 0:
        raise ValueError("MACD fast, slow, and signal periods must be positive")
    if fast >= slow:
        raise ValueError("MACD fast period must be less than slow period")
    if ema_seed_policy not in ("sma_window", "first_value"):
        raise ValueError("ema_seed_policy must be 'sma_window' or 'first_value'")
    if histogram_scale not in (1, 2):
        raise ValueError("histogram_scale must be 1 or 2")
    if round_digits < 0:
        raise ValueError("round_digits must be non-negative")


def _indicator_series(
    code: str,
    params: dict[str, int | str],
    params_hash: str,
    points: list[IndicatorPoint],
    basis: dict[str, int | str | bool],
) -> IndicatorSeries:
    return IndicatorSeries(
        indicator_code=code,
        indicator_version=MACD_VERSION,
        parameters=params,
        parameters_hash=params_hash,
        points=points,
        repainting_risk="none",
        calculation_basis=basis,
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


def _invalid_point(bar_end: str | None, reason: str) -> IndicatorPoint:
    return IndicatorPoint(
        bar_end=bar_end, value=None, ready=True, valid=False, reason=reason
    )


def _warming_point(bar_end: str | None) -> IndicatorPoint:
    return IndicatorPoint(
        bar_end=bar_end,
        value=None,
        ready=False,
        valid=True,
        reason="warming_up",
    )


def _macd_warmup_bars(slow: int, signal: int, ema_seed_policy: SeedPolicy) -> int:
    if ema_seed_policy == "first_value":
        return 0
    return slow + signal - 2
