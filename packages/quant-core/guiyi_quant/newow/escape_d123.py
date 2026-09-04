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
    ma120_prior_closes: tuple[float, ...] = ()
    prior_var4: float | None = None
    physical_contract: str | None = None
    segment_id: str | None = None
    raw_var4_window: tuple[float, ...] = ()


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


def _smoothed_var4(
    rsv9: float,
    previous_var4: float | None,
    profile: NewowTrendProfile,
) -> float | None:
    n = profile.var4_smoothing_n
    m = profile.var4_smoothing_m
    if n <= 0 or m <= 0 or m > n:
        return None
    value = rsv9 if previous_var4 is None else (m * rsv9 + (n - m) * previous_var4) / n
    return value if isfinite(value) else None


def _valid_state(state: EscapeState, profile: NewowTrendProfile) -> bool:
    if profile.escape_formula == "newow_escape_d123_page_v2":
        return _valid_page_v2_state(state, profile)
    if state.raw_var4_window:
        return False
    windows = (
        state.closes,
        state.highs,
        state.lows,
        state.ma120_values,
        state.ma120_prior_closes,
    )
    if profile.ma120_period <= 0 or profile.ma120_slope_window <= 0:
        return False
    if len(state.closes) != len(state.highs) or len(state.closes) != len(state.lows):
        return False
    if not 0 <= state.history_count <= profile.ma120_period:
        return False
    if len(state.closes) != state.history_count:
        return False
    if (
        len(state.closes) > profile.ma120_period
        or len(state.ma120_values) > profile.ma120_slope_window
    ):
        return False
    if (
        state.ma120_values or state.ma120_prior_closes
    ) and state.history_count < profile.ma120_period:
        return False
    if not all(isfinite(value) for window in windows for value in window) or not all(
        value is None or isfinite(value)
        for value in (state.previous_rsv9, state.previous_var4, state.prior_var4)
    ):
        return False
    if state.history_count == 0:
        return (
            state.previous_rsv9 is None
            and state.previous_var4 is None
            and state.prior_var4 is None
        )
    if not isinstance(state.physical_contract, str) or not state.physical_contract:
        return False
    if not isinstance(state.segment_id, str) or not state.segment_id:
        return False
    if state.previous_rsv9 is None or state.previous_var4 is None:
        return False
    if state.history_count == profile.ma120_period:
        if not state.ma120_values:
            return False
        if len(state.ma120_prior_closes) != len(state.ma120_values) - 1:
            return False
        ma_source = state.ma120_prior_closes + state.closes
        for index, stored_ma in enumerate(state.ma120_values):
            close_window = ma_source[index : index + profile.ma120_period]
            expected_ma = sum(close_window) / profile.ma120_period
            if len(close_window) != profile.ma120_period or not isclose(
                stored_ma,
                expected_ma,
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                return False
    denominator = max(state.highs[-profile.var4_lookback :]) - min(
        state.lows[-profile.var4_lookback :]
    )
    if denominator < 0.0 or not isfinite(denominator):
        return False
    if denominator != 0.0:
        expected_rsv9 = (
            100.0
            * (state.closes[-1] - min(state.lows[-profile.var4_lookback :]))
            / denominator
        )
        if not isclose(
            state.previous_rsv9, expected_rsv9, rel_tol=1e-12, abs_tol=1e-12
        ):
            return False
    if state.history_count == 1 and state.prior_var4 is not None:
        return False
    if state.history_count > 1 and state.prior_var4 is None:
        return False
    expected_var4 = _smoothed_var4(state.previous_rsv9, state.prior_var4, profile)
    return expected_var4 is not None and isclose(
        state.previous_var4, expected_var4, rel_tol=1e-12, abs_tol=1e-12
    )


def _page_raw_var4(
    closes: tuple[float, ...],
    highs: tuple[float, ...],
    lows: tuple[float, ...],
    index: int,
    lookback: int,
) -> float | None:
    start = max(0, index - lookback + 1)
    low = min(lows[start : index + 1])
    high = max(highs[start : index + 1])
    denominator = high - low
    if denominator < 0.0 or not isfinite(denominator):
        return None
    value = 50.0 if denominator == 0.0 else (closes[index] - low) / denominator * 100.0
    return value if isfinite(value) else None


def _round4(value: float) -> float:
    """Match the page's four-decimal display arithmetic."""

    return float(f"{value:.4f}")


def _valid_page_v2_state(state: EscapeState, profile: NewowTrendProfile) -> bool:
    windows = (
        state.closes,
        state.highs,
        state.lows,
        state.ma120_values,
        state.ma120_prior_closes,
        state.raw_var4_window,
    )
    if profile.ma120_period <= 0 or profile.var4_lookback <= 0:
        return False
    if len(state.closes) != len(state.highs) or len(state.closes) != len(state.lows):
        return False
    if not 0 <= state.history_count <= profile.ma120_period:
        return False
    if len(state.closes) != state.history_count:
        return False
    if len(state.ma120_values) > 2 or len(state.ma120_prior_closes) > 1:
        return False
    if len(state.raw_var4_window) > 4:
        return False
    scalar_values = (state.previous_rsv9, state.previous_var4, state.prior_var4)
    if not all(isfinite(value) for window in windows for value in window) or not all(
        value is None or isfinite(value) for value in scalar_values
    ):
        return False
    if state.history_count == 0:
        return (
            not state.ma120_values
            and not state.ma120_prior_closes
            and not state.raw_var4_window
            and all(value is None for value in scalar_values)
            and state.physical_contract is None
            and state.segment_id is None
        )
    if not isinstance(state.physical_contract, str) or not state.physical_contract:
        return False
    if not isinstance(state.segment_id, str) or not state.segment_id:
        return False
    expected_raw_count = min(state.history_count, 4)
    expected_ma_count = min(state.history_count, 2)
    if (
        len(state.raw_var4_window) != expected_raw_count
        or len(state.ma120_values) != expected_ma_count
    ):
        return False
    current_z = sum(state.closes) / len(state.closes)
    if not isclose(state.ma120_values[-1], current_z, rel_tol=1e-12, abs_tol=1e-12):
        return False
    if state.history_count > 1:
        if state.history_count < profile.ma120_period or not state.ma120_prior_closes:
            previous_source = state.closes[:-1]
        else:
            previous_source = state.ma120_prior_closes + state.closes[:-1]
        previous_z = sum(previous_source) / len(previous_source)
        if not isclose(
            state.ma120_values[-2], previous_z, rel_tol=1e-12, abs_tol=1e-12
        ):
            return False
    expected_raw: list[float] = []
    raw_start = len(state.closes) - expected_raw_count
    for index in range(raw_start, len(state.closes)):
        raw = _page_raw_var4(
            state.closes, state.highs, state.lows, index, profile.var4_lookback
        )
        if raw is None:
            return False
        expected_raw.append(raw)
    if any(
        not isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12)
        for actual, expected in zip(state.raw_var4_window, expected_raw, strict=True)
    ):
        return False
    current_var4 = _round4(sum(expected_raw[-3:]) / min(len(expected_raw), 3))
    if state.previous_rsv9 is None or state.previous_var4 is None:
        return False
    if not isclose(state.previous_rsv9, expected_raw[-1], rel_tol=1e-12, abs_tol=1e-12):
        return False
    if not isclose(state.previous_var4, current_var4, rel_tol=1e-12, abs_tol=1e-12):
        return False
    if state.history_count == 1:
        return state.prior_var4 is None
    prior_raw = expected_raw[:-1][-3:]
    expected_prior_var4 = _round4(sum(prior_raw) / len(prior_raw))
    return state.prior_var4 is not None and isclose(
        state.prior_var4, expected_prior_var4, rel_tol=1e-12, abs_tol=1e-12
    )


