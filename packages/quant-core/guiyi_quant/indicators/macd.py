from __future__ import annotations

import math
from collections.abc import Sequence

from .models import HistogramScale, IndicatorPoint, IndicatorSeries, MacdSeries, SeedPolicy, parameters_hash


MACD_VERSION = "v1-draft"


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

    _validate_macd_params(closes, fast, slow, signal, ema_seed_policy, histogram_scale, bar_ends, round_digits)

    params = {
        "fast": fast,
        "slow": slow,
        "signal": signal,
        "ema_seed_policy": ema_seed_policy,
        "histogram_scale": histogram_scale,
        "round_digits": round_digits,
    }
    params_hash = parameters_hash(params)
    fast_ema = _ema_values(closes, fast, ema_seed_policy)
    slow_ema = _ema_values(closes, slow, ema_seed_policy)
    dif_raw: list[float | None] = []
    dif_indexes: list[int] = []
    valid_closes = [_finite_float(value) for value in closes]

    for index, (fast_value, slow_value, close_value) in enumerate(zip(fast_ema, slow_ema, valid_closes, strict=True)):
        if close_value is None or fast_value is None or slow_value is None:
            dif_raw.append(None)
            continue
        value = fast_value - slow_value
        dif_raw.append(value)
        dif_indexes.append(index)

    if ema_seed_policy == "sma_window":
        compact_dif = [value for value in dif_raw if value is not None]
        dea_compact = _ema_values(compact_dif, signal, ema_seed_policy)
        dea_raw: list[float | None] = [None] * len(closes)
        for local_index, dea_value in enumerate(dea_compact):
            if local_index >= len(dif_indexes):
                break
            if dea_value is not None:
                dea_raw[dif_indexes[local_index]] = dea_value
    else:
        dea_raw = _ema_values(dif_raw, signal, ema_seed_policy)

    dif_points: list[IndicatorPoint] = []
    dea_points: list[IndicatorPoint] = []
    histogram_points: list[IndicatorPoint] = []

    for index, close_value in enumerate(valid_closes):
        bar_end = _bar_end(bar_ends, index)
        dif_value = dif_raw[index]
        dea_value = dea_raw[index]

        if close_value is None:
            dif_points.append(_invalid_point(bar_end, "input_invalid"))
            dea_points.append(_invalid_point(bar_end, "input_invalid"))
            histogram_points.append(_invalid_point(bar_end, "input_invalid"))
            continue

        if dif_value is None:
            dif_points.append(IndicatorPoint(bar_end=bar_end, value=None, ready=False, valid=True, reason="warming_up"))
            dea_points.append(IndicatorPoint(bar_end=bar_end, value=None, ready=False, valid=True, reason="warming_up"))
            histogram_points.append(
                IndicatorPoint(bar_end=bar_end, value=None, ready=False, valid=True, reason="warming_up")
            )
            continue

        dif_points.append(
            IndicatorPoint(bar_end=bar_end, value=round(dif_value, round_digits), ready=True, valid=True)
        )

        if dea_value is None:
            dea_points.append(IndicatorPoint(bar_end=bar_end, value=None, ready=False, valid=True, reason="warming_up"))
            histogram_points.append(
                IndicatorPoint(bar_end=bar_end, value=None, ready=False, valid=True, reason="warming_up")
            )
            continue

        histogram = (dif_value - dea_value) * histogram_scale
        dea_points.append(IndicatorPoint(bar_end=bar_end, value=round(dea_value, round_digits), ready=True, valid=True))
        histogram_points.append(
            IndicatorPoint(bar_end=bar_end, value=round(histogram, round_digits), ready=True, valid=True)
        )

    basis = {
        "input_field": "close",
        "closed_bar_only": True,
        "alignment": "one_point_per_input_bar",
        "ema_seed_policy": ema_seed_policy,
        "histogram_formula": f"(DIF - DEA) * {histogram_scale}",
        "warmup_bars": _macd_warmup_bars(slow, signal, ema_seed_policy),
    }
    dif_series = _indicator_series("macd_dif", params, params_hash, dif_points, basis)
    dea_series = _indicator_series("macd_dea", params, params_hash, dea_points, basis)
    histogram_series = _indicator_series("macd_histogram", params, params_hash, histogram_points, basis)

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
    if fast <= 0 or slow <= 0 or signal <= 0:
        raise ValueError("MACD fast, slow, and signal periods must be positive")
    if fast >= slow:
        raise ValueError("MACD fast period must be less than slow period")
    if ema_seed_policy not in ("sma_window", "first_value"):
        raise ValueError("ema_seed_policy must be 'sma_window' or 'first_value'")
    if histogram_scale not in (1, 2):
        raise ValueError("histogram_scale must be 1 or 2")
    if bar_ends is not None and len(bar_ends) != len(closes):
        raise ValueError("bar_ends length must match closes length")
    if round_digits < 0:
        raise ValueError("round_digits must be non-negative")


def _ema_values(
    values: Sequence[float | int | None],
    period: int,
    seed_policy: SeedPolicy,
) -> list[float | None]:
    if seed_policy == "first_value":
        return _ema_values_first_value(values, period)
    return _ema_values_sma_window(values, period)


def _ema_values_first_value(values: Sequence[float | int | None], period: int) -> list[float | None]:
    alpha = 2 / (period + 1)
    result: list[float | None] = []
    previous: float | None = None
    for raw_value in values:
        value = _finite_float(raw_value)
        if value is None:
            previous = None
            result.append(None)
            continue
        previous = value if previous is None else (value - previous) * alpha + previous
        result.append(previous)
    return result


def _ema_values_sma_window(values: Sequence[float | int | None], period: int) -> list[float | None]:
    alpha = 2 / (period + 1)
    result: list[float | None] = [None] * len(values)
    previous: float | None = None
    for index, raw_value in enumerate(values):
        value = _finite_float(raw_value)
        if value is None:
            previous = None
            continue
        if index < period - 1:
            continue
        if previous is None:
            seed_window = [_finite_float(item) for item in values[index - period + 1 : index + 1]]
            if any(item is None for item in seed_window):
                continue
            previous = sum(item for item in seed_window if item is not None) / period
        else:
            previous = (value - previous) * alpha + previous
        result[index] = previous
    return result


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
    return IndicatorPoint(bar_end=bar_end, value=None, ready=True, valid=False, reason=reason)


def _macd_warmup_bars(slow: int, signal: int, ema_seed_policy: SeedPolicy) -> int:
    if ema_seed_policy == "first_value":
        return 0
    return slow + signal - 2
