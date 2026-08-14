"""Observation-only HTDY original XMA kernel.

The centered XMA used here reads future bars. It is excluded from ordinary and
formal consumers; a separate exact realtime observation policy may call it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Sequence

import numpy as np


INDICATOR_CODE = "huotian_dayou_original_v0"
INDICATOR_VERSION = "original-v0"
FUTURE_DEPENDENCY_HORIZON_BARS = 24
CONFIGURED_REPAINT_SCAN_ZONE_BARS = 27


@dataclass(frozen=True)
class HtdyOriginalResult:
    """Aligned, minimal original-HTDY observation result."""

    datetimes: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    zk1: np.ndarray
    zd1: np.ndarray
    zd2: np.ndarray
    yellow_candle: np.ndarray
    white_candle: np.ndarray
    buy_observation: np.ndarray
    sell_observation: np.ndarray
    observation_conflict: np.ndarray
    metadata: dict[str, Any]

    def normalized_payload(self) -> dict[str, Any]:
        """Return the stable 12-decimal/null payload used by the shared golden."""

        return {
            "bars": [
                {
                    "datetime": _scalar(self.datetimes[index]),
                    "open": _numeric(self.open[index]),
                    "high": _numeric(self.high[index]),
                    "low": _numeric(self.low[index]),
                    "close": _numeric(self.close[index]),
                    "volume": _numeric(self.volume[index]),
                }
                for index in range(len(self.datetimes))
            ],
            "outputs": {
                "zk1": _numeric_list(self.zk1),
                "zd1": _numeric_list(self.zd1),
                "zd2": _numeric_list(self.zd2),
                "yellow_candle": _bool_list(self.yellow_candle),
                "white_candle": _bool_list(self.white_candle),
                "buy_observation": _bool_list(self.buy_observation),
                "sell_observation": _bool_list(self.sell_observation),
                "observation_conflict": _bool_list(self.observation_conflict),
            },
            "metadata": {
                key: self.metadata[key]
                for key in (
                    "indicator_code",
                    "indicator_version",
                    "status",
                    "future_looking",
                    "repainting_accepted",
                    "historical_backtest_allowed",
                    "future_dependency_horizon_bars",
                    "configured_repaint_scan_zone_bars",
                    "xma_rule",
                    "xma6_oracle_status",
                )
            },
        }


def normalize_period(period: int) -> int:
    """Normalize XMA periods to a positive odd number."""

    value = int(period)
    if value <= 0:
        raise ValueError("period must be positive")
    return value + 1 if value % 2 == 0 else value


def xma(values: Sequence[float], period: int) -> np.ndarray:
    """Centered, clipped XMA that ignores non-finite values in its window."""

    array = _float_array(values, name="values")
    normalized = normalize_period(period)
    radius = (normalized - 1) // 2
    output = np.full(len(array), np.nan, dtype=float)
    for index in range(len(array)):
        window = array[max(0, index - radius) : min(len(array), index + radius + 1)]
        finite = window[np.isfinite(window)]
        if finite.size:
            output[index] = float(np.mean(finite))
    return output


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
    """Compute the frozen original HTDY observation subset over aligned bars."""

    dt = _datetime_array(datetimes)
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
    normalize_period(channel_period)
    if channel_period != 25:
        raise ValueError("channel_period must be exactly 25 for htdy original")

    xma_high = xma(xma(high_values, channel_period), channel_period)
    xma_low = xma(xma(low_values, channel_period), channel_period)
    width = xma_high - xma_low
    zk1 = xma_high + width
    zd1 = xma_low - width
    zd2 = _ema_finite(zd1, channel_period)

    body_high = np.maximum(open_values, close_values)
    body_low = np.minimum(open_values, close_values)
    yellow_candle = (
        ((zd1 > low_values) & (zd1 < high_values))
        | ((zd1 > body_low) & (zd1 < body_high))
        | (zd1 > high_values)
    )
    white_candle = (body_high > zk1) & (body_high > np.maximum(body_low, zk1))
    buy_observation = _new_third_consecutive(yellow_candle)
    sell_observation = _new_third_consecutive(white_candle)
    observation_conflict = buy_observation & sell_observation

    return HtdyOriginalResult(
        datetimes=dt,
        open=open_values,
        high=high_values,
        low=low_values,
        close=close_values,
        volume=volume_values,
        zk1=zk1,
        zd1=zd1,
        zd2=zd2,
        yellow_candle=yellow_candle,
        white_candle=white_candle,
        buy_observation=buy_observation,
        sell_observation=sell_observation,
        observation_conflict=observation_conflict,
        metadata=_metadata(),
    )


def htdy_original_source_sha256() -> str:
    """SHA-256 of this exact production module's bytes."""

    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _metadata() -> dict[str, Any]:
    return {
        "indicator_code": INDICATOR_CODE,
        "indicator_version": INDICATOR_VERSION,
        "status": "observation_only",
        "backtest_capable": False,
        "live_capable": False,
        "alert_capable": True,
        "auto_order": False,
        "future_looking": True,
        "repainting_accepted": True,
        "historical_backtest_allowed": False,
        "formal_historical_status": "rejected",
        "future_dependency_horizon_bars": FUTURE_DEPENDENCY_HORIZON_BARS,
        "configured_repaint_scan_zone_bars": CONFIGURED_REPAINT_SCAN_ZONE_BARS,
        "xma_rule": "symmetric_clipped_finite_mean; even_period_normalizes_to_next_odd",
        "channel_period": 25,
        "xma25_dependency": "single[-12,+12];double[-24,+24]",
        "xma6_dependency": "normalized_to_7;single[-3,+3]",
        "xma6_oracle_status": "externally_unresolved",
        "source_sha256": htdy_original_source_sha256(),
    }


