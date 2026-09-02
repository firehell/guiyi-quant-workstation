"""Bounded, causal cup-handle observation kernel for completed D1 bars."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from statistics import median

from .models import (
    CupHandleDirection,
    CupHandleState,
    CupPivot,
    CupPivotKind,
    NewowCupHandleOverlay,
    NewowDailyBar,
    NewowMainMarker,
)
from .profile import NEWOW_TREND_D1_V1, NewowTrendProfile


@dataclass(frozen=True, slots=True)
class WilderAtrState:
    count: int = 0
    tr_total: float = 0.0
    atr: float | None = None
    previous_close: Decimal | None = None


@dataclass(frozen=True, slots=True)
class CupBarSnapshot:
    bar: NewowDailyBar
    eligible_index: int
    atr: float


@dataclass(frozen=True, slots=True)
class CupPivotTrackerState:
    leg: str = "SEEK_DIRECTION"
    extreme_high: CupBarSnapshot | None = None
    extreme_low: CupBarSnapshot | None = None


@dataclass(frozen=True, slots=True)
class CupHandleStateValue:
    atr_state: WilderAtrState
    pivot_tracker: CupPivotTrackerState
    eligible_bars: tuple[CupBarSnapshot, ...]
    confirmed_pivots: tuple[CupPivot, ...]
    active_candidate: NewowCupHandleOverlay | None
    emitted_milestones: tuple[str, ...]
    recent_terminal_candidate_ids: tuple[str, ...]
    physical_contract: str | None
    segment_id: str | None
    eligible_started: bool


@dataclass(frozen=True, slots=True)
class CupHandleStepResult:
    state: CupHandleStateValue
    active_overlay: NewowCupHandleOverlay | None
    markers: tuple[NewowMainMarker, ...]
    diagnostics: tuple[str, ...]
    candidate_checks: int


def initial_cup_handle_state() -> CupHandleStateValue:
    return CupHandleStateValue(
        atr_state=WilderAtrState(),
        pivot_tracker=CupPivotTrackerState(),
        eligible_bars=(),
        confirmed_pivots=(),
        active_candidate=None,
        emitted_milestones=(),
        recent_terminal_candidate_ids=(),
        physical_contract=None,
        segment_id=None,
        eligible_started=False,
    )


def _next_atr(state: WilderAtrState, bar: NewowDailyBar, period: int) -> WilderAtrState:
    previous_close = state.previous_close
    tr = max(
        float(bar.high - bar.low),
        abs(float(bar.high - previous_close)) if previous_close is not None else 0.0,
        abs(float(bar.low - previous_close)) if previous_close is not None else 0.0,
    )
    count = state.count + 1
    if state.atr is None and count < period:
        return WilderAtrState(count, state.tr_total + tr, None, bar.close)
    if state.atr is None:
        return WilderAtrState(count, state.tr_total + tr, (state.tr_total + tr) / period, bar.close)
    return WilderAtrState(count, 0.0, ((period - 1) * state.atr + tr) / period, bar.close)


def _pivot(kind: CupPivotKind, snapshot: CupBarSnapshot, confirmed: CupBarSnapshot) -> CupPivot:
    return CupPivot(
        kind=kind,
        price=snapshot.bar.high if kind == CupPivotKind.HIGH else snapshot.bar.low,
        pivot_at=snapshot.bar.bar_end,
        confirmed_at=confirmed.bar.bar_end,
        pivot_index=snapshot.eligible_index,
        confirmed_index=confirmed.eligible_index,
        atr_at_pivot=snapshot.atr,
    )


def _track_pivot(
    tracker: CupPivotTrackerState, snapshot: CupBarSnapshot, reversal: float, min_leg: int
) -> tuple[CupPivotTrackerState, CupPivot | None]:
    high = tracker.extreme_high
    low = tracker.extreme_low
    if high is None or snapshot.bar.high >= high.bar.high:
        high = snapshot
    if low is None or snapshot.bar.low <= low.bar.low:
        low = snapshot
    if tracker.leg == "SEEK_DIRECTION":
        up = low is not None and snapshot.eligible_index - low.eligible_index >= min_leg and float(snapshot.bar.close - low.bar.low) >= reversal * low.atr
        down = high is not None and snapshot.eligible_index - high.eligible_index >= min_leg and float(high.bar.high - snapshot.bar.close) >= reversal * high.atr
        if not up and not down:
            return CupPivotTrackerState("SEEK_DIRECTION", high, low), None
        if up and (not down or float(snapshot.bar.close - low.bar.low) >= float(high.bar.high - snapshot.bar.close)):
            return CupPivotTrackerState("UP_LEG", snapshot, low), _pivot(CupPivotKind.LOW, low, snapshot)
        return CupPivotTrackerState("DOWN_LEG", high, snapshot), _pivot(CupPivotKind.HIGH, high, snapshot)
    if tracker.leg == "UP_LEG":
        if float(high.bar.high - snapshot.bar.close) >= reversal * high.atr and snapshot.eligible_index - high.eligible_index >= min_leg:
            return CupPivotTrackerState("DOWN_LEG", high, snapshot), _pivot(CupPivotKind.HIGH, high, snapshot)
        return CupPivotTrackerState("UP_LEG", high, low), None
    if float(snapshot.bar.close - low.bar.low) >= reversal * low.atr and snapshot.eligible_index - low.eligible_index >= min_leg:
        return CupPivotTrackerState("UP_LEG", snapshot, low), _pivot(CupPivotKind.LOW, low, snapshot)
    return CupPivotTrackerState("DOWN_LEG", high, low), None


def _normal(direction: CupHandleDirection, value: Decimal) -> float:
    return float(value) if direction == CupHandleDirection.BULLISH else -float(value)


def _candidate_id(direction: CupHandleDirection, left: CupPivot, bottom: CupPivot, right: CupPivot, bar: NewowDailyBar, formula: str) -> str:
    source = "|".join(("newow_trend_v1", formula, bar.physical_contract, bar.segment_id, direction.value, left.pivot_at.isoformat(), bottom.pivot_at.isoformat(), right.pivot_at.isoformat()))
    return sha256(source.encode()).hexdigest()


def _body_overlay(
    pivots: tuple[CupPivot, ...], bars: tuple[CupBarSnapshot, ...], bar: NewowDailyBar, profile: NewowTrendProfile
) -> tuple[NewowCupHandleOverlay | None, tuple[str, ...], int]:
    checks = 0
    diagnostics: list[str] = []
    for direction, rim_kind in ((CupHandleDirection.BULLISH, CupPivotKind.HIGH), (CupHandleDirection.BEARISH, CupPivotKind.LOW)):
        rims = [pivot for pivot in pivots if pivot.kind == rim_kind]
        for left_pos, left in enumerate(rims):
            for right in rims[left_pos + 1 :]:
                checks += 1
                if checks > profile.cup_max_candidate_checks_per_step:
                    return None, ("CUP_CANDIDATE_LIMIT_EXCEEDED",), checks
                duration = right.pivot_index - left.pivot_index + 1
                if not profile.cup_min_bars <= duration <= profile.cup_max_bars:
                    continue
                bottoms = [pivot for pivot in pivots if pivot.kind != rim_kind and left.pivot_index < pivot.pivot_index < right.pivot_index]
                if not bottoms:
                    continue
                bottom = min(bottoms, key=lambda pivot: (_normal(direction, pivot.price), pivot.pivot_index))
                left_price, right_price, bottom_price = (_normal(direction, pivot.price) for pivot in (left, right, bottom))
                rim = (left_price + right_price) / 2
                depth = rim - bottom_price
                atr_values = [item.atr for item in bars if left.pivot_index <= item.eligible_index <= right.pivot_index]
                if not atr_values or depth <= 0:
                    continue
                depth_pct, depth_atr = depth / abs(rim), depth / median(atr_values)
                gap_pct, gap_atr = abs(left_price - right_price) / abs(rim), abs(left_price - right_price) / median(atr_values)
                if depth_pct < profile.cup_depth_min_pct:
                    diagnostics.append("CUP_DEPTH_BELOW_10_PERCENT")
                    continue
                if depth_pct > profile.cup_depth_hard_max_pct:
                    diagnostics.append("CUP_DEPTH_ABOVE_50_PERCENT")
                    continue
                if depth_atr < profile.cup_depth_min_atr or gap_pct > profile.cup_rim_gap_max_pct or gap_atr > profile.cup_rim_gap_max_atr:
                    diagnostics.append("CUP_GEOMETRY_REJECTED")
                    continue
                # FORMING is intentionally conservative until the complete pretrend/U gates are observable.
                return NewowCupHandleOverlay(
                    candidate_id=_candidate_id(direction, left, bottom, right, bar, profile.cup_handle_formula),
                    direction=direction,
                    state=CupHandleState.FORMING,
                    left_rim=left,
                    bottom=bottom,
                    right_rim=right,
                    handle_start_at=right.pivot_at,
                    handle_extreme=None,
                    pivot_price=None,
                    pivot_frozen_at=None,
                    confirmed_at=max(left.confirmed_at, bottom.confirmed_at, right.confirmed_at),
                    first_seen_at=bar.bar_end,
                    state_changed_at=bar.bar_end,
                    score=45.0,
                    score_breakdown={"pretrend": 15.0, "cup_geometry": 20.0, "u_shape_purity": 10.0, "handle_quality": 0.0, "volume_structure": 0.0},
                    hard_failures=(), diagnostics=(), volume_facts={}, formula_version=profile.cup_handle_formula,
                ), tuple(diagnostics), checks
    return None, tuple(diagnostics), checks


def step_cup_handle(state: CupHandleStateValue, bar: NewowDailyBar, *, profile: NewowTrendProfile = NEWOW_TREND_D1_V1) -> CupHandleStepResult:
    if not isinstance(state, CupHandleStateValue):
        return CupHandleStepResult(initial_cup_handle_state(), None, (), ("NEWOW_CUP_STATE_INVALID",), 0)
    rollover = state.physical_contract is not None and (state.physical_contract != bar.physical_contract or state.segment_id != bar.segment_id)
    if rollover:
        state = initial_cup_handle_state()
    atr_state = _next_atr(state.atr_state, bar, profile.cup_atr_period)
    base = CupHandleStateValue(atr_state, state.pivot_tracker, state.eligible_bars, state.confirmed_pivots, state.active_candidate, state.emitted_milestones, state.recent_terminal_candidate_ids, bar.physical_contract, bar.segment_id, state.eligible_started)
    diagnostics = ["CUP_ROLLOVER_RESET"] if rollover else []
    if not bar.observation_eligible:
        return CupHandleStepResult(base, base.active_candidate, (), tuple(diagnostics), 0)
    if atr_state.atr is None:
        return CupHandleStepResult(base, base.active_candidate, (), tuple(diagnostics + ["CUP_ATR_UNAVAILABLE"]), 0)
    snapshot = CupBarSnapshot(bar, len(base.eligible_bars), atr_state.atr)
    bars = (base.eligible_bars + (snapshot,))[-profile.cup_history_limit :]
    tracker, pivot = _track_pivot(base.pivot_tracker, snapshot, profile.cup_reversal_atr, profile.cup_min_leg_bars)
    pivots = base.confirmed_pivots
    if pivot is not None and (not pivots or pivots[-1].kind != pivot.kind):
        pivots = (pivots + (pivot,))[-profile.cup_max_confirmed_pivots :]
    candidate, candidate_diagnostics, checks = _body_overlay(pivots, bars, bar, profile)
    diagnostics.extend(candidate_diagnostics)
    active = base.active_candidate or candidate
    result = CupHandleStateValue(atr_state, tracker, bars, pivots, active, base.emitted_milestones, base.recent_terminal_candidate_ids, bar.physical_contract, bar.segment_id, True)
    return CupHandleStepResult(result, active, (), tuple(diagnostics), checks)


def calculate_cup_handle_series(bars: tuple[NewowDailyBar, ...], *, profile: NewowTrendProfile = NEWOW_TREND_D1_V1) -> tuple[CupHandleStepResult, ...]:
    state = initial_cup_handle_state()
    results: list[CupHandleStepResult] = []
    for bar in bars:
        result = step_cup_handle(state, bar, profile=profile)
        results.append(result)
        state = result.state
    return tuple(results)
