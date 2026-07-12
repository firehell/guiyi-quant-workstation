"""HTDY original Tongdaxin formula PoC.

This module intentionally preserves the original XMA-based formula shape.
XMA reads future bars relative to the current bar, so every derived field here
is observation-only and forbidden for trusted backtests, live evaluation,
signal_events, notifications, or trading decisions.
"""

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

import numpy as np


ORIGINAL_FIELD_ALIASES: Mapping[str, str] = {
    "zk1": "ZK1",
    "zd1": "ZD1",
    "zd2": "ZD2",
    "yellow_candle": "黄K",
    "white_candle": "白K",
    "buy_observation": "买多信号",
    "sell_observation": "卖空信号",
    "var23": "VAR23",
    "callback_buy": "回调买",
    "xg": "XG",
    "ddx": "DDX",
    "v2": "V2",
    "v5": "V5",
    "v10": "V10",
    "v20": "V20",
    "dy": "DY",
    "dy2": "DY2",
    "xg2": "XG2",
    "xg2_draw_observation": "XG2_DRAWTEXT",
}

NUMERIC_FIELDS = (
    "zk1",
    "zd1",
    "zd2",
    "var23",
    "ddx",
    "v2",
    "v5",
    "v10",
    "v20",
    "dy2",
)

BOOLEAN_FIELDS = (
    "yellow_candle",
    "white_candle",
    "buy_observation",
    "sell_observation",
    "callback_buy",
    "xg",
    "dy",
    "xg2",
    "xg2_draw_observation",
)


@dataclass(frozen=True)
class HtdyOriginalResult:
    """Aligned HTDY original formula output."""

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
            for name, values in self.fields.items():
                key = ORIGINAL_FIELD_ALIASES[name] if original_names else name
                row[key] = _scalar_or_none(values[index], round_digits=round_digits)
            rows.append(row)
        return rows

    def to_payload(self, *, original_names: bool = False, round_digits: int | None = 6) -> dict[str, Any]:
        return {
            "metadata": dict(self.metadata),
            "rows": self.to_rows(original_names=original_names, round_digits=round_digits),
        }


def normalize_period(period: int) -> int:
    value = int(period)
    if value <= 0:
        raise ValueError("period must be positive")
    return value + 1 if value % 2 == 0 else value


def xma(values: Sequence[float], period: int) -> np.ndarray:
    """Tongdaxin-style centered XMA; intentionally future-looking."""
    arr = _float_array(values, name="values")
    normalized_period = normalize_period(period)
    p = (normalized_period - 1) // 2
    out = np.full(len(arr), np.nan, dtype=float)
    for index in range(len(arr)):
        start = index - p - 1
        end = index + (normalized_period - p) - 1
        window = _slice_like_numpy(arr, start, end)
        finite = window[np.isfinite(window)]
        if len(finite) > 0:
            out[index] = float(np.mean(finite))
    return out


def ema(values: Sequence[float], period: int) -> np.ndarray:
    """EMA over finite values, matching the current Web observation layer."""
    arr = _float_array(values, name="values")
    if period <= 0:
        raise ValueError("period must be positive")
    out = np.full(len(arr), np.nan, dtype=float)
    alpha = 2.0 / (period + 1)
    previous: float | None = None
    for index, value in enumerate(arr):
        if not np.isfinite(value):
            continue
        previous = float(value) if previous is None else alpha * float(value) + (1.0 - alpha) * previous
        out[index] = previous
    return out


def ma(values: Sequence[float], period: int) -> np.ndarray:
    arr = _float_array(values, name="values")
    out = np.full(len(arr), np.nan, dtype=float)
    if period <= 0:
        raise ValueError("period must be positive")
    for index in range(period - 1, len(arr)):
        window = arr[index - period + 1 : index + 1]
        if np.all(np.isfinite(window)):
            out[index] = float(np.mean(window))
    return out


def sma(values: Sequence[float], period: int, weight: int) -> np.ndarray:
    """Tongdaxin SMA(X,N,M) = (M*X + (N-M)*Y')/N."""
    arr = _float_array(values, name="values")
    if period <= 0:
        raise ValueError("period must be positive")
    out = np.full(len(arr), np.nan, dtype=float)
    previous: float | None = None
    for index, value in enumerate(arr):
        if not np.isfinite(value):
            continue
        previous = float(value) if previous is None else (weight * float(value) + (period - weight) * previous) / period
        out[index] = previous
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
    out = np.full(len(arr), np.nan, dtype=float)
    if period <= 0:
        raise ValueError("period must be positive")
    for index in range(len(arr)):
        window = arr[max(0, index - period + 1) : index + 1]
        finite = window[np.isfinite(window)]
        if len(finite) > 0:
            out[index] = float(np.min(finite))
    return out


