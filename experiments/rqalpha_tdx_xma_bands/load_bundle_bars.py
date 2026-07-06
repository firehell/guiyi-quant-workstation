"""从 RQAlpha Plus bundle 读取 JM88 期货日线 OHLCV。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

BUNDLE = Path.home() / ".rqalpha-plus" / "bundle"
FUTURES_H5 = BUNDLE / "futures.h5"
DEFAULT_SYMBOL = "JM88"


@dataclass
class BarSeries:
    datetimes: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray


def _parse_bundle_datetime(value: int | float | np.integer) -> datetime:
    text = str(int(value))
    if len(text) >= 14:
        return datetime.strptime(text[:14], "%Y%m%d%H%M%S")
    return datetime.strptime(text[:8], "%Y%m%d")


def _to_bundle_date_int(dt: datetime) -> int:
    return int(dt.strftime("%Y%m%d"))


def _parse_date_str(date_str: str) -> datetime:
    return datetime.strptime(date_str, "%Y-%m-%d")


def load_jm88_bars(
    start_date: str,
    end_date: str,
    *,
    symbol: str = DEFAULT_SYMBOL,
    warmup_bars: int = 120,
    bundle_path: Path | None = None,
) -> BarSeries:
    h5_path = bundle_path or FUTURES_H5
    if not h5_path.exists():
        raise FileNotFoundError(f"未找到 bundle: {h5_path}")

    try:
        import h5py
    except ImportError as exc:
        raise ImportError("请安装 h5py: pip install h5py") from exc

    start_dt = _parse_date_str(start_date)
    end_dt = _parse_date_str(end_date)
    warmup_start = start_dt - timedelta(days=int(warmup_bars * 1.6))

    with h5py.File(h5_path, "r") as handle:
        if symbol not in handle:
            raise KeyError(f"bundle 中无 {symbol}，请执行: rqsdk update-data --base")
        raw = handle[symbol][:]
        if len(raw) == 0:
            raise ValueError(f"{symbol} 无行情数据")

    datetimes: list[int] = []
    opens: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    volumes: list[float] = []

    end_int = _to_bundle_date_int(end_dt)
    warmup_int = _to_bundle_date_int(warmup_start)

    for row in raw:
        dt_int = int(row["datetime"])
        bar_dt = _parse_bundle_datetime(dt_int)
        bar_date_int = _to_bundle_date_int(bar_dt)
        if bar_date_int < warmup_int or bar_date_int > end_int:
            continue
        datetimes.append(bar_date_int)
        opens.append(float(row["open"]))
        highs.append(float(row["high"]))
        lows.append(float(row["low"]))
        closes.append(float(row["close"]))
        volumes.append(float(row["volume"]))

    if not datetimes:
        raise ValueError(f"{symbol} 在 {warmup_start.date()} ~ {end_date} 无数据")

    return BarSeries(
        datetimes=np.asarray(datetimes, dtype=int),
        open=np.asarray(opens, dtype=float),
        high=np.asarray(highs, dtype=float),
        low=np.asarray(lows, dtype=float),
        close=np.asarray(closes, dtype=float),
        volume=np.asarray(volumes, dtype=float),
    )