def _slope(values: tuple[float, ...], denominator: float) -> float | None:
    if len(values) < 10 or not isfinite(denominator) or denominator == 0.0:
        return None
    slope = (
        float(
            np.polyfit(
                np.arange(len(values), dtype=float), np.asarray(values, dtype=float), 1
            )[0]
        )
        / denominator
    )
    return slope if isfinite(slope) else None


def _marker_id(
    bar: NewowDailyBar, kind: NewowMarkerType, profile: NewowTrendProfile
) -> str:
    source = "|".join(
        (
            "newow_trend_v1",
            profile.escape_formula,
            bar.physical_contract,
            kind.value,
            bar.bar_end.isoformat(),
        )
    )
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
    previous_ma120: float | None = None,
    previous_var4: float | None = None,
) -> NewowMainMarker:
    definitions = {
        NewowMarkerType.ESCAPE_D1: (
            "★S逃命",
            "newow-d1-red",
            300,
            95,
            EscapeSeverity.CRITICAL,
        ),
        NewowMarkerType.ESCAPE_D2: (
            "★S逃",
            "newow-d2-green",
            200,
            93,
            EscapeSeverity.WARNING,
        ),
        NewowMarkerType.ESCAPE_D3: (
            "★S跑",
            "newow-d3-blue",
            100,
            90,
            EscapeSeverity.BEAR_CONFIRMATION,
        ),
    }
    label, color, priority, level, severity = definitions[kind]
    close = float(bar.close)
    if profile.escape_formula == "newow_escape_d123_page_v2":
        trigger_facts = {
            "var4": var4,
            "var4_previous": previous_var4,
            "var3": slope,
            "ma120": ma120,
            "ma120_previous": previous_ma120,
            "ma120_ratio": (
                previous_ma120 / ma120
                if previous_ma120 is not None and ma120 != 0.0
                else None
            ),
            "high_low_ratio30": None if amplitude is None else amplitude + 1.0,
            "close_below_ma120": close < ma120,
        }
        price = bar.high
    else:
        trigger_facts = {
            "var4": var4,
            "var4_cross_level": level,
            "ma120": ma120,
            "ma120_deviation": (close - ma120) / ma120 if ma120 != 0.0 else None,
            "amplitude30": amplitude,
            "ma120_slope10": slope,
            "close_below_ma120": close < ma120,
        }
        price = bar.close
    return NewowMainMarker(
        marker_id=_marker_id(bar, kind, profile),
        marker_type=kind,
        bar_end=bar.bar_end,
        price=price,
        label=label,
        color_token=color,
        priority=priority,
        related_marker_ids=(),
        trigger_facts=trigger_facts,
        formula_version=profile.escape_formula,
        severity=severity,
    )