def count(condition: Sequence[bool], period: int) -> np.ndarray:
    flags = np.asarray(condition, dtype=bool)
    out = np.zeros(len(flags), dtype=int)
    if period <= 0:
        raise ValueError("period must be positive")
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


def tdx_if(condition: Sequence[bool], true_value: Sequence[float] | float, false_value: Sequence[float] | float) -> np.ndarray:
    return np.where(np.asarray(condition, dtype=bool), true_value, false_value)


def compute_htdy_original(
    datetimes: Sequence[Any],
    open_: Sequence[float],
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    volume: Sequence[float],
    *,
    capital: float = 0.0,
    from_open: float = 1.0,
    channel_period: int = 25,
    var23_period: int = 6,
) -> HtdyOriginalResult:
    """Compute the original HTDY observation-only formula over aligned bars."""
    dt = np.asarray(datetimes, dtype=object)
    o = _float_array(open_, name="open")
    h = _float_array(high, name="high")
    low_arr = _float_array(low, name="low")
    c = _float_array(close, name="close")
    vol = _float_array(volume, name="volume")
    _require_same_length(datetimes=dt, open=o, high=h, low=low_arr, close=c, volume=vol)
    if from_open == 0:
        raise ValueError("from_open must be non-zero")

    xma_high = xma(xma(h, channel_period), channel_period)
    xma_low = xma(xma(low_arr, channel_period), channel_period)
    band_width = xma_high - xma_low
    zk1 = xma_high + band_width
    zd1 = xma_low - band_width
    zd2 = ema(zd1, channel_period)

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
    var23_num = xma(xma(delta, var23_period), var23_period)
    var23_den = xma(xma(np.abs(delta), var23_period), var23_period)
    with np.errstate(divide="ignore", invalid="ignore"):
        var23 = 100.0 * var23_num / var23_den
    callback_buy = (llv(var23, 2) == llv(var23, 7)) & (count(var23 < 0, 2) > 0) & cross(var23, ma(var23, 2))
    xg = (zd1 > h) & callback_buy & (low_arr <= zd1)

    ddx = compute_ddx(o, h, low_arr, c, vol, capital=capital)
    prev_close = ref(c, 1)
    v2_input = tdx_if(c >= prev_close, ddx, -ddx / 100.0)
    v2 = sma(v2_input, 2, 1)
    v5 = sma(v2 * 120.0 / float(from_open) * 5.0, 2, 1)
    v10 = sma(v5, 5, 1)
    v20 = sma(v10, 5, 1)
    dy = c < prev_close
    dy2 = ref(v2, 1) - dy.astype(float)
    prev_close_safe = np.where(np.isfinite(prev_close) & (prev_close != 0), prev_close, np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        pct_chg = c / prev_close_safe
    xg2 = (c > o) & (dy2 < 0.02) & (ma(c, 5) > ma(c, 60)) & (pct_chg >= 1.02) & (h < zk1)
    xg2_draw_observation = xg2 & (low_arr < zd1)

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
        "xg": xg,
        "ddx": ddx,
        "v2": v2,
        "v5": v5,
        "v10": v10,
        "v20": v20,
        "dy": dy,
        "dy2": dy2,
        "xg2": xg2,
        "xg2_draw_observation": xg2_draw_observation,
    }
    metadata = {
        "indicator_code": "huo_tian_da_you",
        "indicator_version": "original-v0",
        "strategy_code": "huotian_dayou_original",
        "strategy_version": "v0-observation-only",
        "status": "observation_only",
        "repainting_risk": "known",
        "future_looking": True,
        "backtest_capable": False,
        "live_capable": False,
        "alert_capable": False,
        "trading_capable": False,
        "capital": capital,
        "capital_branch": "futures_capital_0" if capital == 0 else "stock_capital_nonzero",
        "from_open": from_open,
        "currbarscount_semantics": "each_row_treated_as_chart_last_bar_for_poc",
        "output_fields": [ORIGINAL_FIELD_ALIASES[name] for name in fields],
    }
    return HtdyOriginalResult(
        datetimes=dt,
        open=o,
        high=h,
        low=low_arr,
        close=c,
        volume=vol,
        fields=fields,
        metadata=metadata,
    )


