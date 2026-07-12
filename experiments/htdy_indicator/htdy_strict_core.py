"""HTDY strict backward-looking research candidate.

This module defines ``huotian_dayou_strict_v1`` as a separate research
candidate from the original Tongdaxin/XMA formula.  It replaces future-looking
XMA calls with trailing double EMA and intentionally does not expose any order,
signal_events, live evaluator, or notification integration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

import numpy as np


STRICT_FIELD_ALIASES: Mapping[str, str] = {
    "zk1": "ZK1",
    "zd1": "ZD1",
    "zd2": "ZD2",
    "yellow_candle": "黄K观察",
    "white_candle": "白K观察",
    "buy_observation": "三连黄K观察",
    "sell_observation": "三连白K观察",
    "var23": "VAR23_STRICT",
    "callback_buy": "回调买观察",
    "xg_observation": "XG观察",
}

NUMERIC_FIELDS = ("zk1", "zd1", "zd2", "var23")
BOOLEAN_FIELDS = (
    "yellow_candle",
    "white_candle",
    "buy_observation",
    "sell_observation",
    "callback_buy",
    "xg_observation",
)
STRICT_OUTPUT_FIELDS = NUMERIC_FIELDS + BOOLEAN_FIELDS


@dataclass(frozen=True)
class HtdyStrictResult:
    """Aligned HTDY strict research-candidate output."""

    datetimes: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    fields: dict[str, np.ndarray]
    metadata: dict[str, Any]

    def to_rows(self, *, original_names: bool = False, round_digits: int | None = 6) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for index in range(len(self.datetimes)):
            row: dict[str, Any] = {
                "datetime": _scalar_or_none(self.datetimes[index], round_digits=round_digits),
                "open": _scalar_or_none(self.open[index], round_digits=round_digits),
                "high": _scalar_or_none(self.high[index], round_digits=round_digits),
                "low": _scalar_or_none(self.low[index], round_digits=round_digits),
                "close": _scalar_or_none(self.close[index], round_digits=round_digits),
                "volume": _scalar_or_none(self.volume[index], round_digits=round_digits),
            }
            for name in STRICT_OUTPUT_FIELDS:
                key = STRICT_FIELD_ALIASES[name] if original_names else name
                row[key] = _scalar_or_none(self.fields[name][index], round_digits=round_digits)
            rows.append(row)
        return rows

    def to_payload(self, *, original_names: bool = False, round_digits: int | None = 6) -> dict[str, Any]:
        return {
            "metadata": dict(self.metadata),
            "rows": self.to_rows(original_names=original_names, round_digits=round_digits),
        }


def compute_htdy_strict(
    datetimes: Sequence[Any],
    open_: Sequence[float],
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    volume: Sequence[float],
    *,
    channel_period: int = 25,
    var23_period: int = 6,
) -> HtdyStrictResult:
    """Compute the HTDY strict v1 research candidate over aligned bars."""
    if channel_period <= 0:
        raise ValueError("channel_period must be positive")
    if var23_period <= 0:
        raise ValueError("var23_period must be positive")

    dt = np.asarray(datetimes, dtype=object)
    o = _float_array(open_, name="open")
    h = _float_array(high, name="high")
    low_arr = _float_array(low, name="low")
    c = _float_array(close, name="close")
    vol = _float_array(volume, name="volume")
    _require_same_length(datetimes=dt, open=o, high=h, low=low_arr, close=c, volume=vol)

    ema_high = double_trailing_ema(h, channel_period)
    ema_low = double_trailing_ema(low_arr, channel_period)
    band_width = ema_high - ema_low
    zk1 = ema_high + band_width
    zd1 = ema_low - band_width
    zd2 = trailing_ema_sma_seed(zd1, channel_period)

    body_high = np.maximum(o, c)
    body_low = np.minimum(o, c)
    over_low = np.maximum(body_low, zk1)
    yellow_candle = ((zd1 > low_arr) & (zd1 < h)) | (
        (zd1 > np.minimum(c, o)) & (zd1 < np.maximum(c, o))
    ) | (zd1 > h)
    white_candle = (body_high > zk1) & (body_high > over_low)
    buy_observation = new_third_consecutive(yellow_candle)
    sell_observation = new_third_consecutive(white_candle)

    delta = c - ref(c, 1)
    var23_num = double_trailing_ema(delta, var23_period)
    var23_den = double_trailing_ema(np.abs(delta), var23_period)
    with np.errstate(divide="ignore", invalid="ignore"):
        var23 = np.where(np.isfinite(var23_den) & (var23_den != 0), 100.0 * var23_num / var23_den, np.nan)
    callback_buy = (llv(var23, 2) == llv(var23, 7)) & (count(var23 < 0, 2) > 0) & cross(var23, ma(var23, 2))
    xg_observation = (zd1 > h) & callback_buy & (low_arr <= zd1)

    fields = {
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
    metadata = {
        "indicator_code": "huo_tian_da_you",
        "indicator_version": "huotian_dayou_strict_v1",
        "source_version": "huotian_dayou_original_v0",
        "strategy_code": "huotian_dayou_strict",
        "strategy_version": "v1-strict-research-candidate",
        "xma_replacement_policy": "double_trailing_ema",
        "ema_seed_policy": "sma_window",
        "status": "strict_research_candidate",
        "repainting_risk": "none_detected_by_future_tail_tests",
        "future_looking": False,
        "closed_bar_only": True,
        "backtest_capable": False,
        "live_capable": False,
        "alert_capable": False,
        "trading_capable": False,
        "excluded_original_fields": ["DDX", "V2", "V5", "V10", "V20", "DY", "DY2", "XG2", "XG2_DRAWTEXT"],
        "output_fields": [STRICT_FIELD_ALIASES[name] for name in STRICT_OUTPUT_FIELDS],
    }
    return HtdyStrictResult(
        datetimes=dt,
        open=o,
        high=h,
        low=low_arr,
        close=c,
        volume=vol,
        fields=fields,
        metadata=metadata,
    )


def double_trailing_ema(values: Sequence[float], period: int) -> np.ndarray:
    """Two trailing EMA passes using SMA-window seed and leading NaN warm-up."""
    return trailing_ema_sma_seed(trailing_ema_sma_seed(values, period), period)


def trailing_ema_sma_seed(values: Sequence[float], period: int) -> np.ndarray:
    """Trailing EMA with SMA seed once a finite window is available."""
    arr = _float_array(values, name="values")
    if period <= 0:
        raise ValueError("period must be positive")
    out = np.full(len(arr), np.nan, dtype=float)
    alpha = 2.0 / (period + 1)
    previous: float | None = None
    for index in range(len(arr)):
        value = arr[index]
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


def ma(values: Sequence[float], period: int) -> np.ndarray:
    arr = _float_array(values, name="values")
    if period <= 0:
        raise ValueError("period must be positive")
    out = np.full(len(arr), np.nan, dtype=float)
    for index in range(period - 1, len(arr)):
        window = arr[index - period + 1 : index + 1]
        if np.all(np.isfinite(window)):
            out[index] = float(np.mean(window))
    return out


def ref(values: Sequence[float] | Sequence[bool], periods: int = 1, *, fill: float | bool | None = None) -> np.ndarray:
    arr = np.asarray(values)
    if periods <= 0:
        return arr.copy()
    if arr.dtype == bool:
        out = np.full(len(arr), bool(fill) if fill is not None else False, dtype=bool)
    else:
        out = np.full(len(arr), float(fill) if fill is not None else np.nan, dtype=float)
    out[periods:] = arr[:-periods]
    return out


def llv(values: Sequence[float], period: int) -> np.ndarray:
    arr = _float_array(values, name="values")
    if period <= 0:
        raise ValueError("period must be positive")
    out = np.full(len(arr), np.nan, dtype=float)
    for index in range(len(arr)):
        window = arr[max(0, index - period + 1) : index + 1]
        finite = window[np.isfinite(window)]
        if len(finite) > 0:
            out[index] = float(np.min(finite))
    return out


def count(condition: Sequence[bool], period: int) -> np.ndarray:
    flags = np.asarray(condition, dtype=bool)
    if period <= 0:
        raise ValueError("period must be positive")
    out = np.zeros(len(flags), dtype=int)
    for index in range(len(flags)):
        out[index] = int(np.sum(flags[max(0, index - period + 1) : index + 1]))
    return out


def cross(left: Sequence[float], right: Sequence[float]) -> np.ndarray:
    left_arr = _float_array(left, name="left")
    right_arr = _float_array(right, name="right")
    _require_same_length(left=left_arr, right=right_arr)
    out = np.zeros(len(left_arr), dtype=bool)
    for index in range(1, len(left_arr)):
        values = (left_arr[index - 1], right_arr[index - 1], left_arr[index], right_arr[index])
        if not all(np.isfinite(value) for value in values):
            continue
        out[index] = left_arr[index - 1] <= right_arr[index - 1] and left_arr[index] > right_arr[index]
    return out


def new_third_consecutive(flags: Sequence[bool]) -> np.ndarray:
    arr = np.asarray(flags, dtype=bool)
    out = np.zeros(len(arr), dtype=bool)
    for index in range(2, len(arr)):
        previous_three = arr[index] and arr[index - 1] and arr[index - 2]
        out[index] = previous_three and not bool(arr[index - 3] if index >= 3 else False)
    return out


def strict_risk_catalog() -> dict[str, dict[str, Any]]:
    return {
        "DOUBLE_TRAILING_EMA": {
            "classification": "strict_rewrite_candidate",
            "future_looking": False,
            "repainting": False,
            "depends_on": ["current_and_past_bars"],
        },
        "ZK1_ZD1_ZD2": {
            "classification": "strict_research_candidate",
            "future_looking": False,
            "repainting": False,
            "depends_on": ["DOUBLE_TRAILING_EMA"],
        },
        "YELLOW_WHITE_THREE_BAR": {
            "classification": "observation_candidate",
            "future_looking": False,
            "repainting": False,
            "depends_on": ["ZK1_ZD1_ZD2", "REF"],
        },
        "VAR23": {
            "classification": "strict_research_candidate",
            "future_looking": False,
            "repainting": False,
            "depends_on": ["DOUBLE_TRAILING_EMA", "REF"],
        },
        "XG_OBSERVATION": {
            "classification": "observation_candidate",
            "future_looking": False,
            "repainting": False,
            "depends_on": ["ZK1_ZD1_ZD2", "VAR23", "MA", "LLV", "COUNT", "CROSS"],
        },
        "XG2": {
            "classification": "excluded_from_strict_v1",
            "future_looking": None,
            "repainting": None,
            "depends_on": ["CURRBARSCOUNT", "FROMOPEN", "DDX_V2_V5_V10_V20", "ZK1_ZD1_ZD2"],
        },
    }


def synthetic_bars(length: int = 96) -> dict[str, list[Any]]:
    if length <= 0:
        raise ValueError("length must be positive")
    index = np.arange(length, dtype=float)
    base = 100.0 + index * 0.18 + np.sin(index / 5.0) * 2.0
    open_ = base + np.sin(index / 3.0) * 0.25
    close = base + np.cos(index / 4.0) * 0.35
    high = np.maximum(open_, close) + 1.2 + (index % 5) * 0.08
    low = np.minimum(open_, close) - 1.1 - (index % 7) * 0.06
    volume = 1000.0 + (index % 13) * 30.0 + index * 4.0
    datetimes = [f"2026-01-{int(i // 24) + 1:02d} {int(i % 24):02d}:00:00" for i in range(length)]
    return {
        "datetime": datetimes,
        "open": open_.tolist(),
        "high": high.tolist(),
        "low": low.tolist(),
        "close": close.tolist(),
        "volume": volume.tolist(),
    }


def compute_synthetic(length: int = 96) -> HtdyStrictResult:
    bars = synthetic_bars(length)
    return compute_htdy_strict(
        bars["datetime"],
        bars["open"],
        bars["high"],
        bars["low"],
        bars["close"],
        bars["volume"],
    )


def _float_array(values: Sequence[float], *, name: str) -> np.ndarray:
    try:
        return np.asarray(values, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc


def _require_same_length(**arrays: Sequence[Any]) -> None:
    lengths = {name: len(value) for name, value in arrays.items()}
    if len(set(lengths.values())) != 1:
        raise ValueError(f"input lengths must match: {lengths}")


def _scalar_or_none(value: Any, *, round_digits: int | None) -> Any:
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, bool):
        return value
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        value = float(value)
    if isinstance(value, float):
        if not np.isfinite(value):
            return None
        return round(value, round_digits) if round_digits is not None else value
    return value


def _truthy_count(values: Iterable[bool]) -> int:
    return int(np.sum(np.asarray(list(values), dtype=bool)))


def summarize(result: HtdyStrictResult) -> dict[str, Any]:
    return {
        "row_count": len(result.datetimes),
        "first_datetime": _scalar_or_none(result.datetimes[0], round_digits=None) if len(result.datetimes) else None,
        "last_datetime": _scalar_or_none(result.datetimes[-1], round_digits=None) if len(result.datetimes) else None,
        "yellow_candle_count": _truthy_count(result.fields["yellow_candle"]),
        "white_candle_count": _truthy_count(result.fields["white_candle"]),
        "buy_observation_count": _truthy_count(result.fields["buy_observation"]),
        "sell_observation_count": _truthy_count(result.fields["sell_observation"]),
        "xg_observation_count": _truthy_count(result.fields["xg_observation"]),
        "metadata": dict(result.metadata),
    }
