from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from math import isclose, isfinite

from .models import (
    NewowDailyBar,
    NewowMainMarker,
    NewowMarkerType,
    NewowTrendBandPoint,
    TrendBandState,
    TrendTransition,
)
from .profile import NEWOW_TREND_D1_V1, NewowTrendProfile


@dataclass(frozen=True, slots=True)
class TrendBandStateValue:
    weighted_window: tuple[float, ...]
    signal_window: tuple[float, ...]
    previous_state: TrendBandState | None
    last_build_close: Decimal | None = None
    last_build_marker_id: str | None = None
    physical_contract: str | None = None
    segment_id: str | None = None


@dataclass(frozen=True, slots=True)
class TrendBandStepResult:
    state: TrendBandStateValue
    point: NewowTrendBandPoint
    marker: NewowMainMarker | None


def initial_trend_band_state() -> TrendBandStateValue:
    return TrendBandStateValue((), (), None)


def _typical_price(bar: NewowDailyBar, profile: NewowTrendProfile) -> float | None:
    if not all(value.is_finite() for value in (bar.open, bar.high, bar.low, bar.close)):
        return None
    close_weight = profile.typical_price_close_weight
    denominator = close_weight + 3.0
    if not isfinite(close_weight) or not isfinite(denominator) or denominator == 0.0:
        return None
    value = (
        close_weight * float(bar.close)
        + float(bar.open)
        + float(bar.high)
        + float(bar.low)
    ) / denominator
    return value if isfinite(value) else None


def _valid_state(state: TrendBandStateValue, profile: NewowTrendProfile) -> bool:
    weighted_count = len(state.weighted_window)
    signal_count = len(state.signal_window)
    if profile.trend_weight_period <= 0 or profile.trend_signal_period <= 0:
        return False
    if weighted_count > profile.trend_weight_period or signal_count > profile.trend_signal_period:
        return False
    if not all(
        isfinite(value) and value > 0.0
        for value in state.weighted_window + state.signal_window
    ):
        return False

    has_history = bool(
        weighted_count
        or signal_count
        or state.previous_state is not None
        or state.last_build_close is not None
        or state.last_build_marker_id is not None
    )
    if has_history and (
        not isinstance(state.physical_contract, str)
        or not state.physical_contract
        or not isinstance(state.segment_id, str)
        or not state.segment_id
    ):
        return False

    has_build_close = state.last_build_close is not None
    has_build_marker = state.last_build_marker_id is not None
    if has_build_close != has_build_marker:
        return False
    if has_build_close and (
        not isinstance(state.last_build_close, Decimal)
        or not state.last_build_close.is_finite()
        or state.last_build_close <= 0
        or not isinstance(state.last_build_marker_id, str)
        or not state.last_build_marker_id
    ):
        return False

    if weighted_count < profile.trend_weight_period:
        return signal_count == 0 and state.previous_state is None and not has_build_close
    if signal_count == 0:
        return False
    expected_b = sum(
        (index + 1) * value for index, value in enumerate(state.weighted_window)
    ) / sum(range(1, profile.trend_weight_period + 1))
    if not isclose(state.signal_window[-1], expected_b, rel_tol=1e-12, abs_tol=1e-12):
        return False
    if signal_count < profile.trend_signal_period:
        return state.previous_state is None and not has_build_close
    if state.previous_state not in (TrendBandState.YELLOW, TrendBandState.BLUE):
        return False
    expected_state = (
        TrendBandState.YELLOW
        if state.signal_window[-1] >= sum(state.signal_window) / profile.trend_signal_period
        else TrendBandState.BLUE
    )
    return state.previous_state is expected_state


def _marker_id(bar: NewowDailyBar, marker_type: NewowMarkerType, profile: NewowTrendProfile) -> str:
    value = "|".join(
        (
            "newow_trend_v1",
            profile.trend_band_formula,
            bar.physical_contract,
            marker_type.value,
            bar.bar_end.isoformat(),
        )
    )
    return sha256(value.encode()).hexdigest()


def _marker(
    bar: NewowDailyBar,
    marker_type: NewowMarkerType,
    profile: NewowTrendProfile,
    state: TrendBandStateValue,
    state_before: TrendBandState,
    state_after: TrendBandState,
    reference_change_pct: float | None = None,
) -> NewowMainMarker:
    marker_id = _marker_id(bar, marker_type, profile)
    if marker_type is NewowMarkerType.BUILD:
        return NewowMainMarker(
            marker_id=marker_id,
            marker_type=marker_type,
            bar_end=bar.bar_end,
            price=bar.close,
            label="建仓 / 建仓价:{}\n策略信号参考变化\n非真实成交\n未计手续费、滑点、涨跌停和换月".format(bar.close),
            color_token="newow-yellow",
            priority=100,
            related_marker_ids=(),
            trigger_facts={
                "state_before": state_before.value,
                "state_after": state_after.value,
                "signal_close": bar.close,
                "reference_basis": "signal_close",
                "reference_change_pct": None,
            },
            formula_version=profile.trend_band_formula,
        )
    return NewowMainMarker(
        marker_id=marker_id,
        marker_type=marker_type,
        bar_end=bar.bar_end,
        price=bar.close,
        label=(
            "清仓 / {}({:+.2f}%)\n策略信号参考变化\n非真实成交\n未计手续费、滑点、涨跌停和换月".format(
                bar.close, reference_change_pct
            )
            if reference_change_pct is not None
            else "清仓 / {}\n策略信号参考变化\n非真实成交\n未计手续费、滑点、涨跌停和换月".format(bar.close)
        ),
        color_token="newow-blue",
        priority=100,
        related_marker_ids=()
        if state.last_build_marker_id is None
        else (state.last_build_marker_id,),
        trigger_facts={
            "state_before": state_before.value,
            "state_after": state_after.value,
            "signal_close": bar.close,
            "reference_basis": "signal_close",
            "reference_change_pct": reference_change_pct,
        },
        formula_version=profile.trend_band_formula,
    )


