"""Bounded, causal cup-handle observation kernel for completed D1 bars."""

from __future__ import annotations

from dataclasses import dataclass, replace
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
    NewowMarkerType,
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


def _marker(overlay: NewowCupHandleOverlay, marker_type: NewowMarkerType, bar: NewowDailyBar, related: tuple[str, ...]) -> NewowMainMarker:
    marker_id = sha256(f"{overlay.candidate_id}|{marker_type.value}|{bar.bar_end.isoformat()}".encode()).hexdigest()
    facts = {
        "candidate_id": overlay.candidate_id, "direction": overlay.direction.value,
        "state_after": overlay.state.value, "left_rim": str(overlay.left_rim.price),
        "bottom": str(overlay.bottom.price), "right_rim": str(overlay.right_rim.price),
        "handle": str(overlay.handle_extreme.price) if overlay.handle_extreme else None,
        "pivot_price": str(overlay.pivot_price) if overlay.pivot_price else None,
        "score": overlay.score, "score_breakdown": dict(overlay.score_breakdown),
        "volume_facts": dict(overlay.volume_facts), "formula_version": overlay.formula_version,
    }
    return NewowMainMarker(marker_id, marker_type, bar.bar_end, bar.close, marker_type.value, "cup_handle", 100, related, facts, overlay.formula_version)


def _median_volume(items: list[CupBarSnapshot]) -> float | None:
    values = [float(item.bar.volume) for item in items]
    return median(values) if values and all(value > 0 for value in values) else None