def _step_page_v2(
    state: EscapeState,
    bar: NewowDailyBar,
    profile: NewowTrendProfile,
) -> EscapeStepResult:
    close, high, low = (
        _finite_decimal(value) for value in (bar.close, bar.high, bar.low)
    )
    if close is None or high is None or low is None:
        return _unavailable()
    closes = (state.closes + (close,))[-profile.ma120_period :]
    highs = (state.highs + (high,))[-profile.ma120_period :]
    lows = (state.lows + (low,))[-profile.ma120_period :]
    raw = _page_raw_var4(closes, highs, lows, len(closes) - 1, profile.var4_lookback)
    if raw is None:
        return _unavailable()
    raw_window = (state.raw_var4_window + (raw,))[-4:]
    var4 = _round4(sum(raw_window[-3:]) / min(len(raw_window), 3))
    ma120 = sum(closes) / len(closes)
    ma_h5 = sum(highs[-5:]) / min(len(highs), 5)
    var3 = _round4((ma_h5 - ma120) / ma120)
    amplitude_low = min(lows[-30:])
    amplitude_high = max(highs[-30:])
    if amplitude_low <= 0.0:
        return _unavailable()
    amplitude = (amplitude_high - amplitude_low) / amplitude_low
    prior_closes = (
        (state.closes[0],) if state.history_count == profile.ma120_period else ()
    )
    ma_values = (state.ma120_values + (ma120,))[-2:]
    next_state = EscapeState(
        closes=closes,
        highs=highs,
        lows=lows,
        ma120_values=ma_values,
        previous_rsv9=raw,
        previous_var4=var4,
        history_count=min(state.history_count + 1, profile.ma120_period),
        ma120_prior_closes=prior_closes,
        prior_var4=state.previous_var4,
        physical_contract=bar.physical_contract,
        segment_id=bar.segment_id,
        raw_var4_window=raw_window,
    )
    previous_ma120 = state.ma120_values[-1] if state.ma120_values else None
    if (
        not bar.observation_eligible
        or state.previous_var4 is None
        or previous_ma120 is None
    ):
        return EscapeStepResult(next_state, ma120, var3, amplitude, raw, var4, ())
    hits: list[NewowMainMarker] = []
    if state.previous_var4 >= 95.0 and var4 < 95.0 and var3 > 0.3:
        hits.append(
            _marker(
                bar,
                NewowMarkerType.ESCAPE_D1,
                profile,
                var4=var4,
                ma120=ma120,
                slope=var3,
                amplitude=amplitude,
                previous_ma120=previous_ma120,
                previous_var4=state.previous_var4,
            )
        )
    if (
        state.previous_var4 >= 93.0
        and var4 < 93.0
        and amplitude > 0.10
        and previous_ma120 / ma120 > 0.997
    ):
        hits.append(
            _marker(
                bar,
                NewowMarkerType.ESCAPE_D2,
                profile,
                var4=var4,
                ma120=ma120,
                slope=var3,
                amplitude=amplitude,
                previous_ma120=previous_ma120,
                previous_var4=state.previous_var4,
            )
        )
    if (
        state.prior_var4 is not None
        and close < ma120
        and ma120 < previous_ma120
        and state.previous_var4 > 90.0
        and var4 < state.previous_var4
        and state.previous_var4 > state.prior_var4
    ):
        hits.append(
            _marker(
                bar,
                NewowMarkerType.ESCAPE_D3,
                profile,
                var4=var4,
                ma120=ma120,
                slope=var3,
                amplitude=amplitude,
                previous_ma120=previous_ma120,
                previous_var4=state.previous_var4,
            )
        )
    return EscapeStepResult(next_state, ma120, var3, amplitude, raw, var4, tuple(hits))