def _unavailable_result(bar: NewowDailyBar) -> TrendBandStepResult:
    return TrendBandStepResult(
        state=initial_trend_band_state(),
        point=NewowTrendBandPoint(
            bar_end=bar.bar_end,
            b_value=None,
            c_value=None,
            state=TrendBandState.UNAVAILABLE,
            state_before=None,
        ),
        marker=None,
    )


def _next_state(
    bar: NewowDailyBar,
    weighted_window: tuple[float, ...],
    signal_window: tuple[float, ...],
    previous_state: TrendBandState | None,
    last_build_close: Decimal | None,
    last_build_marker_id: str | None,
) -> TrendBandStateValue:
    return TrendBandStateValue(
        weighted_window,
        signal_window,
        previous_state,
        last_build_close,
        last_build_marker_id,
        bar.physical_contract,
        bar.segment_id,
    )


def _clear_reference_change_pct(bar: NewowDailyBar, state: TrendBandStateValue) -> float | None:
    reference = state.last_build_close
    if not isinstance(reference, Decimal) or not reference.is_finite() or reference.is_zero():
        return None
    reference_value = float(reference)
    close_value = float(bar.close)
    if not isfinite(reference_value) or not isfinite(close_value):
        return None
    value = (close_value / reference_value - 1.0) * 100.0
    return value if isfinite(value) else None


def step_trend_band(
    state: TrendBandStateValue,
    bar: NewowDailyBar,
    *,
    profile: NewowTrendProfile = NEWOW_TREND_D1_V1,
) -> TrendBandStepResult:
    if not _valid_state(state, profile):
        return _unavailable_result(bar)
    identity = (state.physical_contract, state.segment_id)
    incoming_identity = (bar.physical_contract, bar.segment_id)
    if identity != (None, None) and identity != incoming_identity:
        if identity[0] is None or identity[1] is None:
            return _unavailable_result(bar)
        state = initial_trend_band_state()
    typical = _typical_price(bar, profile)
    if typical is None:
        return _unavailable_result(bar)

    weighted_window = (state.weighted_window + (typical,))[-profile.trend_weight_period :]
    if len(weighted_window) < profile.trend_weight_period:
        return TrendBandStepResult(
            state=_next_state(
                bar,
                weighted_window,
                state.signal_window,
                state.previous_state,
                state.last_build_close,
                state.last_build_marker_id,
            ),
            point=NewowTrendBandPoint(bar.bar_end, None, None, TrendBandState.UNAVAILABLE, state.previous_state),
            marker=None,
        )

    b_value = sum((index + 1) * value for index, value in enumerate(weighted_window)) / sum(
        range(1, profile.trend_weight_period + 1)
    )
    if not isfinite(b_value):
        return _unavailable_result(bar)
    signal_window = (state.signal_window + (b_value,))[-profile.trend_signal_period :]
    if len(signal_window) < profile.trend_signal_period:
        return TrendBandStepResult(
            state=_next_state(
                bar,
                weighted_window,
                signal_window,
                state.previous_state,
                state.last_build_close,
                state.last_build_marker_id,
            ),
            point=NewowTrendBandPoint(bar.bar_end, b_value, None, TrendBandState.UNAVAILABLE, state.previous_state),
            marker=None,
        )

    c_value = sum(signal_window) / profile.trend_signal_period
    if not isfinite(c_value):
        return _unavailable_result(bar)
    current_state = TrendBandState.YELLOW if b_value >= c_value else TrendBandState.BLUE
    state_before = state.previous_state
    transition = None
    marker = None
    if bar.observation_eligible and state_before is not None and current_state is not state_before:
        if current_state is TrendBandState.YELLOW:
            transition = TrendTransition.BUILD
            marker = _marker(
                bar, NewowMarkerType.BUILD, profile, state, state_before, TrendBandState.YELLOW
            )
        elif state.last_build_marker_id is not None:
            reference_change_pct = _clear_reference_change_pct(bar, state)
            if reference_change_pct is None:
                return _unavailable_result(bar)
            transition = TrendTransition.CLEAR
            marker = _marker(
                bar,
                NewowMarkerType.CLEAR,
                profile,
                state,
                state_before,
                TrendBandState.BLUE,
                reference_change_pct,
            )
    next_build_close = state.last_build_close
    next_build_marker_id = state.last_build_marker_id
    if marker is not None and marker.marker_type is NewowMarkerType.BUILD:
        next_build_close = bar.close
        next_build_marker_id = marker.marker_id
    return TrendBandStepResult(
        state=_next_state(
            bar,
            weighted_window,
            signal_window,
            current_state,
            next_build_close,
            next_build_marker_id,
        ),
        point=NewowTrendBandPoint(bar.bar_end, b_value, c_value, current_state, state_before, transition),
        marker=marker,
    )


def calculate_trend_band(
    bars: tuple[NewowDailyBar, ...],
    *,
    profile: NewowTrendProfile = NEWOW_TREND_D1_V1,
) -> tuple[NewowTrendBandPoint, ...]:
    state = initial_trend_band_state()
    points = []
    for bar in bars:
        result = step_trend_band(state, bar, profile=profile)
        points.append(result.point)
        state = result.state
    return tuple(points)
