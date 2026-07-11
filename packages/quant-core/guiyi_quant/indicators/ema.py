from __future__ import annotations

import math
from collections.abc import Sequence

from .models import IndicatorPoint, IndicatorSeries, SeedPolicy, parameters_hash


EMA_VERSION = "v1"


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

    if period <= 0:
        raise ValueError("EMA period must be positive")
    if bar_ends is not None and len(bar_ends) != len(values):
        raise ValueError("bar_ends length must match values length")
    if round_digits < 0:
        raise ValueError("round_digits must be non-negative")

    code = indicator_code or f"ema{period}"
    params = {"period": period, "seed_policy": seed_policy, "round_digits": round_digits}
    alpha = 2 / (period + 1)
    points: list[IndicatorPoint] = []
    previous: float | None = None

    for index, raw_value in enumerate(values):
        bar_end = _bar_end(bar_ends, index)
        value = _finite_float(raw_value)
        warmed = _is_warmed(index, period, seed_policy)

        if value is None:
            previous = None
            points.append(IndicatorPoint(bar_end=bar_end, value=None, ready=warmed, valid=False, reason="input_invalid"))
            continue

        if seed_policy == "first_value":
            previous = value if previous is None else (value - previous) * alpha + previous
            points.append(
                IndicatorPoint(bar_end=bar_end, value=round(previous, round_digits), ready=True, valid=True, reason=None)
            )
            continue

        if index < period - 1:
            points.append(IndicatorPoint(bar_end=bar_end, value=None, ready=False, valid=True, reason="warming_up"))
            continue

        if previous is None:
            seed_window = [_finite_float(item) for item in values[index - period + 1 : index + 1]]
            if any(item is None for item in seed_window):
                points.append(
                    IndicatorPoint(bar_end=bar_end, value=None, ready=True, valid=False, reason="seed_window_invalid")
                )
                continue
            previous = sum(item for item in seed_window if item is not None) / period
        else:
            previous = (value - previous) * alpha + previous

        points.append(IndicatorPoint(bar_end=bar_end, value=round(previous, round_digits), ready=True, valid=True))

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


def _is_warmed(index: int, period: int, seed_policy: SeedPolicy) -> bool:
    if seed_policy == "first_value":
        return True
    return index >= period - 1


def _warmup_bars(period: int, seed_policy: SeedPolicy) -> int:
    if seed_policy == "first_value":
        return 0
    return period - 1