def compute_ddx(
    open_: Sequence[float],
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    volume: Sequence[float],
    *,
    capital: float = 0.0,
) -> np.ndarray:
    o = _float_array(open_, name="open")
    h = _float_array(high, name="high")
    low_arr = _float_array(low, name="low")
    c = _float_array(close, name="close")
    vol = _float_array(volume, name="volume")
    _require_same_length(open=o, high=h, low=low_arr, close=c, volume=vol)

    jj = (h + low_arr + c) / 3.0
    qj0 = vol / np.where(h == low_arr, 4.0, h - low_arr)
    if capital == 0:
        qj1 = qj0 * (jj - np.minimum(c, o))
        qj2 = qj0 * (np.minimum(o, c) - low_arr)
        qj3 = qj0 * (h - np.maximum(o, c))
        qj4 = qj0 * (np.maximum(c, o) - jj)
    else:
        qj1 = qj0 * np.where(h == low_arr, 1.0, np.minimum(o, c) - low_arr)
        qj2 = qj0 * np.where(h == low_arr, 1.0, jj - np.minimum(c, o))
        qj3 = qj0 * np.where(h == low_arr, 1.0, h - np.maximum(o, c))
        qj4 = qj0 * np.where(h == low_arr, 1.0, np.maximum(c, o) - jj)
    return ((qj1 + qj2) - (qj3 + qj4)) / 10000.0


def new_third_consecutive(flags: Sequence[bool]) -> np.ndarray:
    arr = np.asarray(flags, dtype=bool)
    out = np.zeros(len(arr), dtype=bool)
    for index in range(2, len(arr)):
        previous_three = arr[index] and arr[index - 1] and arr[index - 2]
        out[index] = previous_three and not bool(arr[index - 3] if index >= 3 else False)
    return out


def indicator_risk_catalog() -> dict[str, dict[str, Any]]:
    return {
        "XMA": {
            "classification": "forbidden_for_backtest_signal",
            "future_looking": True,
            "repainting": True,
            "full_series_precompute": True,
            "depends_on": [],
        },
        "ZK1_ZD1_ZD2": {
            "classification": "forbidden_for_backtest_signal",
            "future_looking": True,
            "repainting": True,
            "full_series_precompute": True,
            "depends_on": ["XMA"],
        },
        "YELLOW_WHITE_THREE_BAR": {
            "classification": "observation_only",
            "future_looking": True,
            "repainting": True,
            "depends_on": ["ZK1_ZD1_ZD2", "REF"],
        },
        "VAR23": {
            "classification": "forbidden_for_backtest_signal",
            "future_looking": True,
            "repainting": True,
            "depends_on": ["XMA", "REF"],
        },
        "XG": {
            "classification": "observation_only",
            "future_looking": True,
            "repainting": True,
            "depends_on": ["ZK1_ZD1_ZD2", "VAR23", "MA", "LLV", "COUNT", "CROSS"],
        },
        "DDX_V2_V5_V10_V20": {
            "classification": "candidate_after_rewrite",
            "future_looking": False,
            "repainting": False,
            "depends_on": ["IF", "SMA", "REF"],
        },
        "XG2": {
            "classification": "observation_only",
            "future_looking": True,
            "repainting": True,
            "depends_on": ["ZK1_ZD1_ZD2", "DDX_V2_V5_V10_V20", "MA", "REF", "CURRBARSCOUNT"],
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


def compute_synthetic(length: int = 96) -> HtdyOriginalResult:
    bars = synthetic_bars(length)
    return compute_htdy_original(
        bars["datetime"],
        bars["open"],
        bars["high"],
        bars["low"],
        bars["close"],
        bars["volume"],
    )


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


def summarize(result: HtdyOriginalResult) -> dict[str, Any]:
    return {
        "row_count": len(result.datetimes),
        "first_datetime": _scalar_or_none(result.datetimes[0], round_digits=None) if len(result.datetimes) else None,
        "last_datetime": _scalar_or_none(result.datetimes[-1], round_digits=None) if len(result.datetimes) else None,
        "yellow_candle_count": _truthy_count(result.fields["yellow_candle"]),
        "white_candle_count": _truthy_count(result.fields["white_candle"]),
        "buy_observation_count": _truthy_count(result.fields["buy_observation"]),
        "sell_observation_count": _truthy_count(result.fields["sell_observation"]),
        "xg_count": _truthy_count(result.fields["xg"]),
        "xg2_count": _truthy_count(result.fields["xg2"]),
        "metadata": dict(result.metadata),
    }
