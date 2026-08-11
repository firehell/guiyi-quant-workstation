"""Causal HTDY strict kernel (strategy_candidate, historical research only).

Former strategy package path retired; this module is the Indicator Kernel
calculation source for `huotian_dayou_strict_v1`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

NUMERIC_FIELDS = ("zk1", "zd1", "zd2", "var23")
BOOLEAN_FIELDS = (
    "yellow_candle",
    "white_candle",
    "buy_observation",
    "sell_observation",
    "callback_buy",
    "xg_observation",
)


def compute_strict_fields(
    open_: Sequence[float],
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    *,
    channel_period: int = 25,
    var23_period: int = 6,
) -> dict[str, np.ndarray]:
    _require_positive_period("channel_period", channel_period)
    _require_positive_period("var23_period", var23_period)
    o = np.asarray(open_, dtype=float)
    h = np.asarray(high, dtype=float)
    low_arr = np.asarray(low, dtype=float)
    c = np.asarray(close, dtype=float)
    _require_same_length(open=o, high=h, low=low_arr, close=c)

    ema_high = _double_trailing_ema(h, channel_period)
    ema_low = _double_trailing_ema(low_arr, channel_period)
    band_width = ema_high - ema_low
    zk1 = ema_high + band_width
    zd1 = ema_low - band_width
    zd2 = _trailing_ema_sma_seed(zd1, channel_period)
    body_high = np.maximum(o, c)
    body_low = np.minimum(o, c)
    over_low = np.maximum(body_low, zk1)
    yellow_candle = ((zd1 > low_arr) & (zd1 < h)) | ((zd1 > np.minimum(c, o)) & (zd1 < np.maximum(c, o))) | (zd1 > h)
    white_candle = (body_high > zk1) & (body_high > over_low)
    buy_observation = _new_third_consecutive(yellow_candle)
    sell_observation = _new_third_consecutive(white_candle)
    delta = c - _ref(c, 1)
    var23_num = _double_trailing_ema(delta, var23_period)
    var23_den = _double_trailing_ema(np.abs(delta), var23_period)
    with np.errstate(divide="ignore", invalid="ignore"):
        var23 = np.where(np.isfinite(var23_den) & (var23_den != 0), 100.0 * var23_num / var23_den, np.nan)
    callback_buy = (_llv(var23, 2) == _llv(var23, 7)) & (_count(var23 < 0, 2) > 0) & _cross(var23, _ma(var23, 2))
    xg_observation = (zd1 > h) & callback_buy & (low_arr <= zd1)
    return {
        "zk1": zk1,
        "zd1": zd1,
        "zd2": zd2,
        "yellow_candle": yellow_candle,
        "white_candle": white_candle,
        "buy_observation": buy_observation,
        "sell_observation": sell_observation,
        "var23": var23,
        "callback_buy": callback_buy,
        "xg_observation": xg_observation,
    }


def _double_trailing_ema(values: Sequence[float], period: int) -> np.ndarray:
    return _trailing_ema_sma_seed(_trailing_ema_sma_seed(values, period), period)


def _trailing_ema_sma_seed(values: Sequence[float], period: int) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    out = np.full(len(arr), np.nan, dtype=float)
    alpha = 2.0 / (period + 1)
    previous: float | None = None
    for index, value in enumerate(arr):
        if previous is None:
            start = index - period + 1
            if start < 0:
                continue
            window = arr[start : index + 1]
            if not np.all(np.isfinite(window)):
                continue
            previous = float(np.mean(window))
            out[index] = previous
            continue
        if not np.isfinite(value):
            continue
        previous = alpha * float(value) + (1.0 - alpha) * previous
        out[index] = previous
    return out


def _ma(values: Sequence[float], period: int) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    out = np.full(len(arr), np.nan, dtype=float)
    for index in range(period - 1, len(arr)):
        window = arr[index - period + 1 : index + 1]
        if np.all(np.isfinite(window)):
            out[index] = float(np.mean(window))
    return out


def _ref(values: Sequence[float], periods: int = 1) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    out = np.full(len(arr), np.nan, dtype=float)
    out[periods:] = arr[:-periods]
    return out


def _llv(values: Sequence[float], period: int) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    out = np.full(len(arr), np.nan, dtype=float)
    for index in range(len(arr)):
        window = arr[max(0, index - period + 1) : index + 1]
        finite = window[np.isfinite(window)]
        if len(finite) > 0:
            out[index] = float(np.min(finite))
    return out


def _count(condition: Sequence[bool], period: int) -> np.ndarray:
    flags = np.asarray(condition, dtype=bool)
    out = np.zeros(len(flags), dtype=int)
    for index in range(len(flags)):
        out[index] = int(np.sum(flags[max(0, index - period + 1) : index + 1]))
    return out


def _cross(left: Sequence[float], right: Sequence[float]) -> np.ndarray:
    left_arr = np.asarray(left, dtype=float)
    right_arr = np.asarray(right, dtype=float)
    _require_same_length(left=left_arr, right=right_arr)
    out = np.zeros(len(left_arr), dtype=bool)
    for index in range(1, len(left_arr)):
        values = (left_arr[index - 1], right_arr[index - 1], left_arr[index], right_arr[index])
        if not all(np.isfinite(value) for value in values):
            continue
        out[index] = left_arr[index - 1] <= right_arr[index - 1] and left_arr[index] > right_arr[index]
    return out


def _new_third_consecutive(flags: Sequence[bool]) -> np.ndarray:
    arr = np.asarray(flags, dtype=bool)
    out = np.zeros(len(arr), dtype=bool)
    for index in range(2, len(arr)):
        previous_three = arr[index] and arr[index - 1] and arr[index - 2]
        out[index] = previous_three and not bool(arr[index - 3] if index >= 3 else False)
    return out


def _require_same_length(**arrays: Sequence[Any]) -> None:
    lengths = {name: len(value) for name, value in arrays.items()}
    if len(set(lengths.values())) != 1:
        raise ValueError(f"input lengths must match: {lengths}")


def _require_positive_period(name: str, value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