def escape_evaluation_ready(
    state: EscapeState,
    *,
    profile: NewowTrendProfile = NEWOW_TREND_D1_V1,
) -> bool:
    if not _valid_state(state, profile):
        return False
    if profile.escape_formula == "newow_escape_d123_page_v2":
        return state.history_count >= 3 and state.prior_var4 is not None
    return (
        state.history_count >= profile.ma120_period
        and len(state.ma120_values) >= profile.ma120_slope_window
        and state.previous_var4 is not None
    )


def step_escape_d123(
    state: EscapeState,
    bar: NewowDailyBar,
    *,
    profile: NewowTrendProfile = NEWOW_TREND_D1_V1,
) -> EscapeStepResult:
    """Advance one completed D1 bar without crossing a physical-contract segment."""
    identity = (state.physical_contract, state.segment_id)
    incoming = (bar.physical_contract, bar.segment_id)
    if not _valid_state(state, profile):
        return _unavailable()
    if identity != (None, None) and identity != incoming:
        state = initial_escape_state()
    if profile.escape_formula == "newow_escape_d123_page_v2":
        return _step_page_v2(state, bar, profile)
    close, high, low = (
        _finite_decimal(value) for value in (bar.close, bar.high, bar.low)
    )
    if close is None or high is None or low is None:
        return _unavailable()

    closes = (state.closes + (close,))[-profile.ma120_period :]
    highs = (state.highs + (high,))[-profile.ma120_period :]
    lows = (state.lows + (low,))[-profile.ma120_period :]
    lookback_highs, lookback_lows = (
        highs[-profile.var4_lookback :],
        lows[-profile.var4_lookback :],
    )
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
    var4 = _smoothed_var4(rsv9, state.previous_var4, profile)
    if var4 is None:
        return _unavailable()

    ma120 = (
        sum(closes) / profile.ma120_period
        if len(closes) == profile.ma120_period
        else None
    )
    ma_values = state.ma120_values
    prior_closes = state.ma120_prior_closes
    if ma120 is not None:
        if not isfinite(ma120):
            return _unavailable()
        if len(state.closes) == profile.ma120_period:
            prior_limit = profile.ma120_slope_window - 1
            prior_closes = (
                ()
                if prior_limit == 0
                else (prior_closes + (state.closes[0],))[-prior_limit:]
            )
        ma_values = (ma_values + (ma120,))[-profile.ma120_slope_window :]
    slope = _slope(ma_values, ma120) if ma120 is not None else None
    amplitude = None
    if len(highs) >= 30:
        amplitude_low, amplitude_high = min(lows[-30:]), max(highs[-30:])
        if (
            amplitude_low <= 0.0
            or not isfinite(amplitude_low)
            or not isfinite(amplitude_high)
        ):
            return _unavailable()
        amplitude = (amplitude_high - amplitude_low) / amplitude_low
        if not isfinite(amplitude):
            return _unavailable()

    next_state = EscapeState(
        closes=closes,
        highs=highs,
        lows=lows,
        ma120_values=ma_values,
        previous_rsv9=rsv9,
        previous_var4=var4,
        history_count=min(state.history_count + 1, profile.ma120_period),
        ma120_prior_closes=prior_closes,
        prior_var4=state.previous_var4,
        physical_contract=bar.physical_contract,
        segment_id=bar.segment_id,
    )
    if (
        not bar.observation_eligible
        or ma120 is None
        or slope is None
        or amplitude is None
        or state.previous_var4 is None
    ):
        return EscapeStepResult(next_state, ma120, slope, amplitude, rsv9, var4, ())
    cross95 = state.previous_var4 >= 95.0 and var4 < 95.0
    cross93 = state.previous_var4 >= 93.0 and var4 < 93.0
    cross90 = state.previous_var4 >= 90.0 and var4 < 90.0
    deviation = (close - ma120) / ma120 if ma120 != 0.0 else None
    flat_ma120 = abs(slope) < profile.ma120_flat_threshold or isclose(
        abs(slope),
        profile.ma120_flat_threshold,
        rel_tol=1e-12,
        abs_tol=1e-12,
    )
    falling_ma120 = slope < -profile.ma120_flat_threshold and not isclose(
        slope,
        -profile.ma120_flat_threshold,
        rel_tol=1e-12,
        abs_tol=1e-12,
    )
    hits: list[NewowMainMarker] = []
    if cross95 and close > ma120 and deviation is not None and deviation >= 0.30:
        hits.append(
            _marker(
                bar,
                NewowMarkerType.ESCAPE_D1,
                profile,
                var4=var4,
                ma120=ma120,
                slope=slope,
                amplitude=amplitude,
            )
        )
    if cross93 and amplitude > 0.10 and flat_ma120:
        hits.append(
            _marker(
                bar,
                NewowMarkerType.ESCAPE_D2,
                profile,
                var4=var4,
                ma120=ma120,
                slope=slope,
                amplitude=amplitude,
            )
        )
    if close < ma120 and falling_ma120 and cross90:
        hits.append(
            _marker(
                bar,
                NewowMarkerType.ESCAPE_D3,
                profile,
                var4=var4,
                ma120=ma120,
                slope=slope,
                amplitude=amplitude,
            )
        )
    return EscapeStepResult(
        next_state, ma120, slope, amplitude, rsv9, var4, tuple(hits)
    )


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
