from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np


@dataclass(frozen=True)
class HtdyOriginalResult:
    datetimes: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    fields: dict[str, np.ndarray]
    metadata: dict[str, Any]


def normalize_period(period: int) -> int:
    value = int(period)
    if value <= 0:
        raise ValueError("period must be positive")
    return value + 1 if value % 2 == 0 else value


def xma(values: Sequence[float], period: int) -> np.ndarray:
    """Repository-frozen Tongdaxin-style centered XMA.

    The available sequence tail is intentionally used as-is. Values near that
    tail therefore change when later bars arrive.
    """

    arr = _float_array(values, name="values")
    normalized = normalize_period(period)
    offset = (normalized - 1) // 2
    result = np.full(len(arr), np.nan, dtype=float)
    for index in range(len(arr)):
        start = index - offset - 1
        end = index + (normalized - offset) - 1
        window = _slice_like_numpy(arr, start, end)
        finite = window[np.isfinite(window)]
        if len(finite):
            result[index] = float(np.mean(finite))
    return result


def ema(values: Sequence[float], period: int) -> np.ndarray:
    arr = _float_array(values, name="values")
    if period <= 0:
        raise ValueError("period must be positive")
    result = np.full(len(arr), np.nan, dtype=float)
    alpha = 2.0 / (period + 1)
    previous: float | None = None
    for index, value in enumerate(arr):
        if not np.isfinite(value):
            continue
        previous = float(value) if previous is None else alpha * float(value) + (1 - alpha) * previous
        result[index] = previous
    return result


def new_third_consecutive(flags: Sequence[bool]) -> np.ndarray:
    values = np.asarray(flags, dtype=bool)
    result = np.zeros(len(values), dtype=bool)
    for index in range(2, len(values)):
        current_three = values[index] and values[index - 1] and values[index - 2]
        result[index] = current_three and not bool(values[index - 3] if index >= 3 else False)
    return result


def compute_htdy_original(
    datetimes: Sequence[Any],
    open_: Sequence[float],
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    volume: Sequence[float],
    *,
    channel_period: int = 25,
) -> HtdyOriginalResult:
    dt = np.asarray(datetimes, dtype=object)
    open_values = _float_array(open_, name="open")
    high_values = _float_array(high, name="high")
    low_values = _float_array(low, name="low")
    close_values = _float_array(close, name="close")
    volume_values = _float_array(volume, name="volume")
    _require_same_length(
        datetimes=dt,
        open=open_values,
        high=high_values,
        low=low_values,
        close=close_values,
        volume=volume_values,
    )

    xma_high = xma(xma(high_values, channel_period), channel_period)
    xma_low = xma(xma(low_values, channel_period), channel_period)
    band_width = xma_high - xma_low
    zk1 = xma_high + band_width
    zd1 = xma_low - band_width
    zd2 = ema(zd1, channel_period)

    body_high = np.maximum(open_values, close_values)
    body_low = np.minimum(open_values, close_values)
    over_low = np.maximum(body_low, zk1)
    yellow_candle = (
        ((zd1 > low_values) & (zd1 < high_values))
        | ((zd1 > body_low) & (zd1 < body_high))
        | (zd1 > high_values)
    )
    white_candle = (body_high > zk1) & (body_high > over_low)
    buy_observation = new_third_consecutive(yellow_candle)
    sell_observation = new_third_consecutive(white_candle)

    return HtdyOriginalResult(
        datetimes=dt,
        open=open_values,
        high=high_values,
        low=low_values,
        close=close_values,
        volume=volume_values,
        fields={
            "zk1": zk1,
            "zd1": zd1,
            "zd2": zd2,
            "yellow_candle": yellow_candle,
            "white_candle": white_candle,
            "buy_observation": buy_observation,
            "sell_observation": sell_observation,
        },
        metadata={
            "indicator_code": "huo_tian_da_you",
            "indicator_version": "original-v0",
            "strategy_code": "huotian_dayou_original",
            "strategy_version": "v0-observation-only",
            "alert_policy": "htdy_original_repainting_realtime_v1",
            "status": "observation_only",
            "future_looking": True,
            "repainting_risk": "known",
            "confirmed_bar_input_required": True,
            "alert_capable": True,
            "formal_signal_capable": False,
            "backtest_capable": False,
            "trading_capable": False,
        },
    )


def synthetic_bars(length: int = 96) -> dict[str, list[Any]]:
    if length <= 0:
        raise ValueError("length must be positive")
    index = np.arange(length, dtype=float)
    base = 100.0 + index * 0.18 + np.sin(index / 5.0) * 2.0
    open_values = base + np.sin(index / 3.0) * 0.25
    close_values = base + np.cos(index / 4.0) * 0.35
    high_values = np.maximum(open_values, close_values) + 1.2 + (index % 5) * 0.08
    low_values = np.minimum(open_values, close_values) - 1.1 - (index % 7) * 0.06
    volume_values = 1000.0 + (index % 13) * 30.0 + index * 4.0
    return {
        "datetime": [f"2026-01-{int(i // 24) + 1:02d} {int(i % 24):02d}:00:00" for i in range(length)],
        "open": open_values.tolist(),
        "high": high_values.tolist(),
        "low": low_values.tolist(),
        "close": close_values.tolist(),
        "volume": volume_values.tolist(),
    }


def _slice_like_numpy(values: np.ndarray, start: int, end: int) -> np.ndarray:
    length = len(values)
    normalized_start = max(length + start, 0) if start < 0 else min(start, length)
    normalized_end = max(length + end, 0) if end < 0 else min(end, length)
    if normalized_end <= normalized_start:
        return values[:0]
    return values[normalized_start:normalized_end]


def _float_array(values: Sequence[float], *, name: str) -> np.ndarray:
    try:
        return np.asarray(values, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc


def _require_same_length(**arrays: Sequence[Any]) -> None:
    lengths = {name: len(value) for name, value in arrays.items()}
    if len(set(lengths.values())) != 1:
        raise ValueError(f"input lengths must match: {lengths}")


__all__ = [
    "HtdyOriginalResult",
    "compute_htdy_original",
    "ema",
    "new_third_consecutive",
    "normalize_period",
    "synthetic_bars",
    "xma",
]