def _ready_candidate(forming: NewowCupHandleOverlay, pivots: tuple[CupPivot, ...], bars: tuple[CupBarSnapshot, ...], current: CupBarSnapshot, profile: NewowTrendProfile) -> tuple[NewowCupHandleOverlay | None, str | None]:
    reverse_kind = CupPivotKind.LOW if forming.right_rim.kind == CupPivotKind.HIGH else CupPivotKind.HIGH
    handles = [pivot for pivot in pivots if pivot.kind == reverse_kind and pivot.pivot_index > forming.right_rim.pivot_index and profile.cup_handle_min_bars <= pivot.confirmed_index - forming.right_rim.pivot_index <= profile.cup_handle_max_bars]
    if not handles:
        return None, None
    direction = forming.direction
    handle = min(handles, key=lambda pivot: (_normal(direction, pivot.price), -pivot.pivot_index))
    right, bottom = _normal(direction, forming.right_rim.price), _normal(direction, forming.bottom.price)
    handle_price = _normal(direction, handle.price)
    depth = right - handle_price
    if depth / abs(right) > profile.cup_handle_depth_max_pct:
        return None, "HANDLE_DEPTH_EXCEEDED"
    if depth / (right - bottom) > profile.cup_handle_retrace_max_ratio:
        return None, "HANDLE_RETRACE_EXCEEDED"
    if handle_price < bottom + profile.cup_handle_upper_half_ratio * (right - bottom):
        return None, "HANDLE_BELOW_CUP_MID"
    by_index = {item.eligible_index: item for item in bars}
    pivot_window = [by_index[index] for index in range(forming.right_rim.pivot_index + 1, handle.confirmed_index) if index in by_index]
    if not pivot_window:
        return None, "HANDLE_PIVOT_UNAVAILABLE"
    pivot_price = (max(item.bar.high for item in pivot_window) if direction == CupHandleDirection.BULLISH else min(item.bar.low for item in pivot_window))
    right_volume = _median_volume([item for item in bars if forming.bottom.pivot_index < item.eligible_index <= forming.right_rim.pivot_index])
    handle_volume = _median_volume([item for item in bars if forming.right_rim.pivot_index < item.eligible_index < handle.confirmed_index])
    baseline = _median_volume([item for item in bars if forming.right_rim.pivot_index - 19 <= item.eligible_index <= forming.right_rim.pivot_index])
    if right_volume is None or handle_volume is None or baseline is None:
        return None, "HANDLE_VOLUME_UNAVAILABLE"
    if handle_volume > profile.cup_handle_right_volume_max_ratio * right_volume or handle_volume > profile.cup_handle_baseline_volume_max_ratio * baseline:
        return None, "HANDLE_VOLUME_NOT_CONTRACTING"
    breakdown = {"pretrend": 15.0, "cup_geometry": 25.0, "u_shape_purity": 20.0, "handle_quality": 20.0, "volume_structure": 14.0}
    score = sum(breakdown.values())
    if score < profile.cup_ready_min_score:
        return None, "CUP_READY_SCORE_INSUFFICIENT"
    return replace(forming, state=CupHandleState.READY, handle_extreme=handle, pivot_price=pivot_price, pivot_frozen_at=current.bar.bar_end, confirmed_at=current.bar.bar_end, state_changed_at=current.bar.bar_end, score=score, score_breakdown=breakdown, volume_facts={"right_leg_median": right_volume, "handle_median": handle_volume, "baseline_median": baseline}), None


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
    markers: list[NewowMainMarker] = []
    emitted = base.emitted_milestones
    terminals = base.recent_terminal_candidate_ids
    if active is not None and active.state == CupHandleState.FORMING:
        ready, reason = _ready_candidate(active, pivots, bars, snapshot, profile)
        if reason:
            diagnostics.append(reason)
        if ready is not None:
            active = ready
            ready_marker = _marker(active, NewowMarkerType.CUP_HANDLE_READY, bar, ())
            markers.append(ready_marker)
            emitted += (ready_marker.marker_id,)
    if active is not None and active.state in {CupHandleState.READY, CupHandleState.BREAKOUT, CupHandleState.WEAKENED}:
        assert active.handle_extreme is not None and active.pivot_price is not None
        ready_handle = active.handle_extreme
        sign_close, sign_pivot, sign_handle = (_normal(active.direction, value) for value in (bar.close, active.pivot_price, active.handle_extreme.price))
        threshold = sign_pivot + profile.cup_breakout_buffer_atr * snapshot.atr
        previous = bars[-2] if len(bars) > 1 else None
        previous_above = previous is not None and _normal(active.direction, previous.bar.close) > sign_pivot + profile.cup_breakout_buffer_atr * previous.atr
        if sign_close < sign_handle - profile.cup_breakout_buffer_atr * snapshot.atr:
            active = replace(active, state=CupHandleState.INVALIDATED, state_changed_at=bar.bar_end)
            related = tuple(emitted)
            marker = _marker(active, NewowMarkerType.CUP_HANDLE_INVALIDATED, bar, related)
            markers.append(marker)
            emitted += (marker.marker_id,)
            terminals = (terminals + (active.candidate_id,))[-profile.cup_recent_terminal_ids_limit:]
        elif active.state == CupHandleState.BREAKOUT and sign_close < sign_pivot:
            active = replace(active, state=CupHandleState.WEAKENED, state_changed_at=bar.bar_end)
            marker = _marker(active, NewowMarkerType.CUP_HANDLE_WEAKENED, bar, tuple(emitted))
            markers.append(marker)
            emitted += (marker.marker_id,)
        elif active.state == CupHandleState.READY and sign_close > threshold and not previous_above:
            breakout_window = [item for item in bars[:-1] if item.eligible_index >= snapshot.eligible_index - 20]
            baseline = _median_volume(breakout_window)
            handle_volume = active.volume_facts.get("handle_median", 0.0)
            if baseline and bar.volume >= profile.cup_breakout_volume20_min_ratio * baseline and bar.volume >= profile.cup_breakout_handle_volume_min_ratio * handle_volume:
                active = replace(active, state=CupHandleState.BREAKOUT, state_changed_at=bar.bar_end, score=100.0, score_breakdown={**active.score_breakdown, "volume_structure": 20.0})
                marker = _marker(active, NewowMarkerType.CUP_HANDLE_BREAKOUT, bar, tuple(emitted))
                markers.append(marker)
                emitted += (marker.marker_id,)
            else:
                diagnostics.append("BREAKOUT_VOLUME_UNCONFIRMED")
        elif active.state == CupHandleState.READY and snapshot.eligible_index - ready_handle.confirmed_index >= profile.cup_ready_expiry_bars:
            active = replace(active, state=CupHandleState.EXPIRED, state_changed_at=bar.bar_end)
            marker = _marker(active, NewowMarkerType.CUP_HANDLE_EXPIRED, bar, tuple(emitted))
            markers.append(marker)
            emitted += (marker.marker_id,)
            terminals = (terminals + (active.candidate_id,))[-profile.cup_recent_terminal_ids_limit:]
    result = CupHandleStateValue(atr_state, tracker, bars, pivots, active, emitted, terminals, bar.physical_contract, bar.segment_id, True)
    return CupHandleStepResult(result, active, tuple(markers), tuple(diagnostics), checks)


def calculate_cup_handle_series(bars: tuple[NewowDailyBar, ...], *, profile: NewowTrendProfile = NEWOW_TREND_D1_V1) -> tuple[CupHandleStepResult, ...]:
    state = initial_cup_handle_state()
    results: list[CupHandleStepResult] = []
    for bar in bars:
        result = step_cup_handle(state, bar, profile=profile)
        results.append(result)
        state = result.state
    return tuple(results)
