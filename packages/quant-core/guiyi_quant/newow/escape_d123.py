"""Bounded, causal D1/D2/D3 escape calculations for the Newow D1 profile."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from math import isclose, isfinite

import numpy as np

from .models import EscapeSeverity, NewowDailyBar, NewowMainMarker, NewowMarkerType
from .profile import NEWOW_TREND_D1_V1, NewowTrendProfile


@dataclass(frozen=True, slots=True)
class EscapeState:
    closes: tuple[float, ...]
    highs: tuple[float, ...]
    lows: tuple[float, ...]
    ma120_values: tuple[float, ...]
    previous_rsv9: float | None
    previous_var4: float | None
    history_count: int = 0
    prior_var4: float | None = None
    physical_contract: str | None = None
    segment_id: str | None = None


@dataclass(frozen=True, slots=True)
class EscapeStepResult:
    state: EscapeState
    ma120: float | None
    ma120_slope10: float | None
    amplitude30: float | None
    rsv9: float | None
    var4: float | None
    markers: tuple[NewowMainMarker, ...]


def initial_escape_state() -> EscapeState:
    return EscapeState((), (), (), (), None, None)


def _unavailable() -> EscapeStepResult:
    return EscapeStepResult(initial_escape_state(), None, None, None, None, None, ())


def _finite_decimal(value: Decimal) -> float | None:
    if not value.is_finite():
        return None
    numeric = float(value)
    return numeric if isfinite(numeric) else None


def _valid_state(state: EscapeState, profile: NewowTrendProfile) -> bool:
    windows = (state.closes, state.highs, state.lows, state.ma120_values)
    if len(state.closes) != len(state.highs) or len(state.closes) != len(state.lows):
        return False
    if not 0 <= state.history_count <= profile.ma120_period:
        return False
    if len(state.closes) != state.history_count:
        return False
    if len(state.closes) > profile.ma120_period or len(state.ma120_values) > profile.ma120_slope_window:
        return False
    if state.ma120_values and state.history_count < profile.ma120_period:
        return False
    if not all(isfinite(value) for window in windows for value in window) or not all(
        value is None or isfinite(value) for value in (state.previous_rsv9, state.previous_var4, state.prior_var4)
    ):
        return False
    if state.history_count == 0:
        return state.previous_rsv9 is None and state.previous_var4 is None and state.prior_var4 is None
    if state.previous_rsv9 is None or state.previous_var4 is None:
        return False
    denominator = max(state.highs[-profile.var4_lookback :]) - min(state.lows[-profile.var4_lookback :])
    if denominator < 0.0 or not isfinite(denominator):
        return False
    if denominator != 0.0:
        expected_rsv9 = 100.0 * (state.closes[-1] - min(state.lows[-profile.var4_lookback :])) / denominator
        if not isclose(state.previous_rsv9, expected_rsv9, rel_tol=1e-12, abs_tol=1e-12):
            return False
    if state.history_count == 1:
        return state.prior_var4 is None and isclose(state.previous_var4, state.previous_rsv9, rel_tol=1e-12, abs_tol=1e-12)
    if state.prior_var4 is None:
        return False
    return isclose(
        state.previous_var4,
        (state.previous_rsv9 + 2.0 * state.prior_var4) / 3.0,
        rel_tol=1e-12,
        abs_tol=1e-12,
    )


def _slope(values: tuple[float, ...], denominator: float) -> float | None:
    if len(values) < 10 or not isfinite(denominator) or denominator == 0.0:
        return None
    slope = float(np.polyfit(np.arange(len(values), dtype=float), np.asarray(values, dtype=float), 1)[0]) / denominator
    return slope if isfinite(slope) else None


def _marker_id(bar: NewowDailyBar, kind: NewowMarkerType, profile: NewowTrendProfile) -> str:
    source = "|".join(("newow_trend_v1", profile.escape_formula, bar.physical_contract, kind.value, bar.bar_end.isoformat()))
    return sha256(source.encode()).hexdigest()


def _marker(
    bar: NewowDailyBar,
    kind: NewowMarkerType,
    profile: NewowTrendProfile,
    *,
    var4: float,
    ma120: float,
    slope: float | None,
    amplitude: float | None,
) -> NewowMainMarker:
    definitions = {
        NewowMarkerType.ESCAPE_D1: ("★S逃命", "newow-d1-red", 300, 95, EscapeSeverity.CRITICAL),
        NewowMarkerType.ESCAPE_D2: ("★S逃", "newow-d2-green", 200, 93, EscapeSeverity.WARNING),
        NewowMarkerType.ESCAPE_D3: ("★S跑", "newow-d3-blue", 100, 90, EscapeSeverity.BEAR_CONFIRMATION),
    }
    label, color, priority, level, severity = definitions[kind]
    close = float(bar.close)
    return NewowMainMarker(
        marker_id=_marker_id(bar, kind, profile), marker_type=kind, bar_end=bar.bar_end,
        price=bar.close, label=label, color_token=color, priority=priority, related_marker_ids=(),
        trigger_facts={
            "var4": var4,
            "var4_cross_level": level,
            "ma120": ma120,
            "ma120_deviation": (close - ma120) / ma120 if ma120 != 0.0 else None,
            "amplitude30": amplitude,
            "ma120_slope10": slope,
            "close_below_ma120": close < ma120,
        }, formula_version=profile.escape_formula, severity=severity,
    )


def step_escape_d123(
    state: EscapeState, bar: NewowDailyBar, *, profile: NewowTrendProfile = NEWOW_TREND_D1_V1
) -> EscapeStepResult:
    """Advance one completed D1 bar without crossing a physical-contract segment."""
    identity = (state.physical_contract, state.segment_id)
    incoming = (bar.physical_contract, bar.segment_id)
    if identity != (None, None) and identity != incoming:
        state = initial_escape_state()
    if not _valid_state(state, profile):
        return _unavailable()
    close, high, low = (_finite_decimal(value) for value in (bar.close, bar.high, bar.low))
    if close is None or high is None or low is None:
        return _unavailable()

    closes = (state.closes + (close,))[-profile.ma120_period :]
    highs = (state.highs + (high,))[-profile.ma120_period :]
    lows = (state.lows + (low,))[-profile.ma120_period :]
    lookback_highs, lookback_lows = highs[-profile.var4_lookback :], lows[-profile.var4_lookback :]
    llv, hhv = min(lookback_lows), max(lookback_highs)
    denominator = hhv - llv
    if not isfinite(denominator) or denominator < 0.0:
        return _unavailable()
    if denominator == 0.0:
        rsv9 = state.previous_rsv9 if state.previous_rsv9 is not None else 50.0
    else:
        rsv9 = 100.0 * (close - llv) / denominator
    if not isfinite(rsv9):
        return _unavailable()
    var4 = rsv9 if state.previous_var4 is None else (rsv9 + 2.0 * state.previous_var4) / 3.0
    if not isfinite(var4):
        return _unavailable()

    ma120 = sum(closes) / profile.ma120_period if len(closes) == profile.ma120_period else None
    ma_values = state.ma120_values
    if ma120 is not None:
        if not isfinite(ma120):
            return _unavailable()
        ma_values = (ma_values + (ma120,))[-profile.ma120_slope_window :]
    slope = _slope(ma_values, ma120) if ma120 is not None else None
    amplitude = None
    if len(highs) >= 30:
        amplitude_low, amplitude_high = min(lows[-30:]), max(highs[-30:])
        if amplitude_low <= 0.0 or not isfinite(amplitude_low) or not isfinite(amplitude_high):
            return _unavailable()
        amplitude = (amplitude_high - amplitude_low) / amplitude_low
        if not isfinite(amplitude):
            return _unavailable()

    next_state = EscapeState(
        closes, highs, lows, ma_values, rsv9, var4, min(state.history_count + 1, profile.ma120_period),
        state.previous_var4, bar.physical_contract, bar.segment_id,
    )
    if not bar.observation_eligible or ma120 is None or slope is None or amplitude is None or state.previous_var4 is None:
        return EscapeStepResult(next_state, ma120, slope, amplitude, rsv9, var4, ())
    cross95 = state.previous_var4 >= 95.0 and var4 < 95.0
    cross93 = state.previous_var4 >= 93.0 and var4 < 93.0
    cross90 = state.previous_var4 >= 90.0 and var4 < 90.0
    deviation = (close - ma120) / ma120 if ma120 != 0.0 else None
    hits: list[NewowMainMarker] = []
    if cross95 and close > ma120 and deviation is not None and deviation >= 0.30:
        hits.append(_marker(bar, NewowMarkerType.ESCAPE_D1, profile, var4=var4, ma120=ma120, slope=slope, amplitude=amplitude))
    if cross93 and amplitude > 0.10 and abs(slope) <= profile.ma120_flat_threshold:
        hits.append(_marker(bar, NewowMarkerType.ESCAPE_D2, profile, var4=var4, ma120=ma120, slope=slope, amplitude=amplitude))
    if close < ma120 and slope < -profile.ma120_flat_threshold and cross90:
        hits.append(_marker(bar, NewowMarkerType.ESCAPE_D3, profile, var4=var4, ma120=ma120, slope=slope, amplitude=amplitude))
    return EscapeStepResult(next_state, ma120, slope, amplitude, rsv9, var4, tuple(hits))


def calculate_escape_series(
    bars: tuple[NewowDailyBar, ...], *, profile: NewowTrendProfile = NEWOW_TREND_D1_V1
) -> tuple[EscapeStepResult, ...]:
    state = initial_escape_state()
    results: list[EscapeStepResult] = []
    for bar in bars:
        result = step_escape_d123(state, bar, profile=profile)
        results.append(result)
        state = result.state
    return tuple(results)
