"""Causal Web-observation kernel for the designed main-force mirror V0.

The six coloured states are an OHLCV-derived observation proxy, not measured
fund flow and not evidence that a specific participant entered or exited.
The ``caution`` event intentionally reproduces the provided TongDaXin logic:
``BARSLAST(HIGH = HHV(HIGH, 5)) < 10`` and fires only on that state's 0->1 edge.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sized
from typing import Any, Literal, Sequence

import numpy as np


INDICATOR_CODE = "main_force_mirror_v0"
INDICATOR_VERSION = "designed-v0"
MainForceMirrorState = Literal["entry", "wash", "pull_up", "distribute", "exit", "lure"]


@dataclass(frozen=True)
class MainForceMirrorResult:
    """Aligned observation result for the Web secondary pane."""

    datetimes: np.ndarray
    score: np.ndarray
    state: np.ndarray
    ready: np.ndarray
    caution: np.ndarray
    caution_level: np.ndarray
    flow: np.ndarray
    range_position: np.ndarray
    metadata: dict[str, Any]


def classify_main_force_mirror_state(
    range_position: float,
    flow: float,
    flow_delta: float,
    price_delta: float,
) -> MainForceMirrorState:
    """Map causal OHLCV proxy features to one of six observation states."""

    if not all(
        np.isfinite(value) for value in (range_position, flow, flow_delta, price_delta)
    ):
        raise ValueError("classification inputs must be finite")

    if flow < 0:
        if range_position >= 0.50 and price_delta > 0:
            return "lure"
        return "exit"

    if range_position < 0.45:
        if price_delta < 0 or flow_delta < 0:
            return "wash"
        return "entry"

    if price_delta >= 0 and flow_delta >= 0:
        return "pull_up"
    return "distribute"


def compute_main_force_mirror(
    datetimes: Sequence[Any],
    open_: Sequence[float],
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    volume: Sequence[float],
    *,
    volume_window: int = 20,
    flow_ema_period: int = 5,
    range_window: int = 20,
    caution_high_window: int = 5,
    caution_quiet_window: int = 10,
    flow_clip: float = 3.0,
    score_scale: float = 50.0,
    exit_lure_scale: float = 0.35,
    caution_level: float = 50.0,
) -> MainForceMirrorResult:
    """Compute the designed six-state observation and exact caution event."""

    dt = _object_array(datetimes, name="datetimes")
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
    _require_positive_int(volume_window, name="volume_window")
    _require_positive_int(flow_ema_period, name="flow_ema_period")
    _require_positive_int(range_window, name="range_window")
    _require_positive_int(caution_high_window, name="caution_high_window")
    _require_positive_int(caution_quiet_window, name="caution_quiet_window")
    if not np.isfinite(flow_clip) or flow_clip <= 0:
        raise ValueError("flow_clip must be positive and finite")
    if not np.isfinite(score_scale) or score_scale <= 0:
        raise ValueError("score_scale must be positive and finite")
    if not np.isfinite(exit_lure_scale) or not 0 < exit_lure_scale <= 1:
        raise ValueError("exit_lure_scale must be in (0, 1]")
    if not np.isfinite(caution_level) or caution_level <= 0:
        raise ValueError("caution_level must be positive and finite")

    count = len(close_values)
    score = np.full(count, np.nan, dtype=float)
    state = np.full(count, None, dtype=object)
    ready = np.zeros(count, dtype=bool)

    volume_mean = _rolling_mean(volume_values, volume_window)
    volume_ratio = np.full(count, np.nan, dtype=float)
    valid_volume = (
        np.isfinite(volume_mean) & (volume_mean > 0) & np.isfinite(volume_values)
    )
    volume_ratio[valid_volume] = np.clip(
        volume_values[valid_volume] / volume_mean[valid_volume],
        0.0,
        flow_clip,
    )

    price_range = high_values - low_values
    clv = np.zeros(count, dtype=float)
    valid_range = np.isfinite(price_range) & (price_range > 0)
    clv[valid_range] = (
        2.0 * close_values[valid_range]
        - high_values[valid_range]
        - low_values[valid_range]
    ) / price_range[valid_range]
    clv[~np.isfinite(clv)] = 0.0

    raw_flow = clv * volume_ratio
    flow = _ema_finite(raw_flow, flow_ema_period)
    rolling_high = _rolling_extreme(high_values, range_window, maximum=True)
    rolling_low = _rolling_extreme(low_values, range_window, maximum=False)
    range_position = np.full(count, np.nan, dtype=float)
    rolling_width = rolling_high - rolling_low
    valid_position = (
        np.isfinite(rolling_width) & (rolling_width > 0) & np.isfinite(close_values)
    )
    range_position[valid_position] = np.clip(
        (close_values[valid_position] - rolling_low[valid_position])
        / rolling_width[valid_position],
        0.0,
        1.0,
    )

    for index in range(1, count):
        if not all(
            np.isfinite(value)
            for value in (
                flow[index],
                flow[index - 1],
                range_position[index],
                close_values[index],
                close_values[index - 1],
            )
        ):
            continue
        flow_delta = float(flow[index] - flow[index - 1])
        price_delta = float(close_values[index] - close_values[index - 1])
        current_state = classify_main_force_mirror_state(
            float(range_position[index]),
            float(flow[index]),
            flow_delta,
            price_delta,
        )
        strength = min(abs(float(flow[index])) * score_scale, 100.0)
        if current_state in {"entry", "wash"}:
            signed_score = strength
        elif current_state in {"pull_up", "distribute"}:
            signed_score = -strength
        elif current_state == "exit":
            signed_score = strength * exit_lure_scale
        else:
            signed_score = -strength * exit_lure_scale
        score[index] = signed_score
        state[index] = current_state
        ready[index] = True

    short_high_event = _rolling_current_high_event(high_values, caution_high_window)
    recent_short_high = _rolling_any(short_high_event, caution_quiet_window)
    caution = np.zeros(count, dtype=bool)
    for index in range(count):
        previous = bool(recent_short_high[index - 1]) if index > 0 else False
        caution[index] = bool(recent_short_high[index] and not previous)
    caution_values = np.full(count, np.nan, dtype=float)
    caution_values[caution] = caution_level

    return MainForceMirrorResult(
        datetimes=dt,
        score=score,
        state=state,
        ready=ready,
        caution=caution,
        caution_level=caution_values,
        flow=flow,
        range_position=range_position,
        metadata={
            "indicator_code": INDICATOR_CODE,
            "indicator_version": INDICATOR_VERSION,
            "status": "observation_only",
            "future_looking": False,
            "repainting_risk": "none",
            "historical_backtest_allowed": False,
            "alert_capable": False,
            "auto_order": False,
            "interpretation": "structural_warning_not_measured_fund_flow",
            "caution_formula": "rising_edge(BARSLAST(HIGH=HHV(HIGH,5))<10)",
            "volume_window": volume_window,
            "flow_ema_period": flow_ema_period,
            "range_window": range_window,
            "flow_clip": flow_clip,
            "score_scale": score_scale,
            "exit_lure_scale": exit_lure_scale,
            "caution_level": caution_level,
        },
    )


def _rolling_current_high_event(values: np.ndarray, window: int) -> np.ndarray:
    output = np.zeros(len(values), dtype=bool)
    for index in range(window - 1, len(values)):
        current = values[index]
        segment = values[index - window + 1 : index + 1]
        if np.isfinite(current) and np.all(np.isfinite(segment)):
            output[index] = bool(current == np.max(segment))
    return output


def _rolling_any(values: np.ndarray, window: int) -> np.ndarray:
    output = np.zeros(len(values), dtype=bool)
    for index in range(len(values)):
        start = max(0, index - window + 1)
        output[index] = bool(np.any(values[start : index + 1]))
    return output


def _rolling_mean(values: np.ndarray, window: int) -> np.ndarray:
    output = np.full(len(values), np.nan, dtype=float)
    for index in range(window - 1, len(values)):
        segment = values[index - window + 1 : index + 1]
        if np.all(np.isfinite(segment)):
            output[index] = float(np.mean(segment))
    return output


def _rolling_extreme(values: np.ndarray, window: int, *, maximum: bool) -> np.ndarray:
    output = np.full(len(values), np.nan, dtype=float)
    reducer = np.max if maximum else np.min
    for index in range(window - 1, len(values)):
        segment = values[index - window + 1 : index + 1]
        if np.all(np.isfinite(segment)):
            output[index] = float(reducer(segment))
    return output


def _ema_finite(values: np.ndarray, period: int) -> np.ndarray:
    output = np.full(len(values), np.nan, dtype=float)
    alpha = 2.0 / (period + 1)
    previous: float | None = None
    for index, value in enumerate(values):
        if not np.isfinite(value):
            continue
        previous = (
            float(value)
            if previous is None
            else alpha * float(value) + (1.0 - alpha) * previous
        )
        output[index] = previous
    return output


def _float_array(values: Sequence[float], *, name: str) -> np.ndarray:
    raw = _object_array(values, name=name)
    try:
        return raw.astype(float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a one-dimensional numeric sequence") from exc


def _object_array(values: Sequence[Any], *, name: str) -> np.ndarray:
    try:
        array = np.asarray(values, dtype=object)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be one-dimensional") from exc
    if array.ndim != 1 or any(
        isinstance(value, (list, tuple, np.ndarray)) for value in array
    ):
        raise ValueError(f"{name} must be one-dimensional")
    return array


def _require_same_length(**arrays: Sized) -> None:
    lengths = {name: len(value) for name, value in arrays.items()}
    if len(set(lengths.values())) != 1:
        raise ValueError(f"input lengths must match: {lengths}")


def _require_positive_int(value: int, *, name: str) -> None:
    if isinstance(value, bool) or int(value) != value or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