def _ema_finite(values: np.ndarray, period: int) -> np.ndarray:
    output = np.full(len(values), np.nan, dtype=float)
    alpha = 2.0 / (period + 1)
    previous: float | None = None
    for index, value in enumerate(values):
        if not np.isfinite(value):
            continue
        previous = float(value) if previous is None else alpha * float(value) + (1.0 - alpha) * previous
        output[index] = previous
    return output


def _new_third_consecutive(flags: np.ndarray) -> np.ndarray:
    output = np.zeros(len(flags), dtype=bool)
    for index in range(2, len(flags)):
        output[index] = bool(flags[index] and flags[index - 1] and flags[index - 2] and not (flags[index - 3] if index >= 3 else False))
    return output


def _float_array(values: Sequence[float], *, name: str) -> np.ndarray:
    try:
        raw = np.asarray(values, dtype=object)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a one-dimensional numeric sequence") from exc
    if raw.ndim != 1:
        raise ValueError(f"{name} must be a one-dimensional numeric sequence")
    try:
        return raw.astype(float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a one-dimensional numeric sequence") from exc


def _datetime_array(values: Sequence[Any]) -> np.ndarray:
    try:
        array = np.asarray(values, dtype=object)
    except (TypeError, ValueError) as exc:
        raise ValueError("datetimes must be one-dimensional") from exc
    if array.ndim != 1 or any(isinstance(value, (list, tuple, np.ndarray)) for value in array):
        raise ValueError("datetimes must be one-dimensional")
    return array


def _require_same_length(**arrays: Sequence[Any]) -> None:
    lengths = {name: len(value) for name, value in arrays.items()}
    if len(set(lengths.values())) != 1:
        raise ValueError(f"input lengths must match: {lengths}")


def _numeric(value: Any) -> float | int | None:
    numeric = float(value)
    if not np.isfinite(numeric):
        return None
    rounded = round(numeric, 12)
    return int(rounded) if rounded.is_integer() else rounded


def _scalar(value: Any) -> Any:
    if isinstance(value, str):
        return value
    if isinstance(value, np.datetime64):
        if np.isnat(value):
            raise ValueError("datetime value must be JSON-serializable ISO-8601 text")
        return np.datetime_as_string(value, unit="auto")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        try:
            normalized = isoformat()
        except (TypeError, ValueError) as exc:
            raise ValueError("datetime value must be JSON-serializable ISO-8601 text") from exc
        if isinstance(normalized, str):
            return normalized
    raise ValueError("datetime value must be JSON-serializable ISO-8601 text")


def _numeric_list(values: np.ndarray) -> list[float | int | None]:
    return [_numeric(value) for value in values]


def _bool_list(values: np.ndarray) -> list[bool]:
    return [bool(value) for value in values]
