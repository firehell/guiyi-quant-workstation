"""The sole pure incremental orchestrator for completed Newow D1 observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from .cup_handle import (
    CupHandleStateValue,
    _state_is_valid as _cup_state_is_valid,
    initial_cup_handle_state,
    step_cup_handle,
)
from .escape_d123 import (
    EscapeState,
    _valid_state as _escape_state_is_valid,
    initial_escape_state,
    step_escape_d123,
)
from .models import (
    NewowDailyBar,
    NewowMainMarker,
    NewowMarkerType,
    NewowTrendBandPoint,
    NewowTrendFrame,
    TrendBandState,
)
from .profile import NEWOW_TREND_D1_V1, NewowTrendProfile
from .trend_band import (
    TrendBandStateValue,
    _typical_price as _trend_typical_price,
    _valid_state as _trend_band_state_is_valid,
    initial_trend_band_state,
    step_trend_band,
)


@dataclass(frozen=True, slots=True)
class NewowTrendD1EngineState:
    trend_band_state: TrendBandStateValue
    escape_state: EscapeState
    cup_handle_state: CupHandleStateValue
    physical_contract: str | None
    segment_id: str | None
    last_bar_end: datetime | None
    last_trading_day: date | None
    eligibility_started: bool


@dataclass(frozen=True, slots=True)
class NewowTrendD1StepResult:
    state: NewowTrendD1EngineState
    frame: NewowTrendFrame


def _initial_state() -> NewowTrendD1EngineState:
    return NewowTrendD1EngineState(
        trend_band_state=initial_trend_band_state(),
        escape_state=initial_escape_state(),
        cup_handle_state=initial_cup_handle_state(),
        physical_contract=None,
        segment_id=None,
        last_bar_end=None,
        last_trading_day=None,
        eligibility_started=False,
    )


def _identity_is_valid(
    physical_contract: str | None, segment_id: str | None
) -> bool:
    return (physical_contract is None and segment_id is None) or (
        isinstance(physical_contract, str)
        and bool(physical_contract)
        and isinstance(segment_id, str)
        and bool(segment_id)
    )


def _state_is_valid(state: object, profile: NewowTrendProfile) -> bool:
    if not isinstance(state, NewowTrendD1EngineState):
        return False
    if not _identity_is_valid(state.physical_contract, state.segment_id):
        return False
    if not isinstance(state.eligibility_started, bool):
        return False
    if (state.last_bar_end is None) != (state.last_trading_day is None):
        return False
    if state.last_bar_end is not None and (
        not isinstance(state.last_bar_end, datetime)
        or state.last_bar_end.tzinfo is None
        or state.last_bar_end.utcoffset() is None
    ):
        return False
    if state.last_trading_day is not None and (
        not isinstance(state.last_trading_day, date)
        or isinstance(state.last_trading_day, datetime)
    ):
        return False
    try:
        valid_substates = (
            _trend_band_state_is_valid(state.trend_band_state, profile)
            and _escape_state_is_valid(state.escape_state, profile)
            and _cup_state_is_valid(state.cup_handle_state, profile)
        )
    except (ArithmeticError, AttributeError, LookupError, TypeError, ValueError):
        return False
    if not valid_substates:
        return False

    identities = (
        (state.trend_band_state.physical_contract, state.trend_band_state.segment_id),
        (state.escape_state.physical_contract, state.escape_state.segment_id),
        (state.cup_handle_state.physical_contract, state.cup_handle_state.segment_id),
    )
    engine_identity = (state.physical_contract, state.segment_id)
    if engine_identity == (None, None):
        return (
            state.last_bar_end is None
            and state.last_trading_day is None
            and not state.eligibility_started
            and all(identity == (None, None) for identity in identities)
        )
    return (
        state.last_bar_end is not None
        and state.last_trading_day is not None
        and all(identity == engine_identity for identity in identities)
        and state.eligibility_started == state.cup_handle_state.eligible_started
        and _substate_history_is_coherent(state, profile)
    )


def _substate_history_is_coherent(
    state: NewowTrendD1EngineState, profile: NewowTrendProfile
) -> bool:
    """Require shared retained market facts, not caller-supplied provenance claims."""

    processed_count = state.cup_handle_state.atr_state.count
    if processed_count <= 0:
        return False
    expected_escape_count = min(processed_count, profile.ma120_period)
    expected_weighted_count = min(processed_count, profile.trend_weight_period)
    expected_signal_count = min(
        max(processed_count - profile.trend_weight_period + 1, 0),
        profile.trend_signal_period,
    )
    if (
        state.escape_state.history_count != expected_escape_count
        or len(state.trend_band_state.weighted_window) != expected_weighted_count
        or len(state.trend_band_state.signal_window) != expected_signal_count
    ):
        return False
    if not state.eligibility_started:
        return True
    snapshots = state.cup_handle_state.eligible_bars
    if not snapshots:
        return processed_count < profile.cup_atr_period
    latest_bar = snapshots[-1].bar
    latest_matches = (
        latest_bar.bar_end == state.last_bar_end
        and latest_bar.trading_day == state.last_trading_day
        and latest_bar.physical_contract == state.physical_contract
        and latest_bar.segment_id == state.segment_id
    )
    if not latest_matches:
        return False

    typical_values = tuple(
        _trend_typical_price(snapshot.bar, profile) for snapshot in snapshots
    )
    if any(value is None for value in typical_values):
        return False
    actual_typicals = tuple(value for value in typical_values if value is not None)
    trend_overlap = min(
        len(state.trend_band_state.weighted_window), len(actual_typicals)
    )
    if trend_overlap and state.trend_band_state.weighted_window[-trend_overlap:] != actual_typicals[-trend_overlap:]:
        return False

    expected_signal: list[float] = []
    for end in range(profile.trend_weight_period - 1, len(snapshots)):
        window = snapshots[end - profile.trend_weight_period + 1 : end + 1]
        if any(
            right.eligible_index != left.eligible_index + 1
            for left, right in zip(window, window[1:])
        ):
            continue
        values = actual_typicals[
            end - profile.trend_weight_period + 1 : end + 1
        ]
        expected_signal.append(
            sum((index + 1) * value for index, value in enumerate(values))
            / sum(range(1, profile.trend_weight_period + 1))
        )
    signal_overlap = min(len(state.trend_band_state.signal_window), len(expected_signal))
    if signal_overlap and state.trend_band_state.signal_window[-signal_overlap:] != tuple(expected_signal[-signal_overlap:]):
        return False

    escape_overlap = min(len(snapshots), len(state.escape_state.closes))
    if not escape_overlap:
        return True
    recent_bars = tuple(snapshot.bar for snapshot in snapshots[-escape_overlap:])
    return (
        state.escape_state.closes[-escape_overlap:]
        == tuple(float(bar.close) for bar in recent_bars)
        and state.escape_state.highs[-escape_overlap:]
        == tuple(float(bar.high) for bar in recent_bars)
        and state.escape_state.lows[-escape_overlap:]
        == tuple(float(bar.low) for bar in recent_bars)
    )


def _unavailable_frame(bar: NewowDailyBar) -> NewowTrendFrame:
    return NewowTrendFrame(
        bar=bar,
        trend_band=NewowTrendBandPoint(
            bar_end=bar.bar_end,
            b_value=None,
            c_value=None,
            state=TrendBandState.UNAVAILABLE,
            state_before=None,
        ),
        markers=(),
        cup_handle=None,
        diagnostics=("NEWOW_ENGINE_STATE_INVALID",),
    )


_ESCAPE_ORDER = {
    NewowMarkerType.ESCAPE_D1: 0,
    NewowMarkerType.ESCAPE_D2: 1,
    NewowMarkerType.ESCAPE_D3: 2,
}
_CUP_ORDER = {
    NewowMarkerType.CUP_HANDLE_READY: 0,
    NewowMarkerType.CUP_HANDLE_BREAKOUT: 1,
    NewowMarkerType.CUP_HANDLE_WEAKENED: 2,
    NewowMarkerType.CUP_HANDLE_INVALIDATED: 3,
    NewowMarkerType.CUP_HANDLE_EXPIRED: 4,
}


def _ordered_markers(
    trend_marker: NewowMainMarker | None,
    escape_markers: tuple[NewowMainMarker, ...],
    cup_markers: tuple[NewowMainMarker, ...],
) -> tuple[NewowMainMarker, ...]:
    trend = () if trend_marker is None else (trend_marker,)
    ordered_trend = tuple(
        sorted(trend, key=lambda marker: (marker.marker_type.value, marker.marker_id))
    )
    ordered_escape = tuple(
        sorted(
            escape_markers,
            key=lambda marker: (
                _ESCAPE_ORDER[marker.marker_type],
                marker.marker_type.value,
                marker.marker_id,
            ),
        )
    )
    ordered_cup = tuple(
        sorted(
            cup_markers,
            key=lambda marker: (
                _CUP_ORDER[marker.marker_type],
                marker.marker_type.value,
                marker.marker_id,
            ),
        )
    )
    return ordered_trend + ordered_escape + ordered_cup


class NewowTrendD1Engine:
    """Stateful, in-memory completed-D1 orchestrator with no external dependencies."""

    def __init__(
        self,
        *,
        profile: NewowTrendProfile = NEWOW_TREND_D1_V1,
        state: NewowTrendD1EngineState | None = None,
    ) -> None:
        self._profile = profile
        self._state = _initial_state() if state is None else state

    @classmethod
    def initial(
        cls, *, profile: NewowTrendProfile = NEWOW_TREND_D1_V1
    ) -> NewowTrendD1Engine:
        return cls(profile=profile)

    @property
    def state(self) -> NewowTrendD1EngineState:
        return self._state

    def step(self, bar: NewowDailyBar) -> NewowTrendD1StepResult:
        state = self._state
        if not _state_is_valid(state, self._profile):
            next_state = _initial_state()
            result = NewowTrendD1StepResult(next_state, _unavailable_frame(bar))
            self._state = next_state
            return result

        if state.last_bar_end is not None:
            if bar.bar_end == state.last_bar_end:
                raise ValueError("NEWOW_BAR_DUPLICATE")
            if bar.bar_end < state.last_bar_end:
                raise ValueError("NEWOW_BAR_OUT_OF_ORDER")
            assert state.last_trading_day is not None
            if bar.trading_day <= state.last_trading_day:
                raise ValueError("NEWOW_TRADING_DAY_OUT_OF_ORDER")

        incoming_identity = (bar.physical_contract, bar.segment_id)
        rollover_started = (
            state.physical_contract is not None
            and incoming_identity != (state.physical_contract, state.segment_id)
        )
        if rollover_started:
            state = _initial_state()
        elif state.eligibility_started and not bar.observation_eligible:
            raise ValueError("NEWOW_OBSERVATION_ELIGIBILITY_REGRESSION")

        trend_result = step_trend_band(state.trend_band_state, bar, profile=self._profile)
        escape_result = step_escape_d123(state.escape_state, bar, profile=self._profile)
        cup_result = step_cup_handle(state.cup_handle_state, bar, profile=self._profile)
        markers = (
            ()
            if rollover_started
            else _ordered_markers(
                trend_result.marker, escape_result.markers, cup_result.markers
            )
        )
        next_state = NewowTrendD1EngineState(
            trend_band_state=trend_result.state,
            escape_state=escape_result.state,
            cup_handle_state=cup_result.state,
            physical_contract=bar.physical_contract,
            segment_id=bar.segment_id,
            last_bar_end=bar.bar_end,
            last_trading_day=bar.trading_day,
            eligibility_started=state.eligibility_started or bar.observation_eligible,
        )
        frame = NewowTrendFrame(
            bar=bar,
            trend_band=trend_result.point,
            markers=markers,
            cup_handle=cup_result.active_overlay,
            rollover_started=rollover_started,
            diagnostics=cup_result.diagnostics,
        )
        result = NewowTrendD1StepResult(next_state, frame)
        self._state = next_state
        return result


def calculate_newow_trend_frames(
    bars: tuple[NewowDailyBar, ...],
    *,
    profile: NewowTrendProfile = NEWOW_TREND_D1_V1,
) -> tuple[NewowTrendFrame, ...]:
    engine = NewowTrendD1Engine.initial(profile=profile)
    return tuple(engine.step(bar).frame for bar in bars)
