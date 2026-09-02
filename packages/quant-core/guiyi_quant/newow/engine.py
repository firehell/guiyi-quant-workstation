"""The sole pure incremental orchestrator for completed Newow D1 observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from .cup_handle import (
    CupHandleStepResult,
    CupHandleStateValue,
    initial_cup_handle_state,
    step_cup_handle,
)
from .escape_d123 import (
    EscapeState,
    EscapeStepResult,
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
    TrendBandStepResult,
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


def _state_shape_is_valid(state: object) -> bool:
    if not isinstance(state, NewowTrendD1EngineState):
        return False
    if not isinstance(state.trend_band_state, TrendBandStateValue):
        return False
    if not isinstance(state.escape_state, EscapeState):
        return False
    if not isinstance(state.cup_handle_state, CupHandleStateValue):
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
            and state.trend_band_state == initial_trend_band_state()
            and state.escape_state == initial_escape_state()
            and state.cup_handle_state == initial_cup_handle_state()
        )
    if not (
        state.last_bar_end is not None
        and state.last_trading_day is not None
        and all(identity == engine_identity for identity in identities)
        and state.eligibility_started == state.cup_handle_state.eligible_started
    ):
        return False
    retained = state.cup_handle_state.eligible_bars
    if retained:
        latest = retained[-1].bar
        return (
            latest.bar_end == state.last_bar_end
            and latest.trading_day == state.last_trading_day
        )
    return True


def _step_substates(
    state: NewowTrendD1EngineState,
    bar: NewowDailyBar,
    profile: NewowTrendProfile,
) -> tuple[TrendBandStepResult, EscapeStepResult, CupHandleStepResult] | None:
    """Use each kernel's safe step output as its self-validation contract."""

    try:
        trend = step_trend_band(state.trend_band_state, bar, profile=profile)
        escape = step_escape_d123(state.escape_state, bar, profile=profile)
        cup = step_cup_handle(state.cup_handle_state, bar, profile=profile)
    except (ArithmeticError, AttributeError, LookupError, TypeError, ValueError):
        return None

    incoming_identity = (bar.physical_contract, bar.segment_id)
    result_identities = (
        (trend.state.physical_contract, trend.state.segment_id),
        (escape.state.physical_contract, escape.state.segment_id),
        (cup.state.physical_contract, cup.state.segment_id),
    )
    same_segment = (state.physical_contract, state.segment_id) in {
        (None, None),
        incoming_identity,
    }
    expected_eligibility = (
        state.eligibility_started if same_segment else False
    ) or bar.observation_eligible
    if (
        trend.point.bar_end != bar.bar_end
        or any(identity != incoming_identity for identity in result_identities)
        or cup.state.eligible_started != expected_eligibility
        or "NEWOW_CUP_STATE_INVALID" in cup.diagnostics
    ):
        return None
    return trend, escape, cup


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
        if not _state_shape_is_valid(state):
            next_state = _initial_state()
            result = NewowTrendD1StepResult(next_state, _unavailable_frame(bar))
            self._state = next_state
            return result

        stepped = _step_substates(state, bar, self._profile)
        if stepped is None:
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
            stepped = _step_substates(state, bar, self._profile)
            assert stepped is not None
        elif state.eligibility_started and not bar.observation_eligible:
            raise ValueError("NEWOW_OBSERVATION_ELIGIBILITY_REGRESSION")

        trend_result, escape_result, cup_result = stepped
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
