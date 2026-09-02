"""The sole pure incremental orchestrator for completed Newow D1 observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from math import isclose, isfinite

from .cup_handle import (
    CupHandleStateValue,
    WilderAtrState,
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
    source_bars: tuple[NewowDailyBar, ...] = ()
    source_atr_before: WilderAtrState = WilderAtrState()


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
        source_bars=(),
        source_atr_before=WilderAtrState(),
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
            and state.source_bars == ()
            and state.source_atr_before == WilderAtrState()
            and all(identity == (None, None) for identity in identities)
        )
    return (
        state.last_bar_end is not None
        and state.last_trading_day is not None
        and all(identity == engine_identity for identity in identities)
        and state.eligibility_started == state.cup_handle_state.eligible_started
        and _substate_history_is_coherent(state, profile)
    )


def _source_history_limit(profile: NewowTrendProfile) -> int:
    """Keep exactly the raw facts required by the bounded trend/escape states."""

    return max(
        profile.trend_weight_period + profile.trend_signal_period - 1,
        profile.ma120_period + profile.ma120_slope_window - 1,
        profile.var4_lookback,
    )


def _atr_state_is_valid(state: object) -> bool:
    if not isinstance(state, WilderAtrState):
        return False
    if (
        not isinstance(state.count, int)
        or state.count < 0
        or not isinstance(state.tr_total, float)
        or not isfinite(state.tr_total)
        or state.tr_total < 0.0
    ):
        return False
    if state.atr is not None and (
        not isinstance(state.atr, float) or not isfinite(state.atr) or state.atr <= 0.0
    ):
        return False
    return state.previous_close is None or (
        isinstance(state.previous_close, Decimal)
        and state.previous_close.is_finite()
        and state.previous_close > 0
    )


def _advance_atr(
    state: WilderAtrState, bar: NewowDailyBar, period: int
) -> WilderAtrState | None:
    """Replay the Cup ATR transition from retained raw facts only."""

    if not _atr_state_is_valid(state) or period <= 0:
        return None
    if not all(value.is_finite() for value in (bar.high, bar.low, bar.close)):
        return None
    previous_close = state.previous_close
    tr = max(
        float(bar.high - bar.low),
        abs(float(bar.high - previous_close)) if previous_close is not None else 0.0,
        abs(float(bar.low - previous_close)) if previous_close is not None else 0.0,
    )
    if not isfinite(tr) or tr < 0.0:
        return None
    count = state.count + 1
    if state.atr is None and count < period:
        return WilderAtrState(count, state.tr_total + tr, None, bar.close)
    if state.atr is None:
        total = state.tr_total + tr
        atr = total / period
        return (
            None
            if not isfinite(atr) or atr <= 0.0
            else WilderAtrState(count, total, atr, bar.close)
        )
    atr = ((period - 1) * state.atr + tr) / period
    return (
        None
        if not isfinite(atr) or atr <= 0.0
        else WilderAtrState(count, 0.0, atr, bar.close)
    )


def _atr_states_match(left: WilderAtrState, right: WilderAtrState) -> bool:
    return (
        left.count == right.count
        and left.previous_close == right.previous_close
        and (left.atr is None) == (right.atr is None)
        and isclose(left.tr_total, right.tr_total, rel_tol=1e-12, abs_tol=1e-12)
        and (
            left.atr is None
            or right.atr is not None
            and isclose(left.atr, right.atr, rel_tol=1e-12, abs_tol=1e-12)
        )
    )


def _source_history_is_valid(
    state: NewowTrendD1EngineState,
    profile: NewowTrendProfile,
) -> bool:
    """Validate the bounded source basis, including its eligibility witness.

    Eligibility can only move from False to True within a segment.  Therefore,
    after the first True Bar is evicted, every later retained Bar is still True;
    a non-empty valid suffix never loses the fact that eligibility has started.
    """

    source = state.source_bars
    processed_count = state.cup_handle_state.atr_state.count
    if (
        not isinstance(source, tuple)
        or not _atr_state_is_valid(state.source_atr_before)
        or len(source) != min(processed_count, _source_history_limit(profile))
        or state.source_atr_before.count != processed_count - len(source)
        or not source
    ):
        return False
    prior_end: datetime | None = None
    prior_day: date | None = None
    source_eligibility_started = False
    for bar in source:
        if (
            not isinstance(bar, NewowDailyBar)
            or bar.physical_contract != state.physical_contract
            or bar.segment_id != state.segment_id
            or not isinstance(bar.bar_end, datetime)
            or bar.bar_end.tzinfo is None
            or bar.bar_end.utcoffset() is None
            or not isinstance(bar.trading_day, date)
            or isinstance(bar.trading_day, datetime)
            or (prior_end is not None and bar.bar_end <= prior_end)
            or (prior_day is not None and bar.trading_day <= prior_day)
            or (source_eligibility_started and not bar.observation_eligible)
        ):
            return False
        prior_end, prior_day = bar.bar_end, bar.trading_day
        source_eligibility_started = (
            source_eligibility_started or bar.observation_eligible
        )
    return (
        source[-1].bar_end == state.last_bar_end
        and source[-1].trading_day == state.last_trading_day
        and state.eligibility_started == source_eligibility_started
        and state.cup_handle_state.eligible_started == source_eligibility_started
    )


def _source_atr_is_coherent(
    state: NewowTrendD1EngineState,
    profile: NewowTrendProfile,
) -> bool:
    replayed = state.source_atr_before
    for bar in state.source_bars:
        advanced = _advance_atr(replayed, bar, profile.cup_atr_period)
        if advanced is None:
            return False
        replayed = advanced
    return _atr_states_match(replayed, state.cup_handle_state.atr_state)


def _next_source_basis(
    state: NewowTrendD1EngineState,
    bar: NewowDailyBar,
    profile: NewowTrendProfile,
) -> tuple[tuple[NewowDailyBar, ...], WilderAtrState]:
    """Advance the bounded factual basis in lockstep with the three kernels."""

    source = state.source_bars
    before = state.source_atr_before
    if len(source) == _source_history_limit(profile):
        advanced = _advance_atr(before, source[0], profile.cup_atr_period)
        assert advanced is not None
        before = advanced
        source = source[1:]
    return source + (bar,), before


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
    if not _source_history_is_valid(state, profile) or not _source_atr_is_coherent(
        state, profile
    ):
        return False

    source = state.source_bars
    source_typicals = tuple(_trend_typical_price(bar, profile) for bar in source)
    if any(value is None for value in source_typicals):
        return False
    typicals = tuple(value for value in source_typicals if value is not None)
    if state.trend_band_state.weighted_window != typicals[
        -expected_weighted_count:
    ]:
        return False

    signal_source_count = profile.trend_weight_period + expected_signal_count - 1
    signal_source = typicals[-signal_source_count:]
    expected_signal = tuple(
        sum((index + 1) * value for index, value in enumerate(window))
        / sum(range(1, profile.trend_weight_period + 1))
        for window in (
            signal_source[index : index + profile.trend_weight_period]
            for index in range(expected_signal_count)
        )
    )
    if state.trend_band_state.signal_window != expected_signal:
        return False

    escape = state.escape_state
    if (
        len(source) < escape.history_count + len(escape.ma120_prior_closes)
        or escape.closes
        != tuple(float(bar.close) for bar in source[-escape.history_count:])
        or escape.highs
        != tuple(float(bar.high) for bar in source[-escape.history_count:])
        or escape.lows
        != tuple(float(bar.low) for bar in source[-escape.history_count:])
    ):
        return False
    if escape.ma120_prior_closes:
        prior_end = -escape.history_count
        prior_start = prior_end - len(escape.ma120_prior_closes)
        if escape.ma120_prior_closes != tuple(
            float(bar.close) for bar in source[prior_start:prior_end]
        ):
            return False

    snapshots = state.cup_handle_state.eligible_bars
    snapshot_overlap = min(len(snapshots), len(source))
    return not snapshot_overlap or tuple(
        snapshot.bar for snapshot in snapshots[-snapshot_overlap:]
    ) == source[-snapshot_overlap:]


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
        source_bars, source_atr_before = _next_source_basis(
            state, bar, self._profile
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
            source_bars=source_bars,
            source_atr_before=source_atr_before,
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
