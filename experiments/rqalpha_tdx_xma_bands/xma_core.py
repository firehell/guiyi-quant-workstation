"""
通达信 XMA 通道指标核心（研究 PoC）

警告：XMA 为偏移移动平均，使用当前 bar 之后约 N/2 根 K 线，存在未来函数 / 重绘风险。
本模块故意保留该设计，结果不可作为无未来函数的可信回测结论。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np


def _normalize_period(n: int) -> int:
    """通达信 XMA 偶数周期按 N+1（奇数）处理。"""
    n = int(n)
    if n <= 0:
        raise ValueError("period must be positive")
    return n + 1 if n % 2 == 0 else n


def xma(src: Sequence[float], period: int) -> np.ndarray:
    """通达信 XMA：居中窗口均值，含未来 bar。"""
    arr = np.asarray(src, dtype=float)
    n = _normalize_period(period)
    p = (n - 1) // 2
    out = np.full(len(arr), np.nan, dtype=float)
    for i in range(len(arr)):
        start = i - p - 1
        end = i + (n - p) - 1
        window = arr[start:end]
        if len(window) == 0:
            continue
        out[i] = float(np.nanmean(window))
    return out


def ema(src: Sequence[float], period: int) -> np.ndarray:
    arr = np.asarray(src, dtype=float)
    if len(arr) == 0:
        return arr.copy()
    alpha = 2.0 / (period + 1)
    out = np.empty(len(arr), dtype=float)
    out[0] = arr[0]
    for i in range(1, len(arr)):
        out[i] = alpha * arr[i] + (1 - alpha) * out[i - 1]
    return out


def ma(src: Sequence[float], period: int) -> np.ndarray:
    arr = np.asarray(src, dtype=float)
    out = np.full(len(arr), np.nan, dtype=float)
    if period <= 0:
        return out
    for i in range(period - 1, len(arr)):
        out[i] = float(np.mean(arr[i - period + 1 : i + 1]))
    return out


def sma(src: Sequence[float], n: int, m: int) -> np.ndarray:
    """通达信 SMA(X,N,M) = (M*X + (N-M)*Y')/N"""
    arr = np.asarray(src, dtype=float)
    out = np.empty(len(arr), dtype=float)
    if len(arr) == 0:
        return out
    out[0] = arr[0]
    for i in range(1, len(arr)):
        out[i] = (m * arr[i] + (n - m) * out[i - 1]) / n
    return out


def ref(src: Sequence[float], n: int = 1) -> np.ndarray:
    arr = np.asarray(src, dtype=float)
    out = np.full(len(arr), np.nan, dtype=float)
    if n <= 0:
        return arr.copy()
    out[n:] = arr[:-n]
    return out


def llv(src: Sequence[float], period: int) -> np.ndarray:
    arr = np.asarray(src, dtype=float)
    out = np.full(len(arr), np.nan, dtype=float)
    for i in range(len(arr)):
        start = max(0, i - period + 1)
        out[i] = float(np.nanmin(arr[start : i + 1]))
    return out


def count(cond: Sequence[bool], period: int) -> np.ndarray:
    flags = np.asarray(cond, dtype=bool)
    out = np.zeros(len(flags), dtype=int)
    for i in range(len(flags)):
        start = max(0, i - period + 1)
        out[i] = int(np.sum(flags[start : i + 1]))
    return out


def cross(a: Sequence[float], b: Sequence[float]) -> np.ndarray:
    aa = np.asarray(a, dtype=float)
    bb = np.asarray(b, dtype=float)
    out = np.zeros(len(aa), dtype=bool)
    for i in range(1, len(aa)):
        if np.isnan(aa[i - 1]) or np.isnan(bb[i - 1]) or np.isnan(aa[i]) or np.isnan(bb[i]):
            continue
        out[i] = aa[i - 1] <= bb[i - 1] and aa[i] > bb[i]
    return out


def compute_bands(
    high: Sequence[float],
    low: Sequence[float],
    period: int = 25,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    xma_h = xma(xma(high, period), period)
    xma_l = xma(xma(low, period), period)
    band_width = xma_h - xma_l
    zk1 = band_width + xma_h
    zd1 = xma_l - band_width
    zd2 = ema(zd1, period)
    return zk1, zd1, zd2


def compute_var23(close: Sequence[float]) -> np.ndarray:
    delta = np.asarray(close, dtype=float) - ref(close, 1)
    num = xma(xma(delta, 6), 6)
    den = xma(xma(np.abs(delta), 6), 6)
    with np.errstate(divide="ignore", invalid="ignore"):
        return 100.0 * num / den


def compute_callback_buy(var23: Sequence[float]) -> np.ndarray:
    v = np.asarray(var23, dtype=float)
    llv2 = llv(v, 2)
    llv7 = llv(v, 7)
    cond_llv = llv2 == llv7
    cond_count = count(v < 0, 2) > 0
    var23_ma2 = ma(v, 2)
    cond_cross = cross(v, var23_ma2)
    return cond_llv & cond_count & cond_cross


def compute_xg(
    high: Sequence[float],
    low: Sequence[float],
    zd1: Sequence[float],
    callback_buy: Sequence[bool],
) -> np.ndarray:
    h = np.asarray(high, dtype=float)
    low_arr = np.asarray(low, dtype=float)
    z = np.asarray(zd1, dtype=float)
    cb = np.asarray(callback_buy, dtype=bool)
    return (z > h) & cb & (low_arr <= z)


def compute_ddx(
    open_: Sequence[float],
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    volume: Sequence[float],
) -> np.ndarray:
    """CAPITAL=0 分支（期货）。"""
    o = np.asarray(open_, dtype=float)
    h = np.asarray(high, dtype=float)
    low_arr = np.asarray(low, dtype=float)
    c = np.asarray(close, dtype=float)
    vol = np.asarray(volume, dtype=float)
    jj = (h + low_arr + c) / 3.0
    hl_range = np.where(h == low_arr, 4.0, h - low_arr)
    qj0 = vol / hl_range
    qj1 = qj0 * (jj - np.minimum(c, o))
    qj2 = qj0 * (np.minimum(o, c) - low_arr)
    qj3 = qj0 * (h - np.maximum(o, c))
    qj4 = qj0 * (np.maximum(c, o) - jj)
    return ((qj1 + qj2) - (qj3 + qj4)) / 10000.0


def compute_xg2(
    open_: Sequence[float],
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    volume: Sequence[float],
    zk1: Sequence[float],
    zd1: Sequence[float],
    *,
    from_open: float = 1.0,
) -> np.ndarray:
    o = np.asarray(open_, dtype=float)
    h = np.asarray(high, dtype=float)
    low_arr = np.asarray(low, dtype=float)
    c = np.asarray(close, dtype=float)
    zk = np.asarray(zk1, dtype=float)
    zd = np.asarray(zd1, dtype=float)

    ddx = compute_ddx(o, h, low_arr, c, volume)
    prev_c = ref(c, 1)
    v2_input = np.where(c >= prev_c, ddx, -ddx / 100.0)
    v2 = sma(v2_input, 2, 1)
    v5_input = v2 * 120.0 / from_open * 5.0
    _ = sma(v5_input, 2, 1)  # 公式含 V5/V10/V20，XG2 未直接使用，保留计算链完整性

    # PoC：当前 bar 视为图表末 bar（CURRBARSCOUNT=1）
    dy = c < prev_c
    dy2 = ref(v2, 1) - dy.astype(float)

    ma5 = ma(c, 5)
    ma60 = ma(c, 60)
    prev_c_safe = np.where(np.isnan(prev_c) | (prev_c == 0), np.nan, prev_c)
    with np.errstate(divide="ignore", invalid="ignore"):
        pct_chg = c / prev_c_safe

    return (
        (c > o)
        & (dy2 < 0.02)
        & (ma5 > ma60)
        & (pct_chg >= 1.02)
        & (h < zk)
        & (low_arr < zd)
    )


@dataclass
class PrecomputedSignals:
    datetimes: np.ndarray
    entry_long: np.ndarray
    exit_long: np.ndarray
    xg: np.ndarray
    xg2: np.ndarray
    zk1: np.ndarray
    zd1: np.ndarray
    zd2: np.ndarray


def indicator_risk_catalog() -> dict[str, dict[str, Any]]:
    """Return static review metadata for the Tongdaxin XMA PoC indicators."""
    return {
        "XMA": {
            "classification": "forbidden_for_backtest_signal",
            "future_looking": True,
            "repainting": True,
            "full_series_precompute": True,
            "depends_on": [],
            "reason": "Centered/shifted moving average reads future bars relative to the current bar.",
        },
        "ZK1_ZD1_ZD2": {
            "classification": "forbidden_for_backtest_signal",
            "future_looking": True,
            "repainting": True,
            "full_series_precompute": True,
            "depends_on": ["XMA"],
            "reason": "Channel lines are derived from double XMA high/low bands.",
        },
        "VAR23": {
            "classification": "forbidden_for_backtest_signal",
            "future_looking": True,
            "repainting": True,
            "full_series_precompute": True,
            "depends_on": ["XMA", "REF"],
            "reason": "VAR23 uses double XMA over close deltas and absolute deltas.",
        },
        "XG": {
            "classification": "observation_only",
            "future_looking": True,
            "repainting": True,
            "full_series_precompute": True,
            "depends_on": ["ZK1_ZD1_ZD2", "VAR23", "MA", "LLV", "COUNT", "CROSS"],
            "reason": "Entry condition depends on XMA-derived channel and VAR23.",
        },
        "XG2": {
            "classification": "observation_only",
            "future_looking": True,
            "repainting": True,
            "full_series_precompute": True,
            "depends_on": ["ZK1_ZD1_ZD2", "DDX", "REF", "SMA", "MA"],
            "currbarscount_semantics": "poc_current_bar_as_chart_last_bar",
            "reason": "Signal depends on XMA channel and simplified CURRBARSCOUNT semantics.",
        },
        "DDX": {
            "classification": "candidate_after_rewrite",
            "future_looking": False,
            "repainting": False,
            "full_series_precompute": False,
            "depends_on": [],
            "reason": "Formula uses current OHLCV only, but still needs confirmed-bar review before promotion.",
        },
        "CURRBARSCOUNT": {
            "classification": "observation_only",
            "future_looking": False,
            "repainting": False,
            "full_series_precompute": False,
            "depends_on": [],
            "reason": "PoC treats current bar as chart-last bar; Tongdaxin rolling chart semantics need separate validation.",
        },
        "REF": {
            "classification": "candidate_after_rewrite",
            "future_looking": False,
            "repainting": False,
            "full_series_precompute": False,
            "depends_on": [],
            "reason": "Positive REF offset reads past values only in this PoC.",
        },
        "MA": {
            "classification": "candidate_after_rewrite",
            "future_looking": False,
            "repainting": False,
            "full_series_precompute": False,
            "depends_on": [],
            "reason": "Rolling mean uses current and past bars only.",
        },
        "EMA": {
            "classification": "candidate_after_rewrite",
            "future_looking": False,
            "repainting": False,
            "full_series_precompute": False,
            "depends_on": [],
            "reason": "Recursive EMA uses current and past values only.",
        },
    }


def precompute(
    datetimes: Sequence[int],
    open_: Sequence[float],
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    volume: Sequence[float],
) -> PrecomputedSignals:
    zk1, zd1, zd2 = compute_bands(high, low, 25)
    var23 = compute_var23(close)
    callback_buy = compute_callback_buy(var23)
    xg = compute_xg(high, low, zd1, callback_buy)
    xg2 = compute_xg2(open_, high, low, close, volume, zk1, zd1)

    c = np.asarray(close, dtype=float)
    zd2_arr = np.asarray(zd2, dtype=float)
    entry_long = xg | xg2
    exit_long = c < zd2_arr

    return PrecomputedSignals(
        datetimes=np.asarray(datetimes),
        entry_long=entry_long,
        exit_long=exit_long,
        xg=xg,
        xg2=xg2,
        zk1=zk1,
        zd1=zd1,
        zd2=zd2,
    )


def signals_for_range(
    signals: PrecomputedSignals,
    start_date: int,
    end_date: int,
) -> dict[int, dict[str, bool]]:
    """按 bundle datetime(int YYYYMMDD) 建立信号表。"""
    out: dict[int, dict[str, bool]] = {}
    for i, dt in enumerate(signals.datetimes):
        dt_int = int(dt)
        if dt_int < start_date or dt_int > end_date:
            continue
        out[dt_int] = {
            "entry_long": bool(signals.entry_long[i]),
            "exit_long": bool(signals.exit_long[i]),
            "xg": bool(signals.xg[i]),
            "xg2": bool(signals.xg2[i]),
        }
    return out


if __name__ == "__main__":
    sample = np.array([11.0, 12.0, 13.0, 14.0, 15.0], dtype=float)
    result = xma(sample, 3)
    # i=2: window [11,12,13,14] -> mean 12.5 per TDX offset logic
    p = (3 - 1) // 2
    i = 2
    start = i - p - 1
    end = i + (3 - p) - 1
    expected = float(np.mean(sample[start:end]))
    assert abs(result[i] - expected) < 1e-9, (result[i], expected)
    print("xma smoke ok:", result[i])
