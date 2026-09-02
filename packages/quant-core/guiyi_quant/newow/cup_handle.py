"""Bounded, causal cup-handle observation kernel for completed D1 bars."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
from hashlib import sha256
from math import isfinite
from statistics import median
from typing import Mapping

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
    last_pivot: CupPivot | None = None
    eligible_index: int = -1


@dataclass(frozen=True, slots=True)
class CupMilestoneFact:
    fact_id: str
    marker_id: str
    marker_type: NewowMarkerType
    bar_end: datetime
    eligible_index: int
    source_identity: str


@dataclass(frozen=True, slots=True)
class CupReadyWitness:
    witness_id: str
    candidate_id: str
    left_rim: CupPivot
    bottom: CupPivot
    right_rim: CupPivot
    handle_extreme: CupPivot
    pivot_price: Decimal
    confirmed_at: datetime
    score: float
    score_breakdown: tuple[tuple[str, float], ...]
    volume_facts: tuple[tuple[str, float], ...]
    formula_version: str


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
    emitted_milestone_facts: tuple[CupMilestoneFact, ...] = ()
    ready_witness: CupReadyWitness | None = None


@dataclass(frozen=True, slots=True)
class CupHandleStepResult:
    state: CupHandleStateValue
    active_overlay: NewowCupHandleOverlay | None
    markers: tuple[NewowMainMarker, ...]
    diagnostics: tuple[str, ...]
    candidate_checks: int


@dataclass(frozen=True, slots=True)
class _BodyFacts:
    breakdown: Mapping[str, float]
    bottom_span_bars: int


_SCORE_KEYS = (
    "pretrend",
    "cup_geometry",
    "u_shape_purity",
    "handle_quality",
    "volume_structure",
)
_VOLUME_FACT_KEYS = (
    "right_leg_median",
    "handle_median",
    "handle_baseline_median",
    "handle_right_ratio",
    "handle_baseline_ratio",
)


def _pivot_witness_part(pivot: CupPivot) -> str:
    return ",".join(
        (
            pivot.kind.value,
            str(pivot.price),
            pivot.pivot_at.isoformat(),
            pivot.confirmed_at.isoformat(),
            str(pivot.pivot_index),
            str(pivot.confirmed_index),
            repr(float(pivot.atr_at_pivot)),
        )
    )


def _ready_witness_identity(
    candidate_id: str,
    left_rim: CupPivot,
    bottom: CupPivot,
    right_rim: CupPivot,
    handle_extreme: CupPivot,
    pivot_price: Decimal,
    confirmed_at: datetime,
    score: float,
    score_breakdown: tuple[tuple[str, float], ...],
    volume_facts: tuple[tuple[str, float], ...],
    formula_version: str,
) -> str:
    source = "|".join(
        (
            "newow_cup_ready_witness_v1",
            candidate_id,
            _pivot_witness_part(left_rim),
            _pivot_witness_part(bottom),
            _pivot_witness_part(right_rim),
            _pivot_witness_part(handle_extreme),
            str(pivot_price),
            confirmed_at.isoformat(),
            repr(float(score)),
            *(f"score:{key}={value!r}" for key, value in score_breakdown),
            *(f"volume:{key}={value!r}" for key, value in volume_facts),
            formula_version,
        )
    )
    return sha256(source.encode()).hexdigest()


def _ready_witness(active: NewowCupHandleOverlay) -> CupReadyWitness:
    assert active.handle_extreme is not None
    assert active.pivot_price is not None
    score_breakdown = tuple(
        (key, float(active.score_breakdown[key])) for key in _SCORE_KEYS
    )
    volume_facts = tuple(
        (key, float(active.volume_facts[key])) for key in _VOLUME_FACT_KEYS
    )
    return CupReadyWitness(
        witness_id=_ready_witness_identity(
            active.candidate_id,
            active.left_rim,
            active.bottom,
            active.right_rim,
            active.handle_extreme,
            active.pivot_price,
            active.confirmed_at,
            active.score,
            score_breakdown,
            volume_facts,
            active.formula_version,
        ),
        candidate_id=active.candidate_id,
        left_rim=active.left_rim,
        bottom=active.bottom,
        right_rim=active.right_rim,
        handle_extreme=active.handle_extreme,
        pivot_price=active.pivot_price,
        confirmed_at=active.confirmed_at,
        score=active.score,
        score_breakdown=score_breakdown,
        volume_facts=volume_facts,
        formula_version=active.formula_version,
    )


def _candidate_identity(
    direction: CupHandleDirection,
    left: CupPivot,
    bottom: CupPivot,
    right: CupPivot,
    physical_contract: str,
    segment_id: str,
    formula: str,
) -> str:
    source = "|".join(
        (
            "newow_trend_v1",
            formula,
            physical_contract,
            segment_id,
            direction.value,
            left.pivot_at.isoformat(),
            bottom.pivot_at.isoformat(),
            right.pivot_at.isoformat(),
        )
    )
    return sha256(source.encode()).hexdigest()


def _marker_identity(
    candidate_id: str,
    marker_type: NewowMarkerType,
    bar_end: datetime,
) -> str:
    return sha256(
        f"{candidate_id}|{marker_type.value}|{bar_end.isoformat()}".encode()
    ).hexdigest()


def _milestone_fact_identity(
    candidate_id: str,
    marker_id: str,
    marker_type: NewowMarkerType,
    bar_end: datetime,
    eligible_index: int,
    source_identity: str,
    physical_contract: str,
    segment_id: str,
) -> str:
    source = "|".join(
        (
            "newow_cup_milestone_state_v1",
            candidate_id,
            marker_id,
            marker_type.value,
            bar_end.isoformat(),
            str(eligible_index),
            source_identity,
            physical_contract,
            segment_id,
        )
    )
    return sha256(source.encode()).hexdigest()


def _milestone_fact(
    marker: NewowMainMarker,
    snapshot: CupBarSnapshot,
    candidate_id: str,
) -> CupMilestoneFact:
    return CupMilestoneFact(
        fact_id=_milestone_fact_identity(
            candidate_id,
            marker.marker_id,
            marker.marker_type,
            marker.bar_end,
            snapshot.eligible_index,
            snapshot.bar.source_identity,
            snapshot.bar.physical_contract,
            snapshot.bar.segment_id,
        ),
        marker_id=marker.marker_id,
        marker_type=marker.marker_type,
        bar_end=marker.bar_end,
        eligible_index=snapshot.eligible_index,
        source_identity=snapshot.bar.source_identity,
    )


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
        emitted_milestone_facts=(),
        ready_witness=None,
    )


def _unique(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _safe_finite_float(value: Decimal | Fraction | int | float) -> float | None:
    try:
        numeric = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    return numeric if isfinite(numeric) else None


def _rational_parameter(value: int | float) -> Fraction:
    return Fraction(value).limit_denominator()


def _decimal_ratio_exceeds(
    numerator: Decimal | Fraction,
    denominator: Decimal | Fraction,
    threshold: float,
) -> bool:
    """Compare a Decimal ratio to the profile's human-authored rational value."""

    rational = _rational_parameter(threshold)
    return (
        Fraction(numerator) * rational.denominator
        > Fraction(denominator) * rational.numerator
    )


def _decimal_ratio_below(
    numerator: Decimal | Fraction,
    denominator: Decimal | Fraction,
    threshold: float,
) -> bool:
    rational = _rational_parameter(threshold)
    return (
        Fraction(numerator) * rational.denominator
        < Fraction(denominator) * rational.numerator
    )


def _decimal_over_fraction(
    numerator: Decimal | Fraction, denominator: float
) -> Fraction | None:
    if not isfinite(denominator) or denominator <= 0:
        return None
    return Fraction(numerator) / Fraction(Decimal(str(denominator)))


def _finite_fact_values(
    facts: Mapping[str, object], required_keys: tuple[str, ...]
) -> dict[str, float] | None:
    if set(facts) != set(required_keys):
        return None
    values: dict[str, float] = {}
    for key in required_keys:
        value = facts[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        numeric = _safe_finite_float(value)
        if numeric is None:
            return None
        values[key] = numeric
    return values


def _ready_witness_is_valid(
    active: NewowCupHandleOverlay,
    witness: object,
) -> bool:
    if not isinstance(witness, CupReadyWitness):
        return False
    if (
        not isinstance(witness.score_breakdown, tuple)
        or not all(
            isinstance(item, tuple) and len(item) == 2
            for item in witness.score_breakdown
        )
        or not isinstance(witness.volume_facts, tuple)
        or not all(
            isinstance(item, tuple) and len(item) == 2
            for item in witness.volume_facts
        )
        or tuple(key for key, _ in witness.score_breakdown) != _SCORE_KEYS
        or tuple(key for key, _ in witness.volume_facts) != _VOLUME_FACT_KEYS
    ):
        return False
    breakdown = _finite_fact_values(dict(witness.score_breakdown), _SCORE_KEYS)
    volumes = _finite_fact_values(dict(witness.volume_facts), _VOLUME_FACT_KEYS)
    if breakdown is None or volumes is None:
        return False
    if (
        witness.candidate_id != active.candidate_id
        or witness.left_rim != active.left_rim
        or witness.bottom != active.bottom
        or witness.right_rim != active.right_rim
        or witness.handle_extreme != active.handle_extreme
        or witness.pivot_price != active.pivot_price
        or witness.confirmed_at != active.confirmed_at
        or witness.score != active.score
        or dict(witness.score_breakdown) != dict(active.score_breakdown)
        or dict(witness.volume_facts) != dict(active.volume_facts)
        or witness.formula_version != active.formula_version
    ):
        return False
    return witness.witness_id == _ready_witness_identity(
        witness.candidate_id,
        witness.left_rim,
        witness.bottom,
        witness.right_rim,
        witness.handle_extreme,
        witness.pivot_price,
        witness.confirmed_at,
        witness.score,
        witness.score_breakdown,
        witness.volume_facts,
        witness.formula_version,
    )


def _retained_window(
    by_index: Mapping[int, CupBarSnapshot], start: int, end: int
) -> tuple[CupBarSnapshot, ...] | None:
    snapshots = tuple(by_index[index] for index in range(start, end + 1) if index in by_index)
    if len(snapshots) != end - start + 1:
        return None
    return snapshots


def _snapshot_observable_facts_are_valid(
    snapshot: object,
    state: CupHandleStateValue,
) -> bool:
    if not isinstance(snapshot, CupBarSnapshot) or not isinstance(
        snapshot.bar, NewowDailyBar
    ):
        return False
    return (
        type(snapshot.eligible_index) is int
        and snapshot.eligible_index >= 0
        and not isinstance(snapshot.atr, bool)
        and isinstance(snapshot.atr, (int, float))
        and isfinite(snapshot.atr)
        and snapshot.atr > 0
        and snapshot.bar.observation_eligible is True
        and snapshot.bar.physical_contract == state.physical_contract
        and snapshot.bar.segment_id == state.segment_id
    )


def _tracker_is_coherent(
    state: CupHandleStateValue,
    profile: NewowTrendProfile,
    by_index: Mapping[int, CupBarSnapshot],
) -> bool:
    tracker = state.pivot_tracker
    pivots = state.confirmed_pivots
    bars = state.eligible_bars
    if (
        isinstance(tracker.eligible_index, bool)
        or not isinstance(tracker.eligible_index, int)
    ):
        return False
    if state.eligible_started != (tracker.eligible_index >= 0):
        return False
    if bars:
        if bars[-1].eligible_index != tracker.eligible_index:
            return False
        if any(
            right.eligible_index != left.eligible_index + 1
            for left, right in zip(bars, bars[1:])
        ):
            return False
    if tracker.last_pivot is None:
        if pivots or tracker.leg != "SEEK_DIRECTION":
            return False
    else:
        if not pivots or tracker.last_pivot != pivots[-1]:
            return False
        expected_leg = (
            "UP_LEG"
            if tracker.last_pivot.kind == CupPivotKind.LOW
            else "DOWN_LEG"
        )
        if tracker.leg != expected_leg:
            return False
    if tracker.leg == "SEEK_DIRECTION":
        if (tracker.extreme_high is None) != (tracker.extreme_low is None):
            return False
        if (
            tracker.extreme_high is not None
            and tracker.extreme_high.eligible_index in by_index
            and tracker.extreme_high
            != max(bars, key=lambda snapshot: snapshot.bar.high)
        ):
            return False
        if (
            tracker.extreme_low is not None
            and tracker.extreme_low.eligible_index in by_index
            and tracker.extreme_low
            != min(bars, key=lambda snapshot: snapshot.bar.low)
        ):
            return False
    elif tracker.extreme_high is None or tracker.extreme_low is None:
        return False

    previous_pivot: CupPivot | None = None
    for pivot in pivots:
        confirmed = by_index.get(pivot.confirmed_index)
        if confirmed is not None:
            reversal_distance = (
                Fraction(pivot.price) - Fraction(confirmed.bar.close)
                if pivot.kind == CupPivotKind.HIGH
                else Fraction(confirmed.bar.close) - Fraction(pivot.price)
            )
            reversal_threshold = _rational_parameter(
                profile.cup_reversal_atr
            ) * Fraction(Decimal(str(pivot.atr_at_pivot)))
            if reversal_distance < reversal_threshold:
                return False
        if previous_pivot is not None:
            if (
                pivot.pivot_index < previous_pivot.confirmed_index
                or pivot.pivot_index - previous_pivot.pivot_index
                < profile.cup_min_leg_bars
            ):
                return False
        previous_pivot = pivot

    if tracker.last_pivot is not None:
        directional_extreme = (
            tracker.extreme_high
            if tracker.leg == "UP_LEG"
            else tracker.extreme_low
        )
        assert directional_extreme is not None
        if (
            directional_extreme.eligible_index < tracker.last_pivot.confirmed_index
            or (
                directional_extreme.eligible_index
                == tracker.last_pivot.confirmed_index
                and directional_extreme.bar.bar_end
                != tracker.last_pivot.confirmed_at
            )
            or (
                directional_extreme.eligible_index
                > tracker.last_pivot.confirmed_index
                and directional_extreme.bar.bar_end
                <= tracker.last_pivot.confirmed_at
            )
        ):
            return False
        leg_window = _retained_window(
            by_index,
            tracker.last_pivot.confirmed_index,
            tracker.eligible_index,
        )
        if leg_window is not None:
            expected = (
                max(leg_window, key=lambda snapshot: snapshot.bar.high)
                if tracker.leg == "UP_LEG"
                else min(leg_window, key=lambda snapshot: snapshot.bar.low)
            )
            if directional_extreme != expected:
                return False
    return True


def _atr_state_is_valid(state: object, period: int) -> bool:
    if not isinstance(state, WilderAtrState):
        return False
    if (
        isinstance(state.count, bool)
        or not isinstance(state.count, int)
        or state.count < 0
        or isinstance(state.tr_total, bool)
        or not isinstance(state.tr_total, (int, float))
        or not isfinite(state.tr_total)
        or state.tr_total < 0
        or (
            state.atr is not None
            and (
                isinstance(state.atr, bool)
                or not isinstance(state.atr, (int, float))
                or not isfinite(state.atr)
                or state.atr < 0
            )
        )
        or (
            state.previous_close is not None
            and (
                not isinstance(state.previous_close, Decimal)
                or not state.previous_close.is_finite()
                or state.previous_close <= 0
            )
        )
    ):
        return False
    if state.count == 0:
        return (
            state.tr_total == 0.0
            and state.atr is None
            and state.previous_close is None
        )
    if state.previous_close is None:
        return False
    if state.count < period:
        return state.atr is None
    if state.count == period:
        if state.atr is None:
            return state.tr_total == 0.0
        return state.atr == state.tr_total / period
    return state.atr is not None and state.tr_total == 0.0


def _score_facts_are_valid(
    active: NewowCupHandleOverlay,
    state: CupHandleStateValue,
    profile: NewowTrendProfile,
) -> bool:
    breakdown = _finite_fact_values(active.score_breakdown, _SCORE_KEYS)
    if breakdown is None or active.score != sum(breakdown.values()):
        return False
    if breakdown["pretrend"] not in {10.0, 12.0, 15.0}:
        return False
    if breakdown["cup_geometry"] not in {15.0, 17.0, 19.0, 21.0, 23.0, 25.0}:
        return False
    if breakdown["u_shape_purity"] not in {
        2.0,
        4.0,
        6.0,
        8.0,
        10.0,
        12.0,
        14.0,
        16.0,
        18.0,
        20.0,
    }:
        return False
    body_score = sum(breakdown[key] for key in _SCORE_KEYS[:3])
    if body_score < profile.cup_forming_min_body_score:
        return False
    by_index = {snapshot.eligible_index: snapshot for snapshot in state.eligible_bars}
    required_body_indexes = range(
        active.left_rim.pivot_index, active.right_rim.pivot_index + 1
    )
    body_history_complete = all(index in by_index for index in required_body_indexes)
    history_may_be_truncated = (
        active.state == CupHandleState.WEAKENED
        and len(state.eligible_bars) == profile.cup_history_limit
    )
    if not body_history_complete and not history_may_be_truncated:
        return False
    if body_history_complete and not history_may_be_truncated:
        body_facts, _ = _body_facts(
            active.direction,
            active.left_rim,
            active.bottom,
            active.right_rim,
            by_index,
            profile,
        )
        if body_facts is None or any(
            breakdown[key] != float(body_facts.breakdown[key])
            for key in _SCORE_KEYS[:3]
        ):
            return False
    if active.state == CupHandleState.FORMING:
        return (
            breakdown["handle_quality"] == 0
            and breakdown["volume_structure"] == 0
            and active.score == body_score
            and active.score <= 60
            and not active.volume_facts
        )
    if breakdown["handle_quality"] not in {
        10.0,
        12.0,
        14.0,
        16.0,
        18.0,
        20.0,
    } or breakdown["volume_structure"] not in {6.0, 8.0, 10.0, 12.0, 14.0}:
        return False
    return profile.cup_ready_min_score <= active.score <= 94


def _ready_facts_are_valid(
    active: NewowCupHandleOverlay,
    state: CupHandleStateValue,
    profile: NewowTrendProfile,
) -> bool:
    handle = active.handle_extreme
    pivot_price = active.pivot_price
    if handle is None or pivot_price is None:
        return False
    right_price = _normal_fraction(active.direction, active.right_rim.price)
    left_price = _normal_fraction(active.direction, active.left_rim.price)
    bottom_price = _normal_fraction(active.direction, active.bottom.price)
    handle_price = _normal_fraction(active.direction, handle.price)
    handle_bars = handle.confirmed_index - active.right_rim.pivot_index
    handle_depth = right_price - handle_price
    right_leg = right_price - bottom_price
    cup_depth = (left_price + right_price) / 2 - bottom_price
    depth_pct = handle_depth / abs(right_price) if right_price else None
    handle_retrace = handle_depth / right_leg if right_leg else None
    if (
        right_leg <= 0
        or cup_depth <= 0
        or not profile.cup_handle_min_bars
        <= handle_bars
        <= profile.cup_handle_max_bars
        or handle_depth <= 0
        or depth_pct is None
        or depth_pct > _rational_parameter(profile.cup_handle_depth_max_pct)
        or handle_retrace is None
        or _decimal_ratio_exceeds(
            handle_depth,
            right_leg,
            profile.cup_handle_retrace_max_ratio,
        )
        or handle_price
        < bottom_price
        + _rational_parameter(profile.cup_handle_upper_half_ratio) * cup_depth
    ):
        return False
    length_score = 6.0 if 7 <= handle_bars <= 10 else 4.0
    depth_score = (
        5.0
        if depth_pct <= Fraction(8, 100)
        else 3.0
        if depth_pct <= Fraction(12, 100)
        else 1.0
    )
    retrace_score = (
        5.0
        if handle_retrace <= Fraction(20, 100)
        else 3.0
        if handle_retrace <= Fraction(28, 100)
        else 1.0
    )
    if float(active.score_breakdown["handle_quality"]) != (
        length_score + depth_score + retrace_score + 4.0
    ):
        return False

    volumes = _finite_fact_values(active.volume_facts, _VOLUME_FACT_KEYS)
    if volumes is None:
        return False
    right_volume = Decimal(str(volumes["right_leg_median"]))
    handle_volume = Decimal(str(volumes["handle_median"]))
    baseline_volume = Decimal(str(volumes["handle_baseline_median"]))
    right_ratio = Decimal(str(volumes["handle_right_ratio"]))
    baseline_ratio = Decimal(str(volumes["handle_baseline_ratio"]))
    if (
        right_volume <= 0
        or handle_volume < 0
        or baseline_volume <= 0
        or _decimal_ratio_exceeds(
            right_ratio,
            Decimal(1),
            profile.cup_handle_right_volume_max_ratio,
        )
        or _decimal_ratio_exceeds(
            baseline_ratio,
            Decimal(1),
            profile.cup_handle_baseline_volume_max_ratio,
        )
    ):
        return False
    right_volume_score = (
        7.0
        if right_ratio <= Decimal("0.65")
        else 5.0
        if right_ratio <= Decimal("0.75")
        else 3.0
    )
    baseline_volume_score = (
        7.0
        if baseline_ratio <= Decimal("0.75")
        else 5.0
        if baseline_ratio <= Decimal("0.85")
        else 3.0
    )
    if float(active.score_breakdown["volume_structure"]) != (
        right_volume_score + baseline_volume_score
    ):
        return False

    by_index = {snapshot.eligible_index: snapshot for snapshot in state.eligible_bars}
    pivot_indexes = range(active.right_rim.pivot_index + 1, handle.confirmed_index)
    if all(index in by_index for index in pivot_indexes):
        pivot_window = [by_index[index] for index in pivot_indexes]
        if not pivot_window:
            return False
        expected_pivot = (
            max(snapshot.bar.high for snapshot in pivot_window)
            if active.direction == CupHandleDirection.BULLISH
            else min(snapshot.bar.low for snapshot in pivot_window)
        )
        if pivot_price != expected_pivot:
            return False
    right_indexes = range(
        active.bottom.pivot_index + 1, active.right_rim.pivot_index + 1
    )
    handle_indexes = range(active.right_rim.pivot_index + 1, handle.confirmed_index)
    baseline_indexes = range(
        active.right_rim.pivot_index - 19, active.right_rim.pivot_index + 1
    )
    all_volume_indexes = (*right_indexes, *handle_indexes, *baseline_indexes)
    if all(index in by_index for index in all_volume_indexes):
        expected_right = _median_volume([by_index[index] for index in right_indexes])
        expected_handle = _median_volume(
            [by_index[index] for index in handle_indexes]
        )
        expected_baseline = _median_volume(
            [by_index[index] for index in baseline_indexes]
        )
        expected_facts = (
            _float_volume_facts(expected_right, expected_handle, expected_baseline)
            if expected_right is not None
            and expected_handle is not None
            and expected_baseline is not None
            else None
        )
        if (
            expected_right is None
            or expected_handle is None
            or expected_baseline is None
            or expected_facts is None
            or dict(active.volume_facts) != expected_facts
            or _decimal_ratio_exceeds(
                expected_handle,
                expected_right,
                profile.cup_handle_right_volume_max_ratio,
            )
            or _decimal_ratio_exceeds(
                expected_handle,
                expected_baseline,
                profile.cup_handle_baseline_volume_max_ratio,
            )
        ):
            return False
    return True


def _milestones_are_authentic(
    active: NewowCupHandleOverlay,
    state: CupHandleStateValue,
    profile: NewowTrendProfile,
) -> bool:
    milestones = state.emitted_milestones
    milestone_facts = state.emitted_milestone_facts
    if state.physical_contract is None or state.segment_id is None:
        return False
    if len(milestones) != len(milestone_facts) or milestones != tuple(
        fact.marker_id for fact in milestone_facts
    ):
        return False
    if active.state == CupHandleState.FORMING:
        expected_types: tuple[NewowMarkerType, ...] = ()
    elif active.state == CupHandleState.READY:
        expected_types = (NewowMarkerType.CUP_HANDLE_READY,)
    elif active.state == CupHandleState.BREAKOUT:
        expected_types = (
            NewowMarkerType.CUP_HANDLE_READY,
            NewowMarkerType.CUP_HANDLE_BREAKOUT,
        )
    elif active.state == CupHandleState.WEAKENED:
        expected_types = (
            NewowMarkerType.CUP_HANDLE_READY,
            NewowMarkerType.CUP_HANDLE_BREAKOUT,
            NewowMarkerType.CUP_HANDLE_WEAKENED,
        )
    else:
        return False
    if tuple(fact.marker_type for fact in milestone_facts) != expected_types:
        return False

    by_index = {snapshot.eligible_index: snapshot for snapshot in state.eligible_bars}
    first_retained = state.eligible_bars[0] if state.eligible_bars else None
    previous_fact: CupMilestoneFact | None = None
    for fact in milestone_facts:
        if (
            not isinstance(fact, CupMilestoneFact)
            or not isinstance(fact.fact_id, str)
            or not fact.fact_id
            or not isinstance(fact.marker_type, NewowMarkerType)
            or not isinstance(fact.marker_id, str)
            or not isinstance(fact.bar_end, datetime)
            or fact.bar_end.tzinfo is None
            or fact.bar_end.utcoffset() is None
            or not isinstance(fact.eligible_index, int)
            or isinstance(fact.eligible_index, bool)
            or fact.eligible_index < 0
            or fact.eligible_index > state.pivot_tracker.eligible_index
            or not isinstance(fact.source_identity, str)
            or not fact.source_identity
            or fact.marker_id
            != _marker_identity(
                active.candidate_id,
                fact.marker_type,
                fact.bar_end,
            )
            or fact.fact_id
            != _milestone_fact_identity(
                active.candidate_id,
                fact.marker_id,
                fact.marker_type,
                fact.bar_end,
                fact.eligible_index,
                fact.source_identity,
                state.physical_contract,
                state.segment_id,
            )
        ):
            return False
        retained = by_index.get(fact.eligible_index)
        if retained is not None:
            if (
                retained.bar.bar_end != fact.bar_end
                or retained.bar.source_identity != fact.source_identity
            ):
                return False
        elif first_retained is not None and (
            fact.eligible_index >= first_retained.eligible_index
            or fact.bar_end >= first_retained.bar.bar_end
        ):
            return False
        if previous_fact is not None and (
            fact.eligible_index < previous_fact.eligible_index
            or fact.bar_end < previous_fact.bar_end
            or (
                fact.eligible_index == previous_fact.eligible_index
                and fact.bar_end != previous_fact.bar_end
            )
        ):
            return False
        previous_fact = fact

    if active.state == CupHandleState.FORMING:
        return not milestones
    ready_fact = milestone_facts[0]
    if ready_fact.bar_end != active.confirmed_at:
        return False
    if active.state == CupHandleState.READY:
        return True

    breakout_fact = milestone_facts[1]
    breakout_snapshot = by_index.get(breakout_fact.eligible_index)
    breakout_history_complete = all(
        index in by_index
        for index in range(
            breakout_fact.eligible_index - 20,
            breakout_fact.eligible_index + 1,
        )
    )
    if breakout_history_complete:
        assert breakout_snapshot is not None
        if (
            _breakout_facts(active, state.eligible_bars, breakout_snapshot, profile)[0]
            is None
        ):
            return False
    elif active.state == CupHandleState.BREAKOUT:
        return False
    if active.state == CupHandleState.BREAKOUT:
        return breakout_fact.bar_end == active.state_changed_at

    weakened_fact = milestone_facts[2]
    if (
        weakened_fact.bar_end != active.state_changed_at
        or weakened_fact.eligible_index <= breakout_fact.eligible_index
        or active.pivot_price is None
        or active.handle_extreme is None
    ):
        return False
    weakened_snapshot = by_index.get(weakened_fact.eligible_index)
    if weakened_snapshot is not None:
        normalized_close = _normal_fraction(
            active.direction, weakened_snapshot.bar.close
        )
        normalized_pivot = _normal_fraction(active.direction, active.pivot_price)
        normalized_handle = _normal_fraction(
            active.direction, active.handle_extreme.price
        )
        invalidation = normalized_handle - _rational_parameter(
            profile.cup_breakout_buffer_atr
        ) * Fraction(Decimal(str(weakened_snapshot.atr)))
        if not invalidation <= normalized_close < normalized_pivot:
            return False
    return True


def _active_candidate_is_coherent(
    active: NewowCupHandleOverlay,
    state: CupHandleStateValue,
    profile: NewowTrendProfile,
) -> bool:
    if (
        state.physical_contract is None
        or state.segment_id is None
        or not state.eligible_bars
        or not isinstance(active.direction, CupHandleDirection)
        or not isinstance(active.state, CupHandleState)
        or active.formula_version != profile.cup_handle_formula
        or active.handle_start_at != active.right_rim.pivot_at
        or active.candidate_id
        != _candidate_identity(
            active.direction,
            active.left_rim,
            active.bottom,
            active.right_rim,
            state.physical_contract,
            state.segment_id,
            active.formula_version,
        )
    ):
        return False
    anchors = [active.left_rim, active.bottom, active.right_rim]
    if active.handle_extreme is not None:
        anchors.append(active.handle_extreme)
    if any(
        anchor not in state.confirmed_pivots
        and (
            not state.confirmed_pivots
            or anchor.pivot_index >= state.confirmed_pivots[0].pivot_index
        )
        for anchor in anchors
    ):
        return False
    anchor_confirmed_at = max(anchor.confirmed_at for anchor in anchors[:3])
    if (
        active.first_seen_at < anchor_confirmed_at
        or active.confirmed_at > state.eligible_bars[-1].bar.bar_end
        or active.first_seen_at > state.eligible_bars[-1].bar.bar_end
        or active.state_changed_at > state.eligible_bars[-1].bar.bar_end
    ):
        return False
    if active.state == CupHandleState.FORMING:
        if (
            active.handle_extreme is not None
            or active.pivot_price is not None
            or active.pivot_frozen_at is not None
            or active.confirmed_at != anchor_confirmed_at
            or active.first_seen_at < active.confirmed_at
            or active.state_changed_at != active.first_seen_at
        ):
            return False
    else:
        handle = active.handle_extreme
        if (
            handle is None
            or active.confirmed_at < max(anchor_confirmed_at, handle.confirmed_at)
            or active.first_seen_at > active.confirmed_at
            or active.pivot_frozen_at != active.confirmed_at
            or active.state_changed_at < active.confirmed_at
            or (
                active.state == CupHandleState.READY
                and active.state_changed_at != active.confirmed_at
            )
        ):
            return False
    return (
        _score_facts_are_valid(active, state, profile)
        and (
            active.state == CupHandleState.FORMING
            or _ready_facts_are_valid(active, state, profile)
        )
        and _milestones_are_authentic(active, state, profile)
    )


def _state_is_valid(state: CupHandleStateValue, profile: NewowTrendProfile) -> bool:
    if not _atr_state_is_valid(state.atr_state, profile.cup_atr_period) or not isinstance(
        state.pivot_tracker, CupPivotTrackerState
    ):
        return False
    if (state.physical_contract is None) != (state.segment_id is None):
        return False
    if (
        state.physical_contract is not None
        and (
            not isinstance(state.physical_contract, str)
            or not state.physical_contract
            or not isinstance(state.segment_id, str)
            or not state.segment_id
        )
    ):
        return False
    if not isinstance(state.eligible_started, bool):
        return False
    if state.pivot_tracker.leg not in {"SEEK_DIRECTION", "UP_LEG", "DOWN_LEG"}:
        return False
    if state.pivot_tracker.eligible_index < -1:
        return False
    if (
        not isinstance(state.eligible_bars, tuple)
        or len(state.eligible_bars) > profile.cup_history_limit
        or not isinstance(state.confirmed_pivots, tuple)
        or len(state.confirmed_pivots) > profile.cup_max_confirmed_pivots
        or not isinstance(state.emitted_milestones, tuple)
        or len(state.emitted_milestones) > 3
        or not all(isinstance(marker_id, str) and marker_id for marker_id in state.emitted_milestones)
        or not isinstance(state.emitted_milestone_facts, tuple)
        or len(state.emitted_milestone_facts) > 3
        or not isinstance(state.recent_terminal_candidate_ids, tuple)
        or len(state.recent_terminal_candidate_ids) > profile.cup_recent_terminal_ids_limit
        or len(set(state.recent_terminal_candidate_ids))
        != len(state.recent_terminal_candidate_ids)
        or not all(
            isinstance(candidate_id, str) and candidate_id
            for candidate_id in state.recent_terminal_candidate_ids
        )
    ):
        return False
    if (state.atr_state.atr is None or state.atr_state.atr <= 0) and (
        state.eligible_bars
        or state.confirmed_pivots
        or state.active_candidate is not None
        or state.emitted_milestones
        or state.emitted_milestone_facts
        or state.ready_witness is not None
        or state.pivot_tracker.leg != "SEEK_DIRECTION"
        or state.pivot_tracker.extreme_high is not None
        or state.pivot_tracker.extreme_low is not None
        or state.pivot_tracker.last_pivot is not None
    ):
        return False
    by_index: dict[int, CupBarSnapshot] = {}
    previous_snapshot: CupBarSnapshot | None = None
    for snapshot in state.eligible_bars:
        if (
            not _snapshot_observable_facts_are_valid(snapshot, state)
            or (
                previous_snapshot is not None
                and (
                    snapshot.eligible_index
                    != previous_snapshot.eligible_index + 1
                    or snapshot.bar.bar_end <= previous_snapshot.bar.bar_end
                    or snapshot.bar.trading_day
                    <= previous_snapshot.bar.trading_day
                )
            )
            or snapshot.eligible_index > state.pivot_tracker.eligible_index
        ):
            return False
        previous_snapshot = snapshot
        by_index[snapshot.eligible_index] = snapshot
    if state.eligible_bars and state.atr_state.atr is not None and (
        state.atr_state.previous_close != state.eligible_bars[-1].bar.close
    ):
        return False
    previous_pivot: CupPivot | None = None
    latest_retained_at = (
        state.eligible_bars[-1].bar.bar_end if state.eligible_bars else None
    )
    for pivot in state.confirmed_pivots:
        if (
            not isinstance(pivot, CupPivot)
            or not isinstance(pivot.kind, CupPivotKind)
            or not isinstance(pivot.price, Decimal)
            or not pivot.price.is_finite()
            or pivot.price <= 0
            or not isinstance(pivot.pivot_at, datetime)
            or pivot.pivot_at.tzinfo is None
            or pivot.pivot_at.utcoffset() is None
            or not isinstance(pivot.confirmed_at, datetime)
            or pivot.confirmed_at.tzinfo is None
            or pivot.confirmed_at.utcoffset() is None
            or type(pivot.pivot_index) is not int
            or type(pivot.confirmed_index) is not int
            or isinstance(pivot.atr_at_pivot, bool)
            or not isinstance(pivot.atr_at_pivot, (int, float))
            or not isfinite(pivot.atr_at_pivot)
            or pivot.atr_at_pivot <= 0
            or pivot.pivot_index < 0
            or pivot.confirmed_index < pivot.pivot_index
            or pivot.confirmed_at < pivot.pivot_at
            or (
                pivot.confirmed_index == pivot.pivot_index
                and pivot.confirmed_at != pivot.pivot_at
            )
            or latest_retained_at is None
            or pivot.pivot_at > latest_retained_at
            or pivot.confirmed_at > latest_retained_at
        ):
            return False
        if previous_pivot is not None and (
            pivot.kind == previous_pivot.kind
            or pivot.pivot_index <= previous_pivot.pivot_index
            or pivot.confirmed_index <= previous_pivot.confirmed_index
        ):
            return False
        if (
            pivot.confirmed_index < pivot.pivot_index
            or pivot.confirmed_index > state.pivot_tracker.eligible_index
        ):
            return False
        pivot_snapshot = by_index.get(pivot.pivot_index)
        if pivot_snapshot is not None:
            expected_price = (
                pivot_snapshot.bar.high
                if pivot.kind == CupPivotKind.HIGH
                else pivot_snapshot.bar.low
            )
            if (
                pivot.price != expected_price
                or pivot.pivot_at != pivot_snapshot.bar.bar_end
                or pivot.atr_at_pivot != pivot_snapshot.atr
            ):
                return False
        elif state.eligible_bars and (
            pivot.pivot_index >= state.eligible_bars[0].eligible_index
        ):
            return False
        confirmed_snapshot = by_index.get(pivot.confirmed_index)
        if confirmed_snapshot is not None:
            if pivot.confirmed_at != confirmed_snapshot.bar.bar_end:
                return False
        elif state.eligible_bars and (
            pivot.confirmed_index >= state.eligible_bars[0].eligible_index
        ):
            return False
        previous_pivot = pivot
    for extreme in (
        state.pivot_tracker.extreme_high,
        state.pivot_tracker.extreme_low,
    ):
        if extreme is None:
            continue
        if (
            not _snapshot_observable_facts_are_valid(extreme, state)
            or extreme.eligible_index > state.pivot_tracker.eligible_index
        ):
            return False
        retained_extreme = by_index.get(extreme.eligible_index)
        if retained_extreme is not None:
            if extreme != retained_extreme:
                return False
            continue
        if not state.eligible_bars:
            return False
        first_retained = state.eligible_bars[0]
        if (
            extreme.eligible_index >= first_retained.eligible_index
            or extreme.bar.bar_end >= first_retained.bar.bar_end
            or extreme.bar.trading_day >= first_retained.bar.trading_day
        ):
            return False
    if not _tracker_is_coherent(state, profile, by_index):
        return False
    active = state.active_candidate
    if active is not None and (
        not isinstance(active, NewowCupHandleOverlay)
        or active.state
        not in {
            CupHandleState.FORMING,
            CupHandleState.READY,
            CupHandleState.BREAKOUT,
            CupHandleState.WEAKENED,
        }
        or active.candidate_id in state.recent_terminal_candidate_ids
    ):
        return False
    if active is not None:
        try:
            if not _active_candidate_is_coherent(active, state, profile):
                return False
        except (ArithmeticError, AttributeError, TypeError, ValueError):
            return False
    if active is None and (
        state.emitted_milestones
        or state.emitted_milestone_facts
        or state.ready_witness is not None
    ):
        return False
    if active is not None:
        if active.state == CupHandleState.FORMING:
            if state.ready_witness is not None:
                return False
        elif not _ready_witness_is_valid(active, state.ready_witness):
            return False
    return True


def _next_atr(state: WilderAtrState, bar: NewowDailyBar, period: int) -> WilderAtrState:
    previous_close = state.previous_close
    try:
        tr_decimal = max(
            bar.high - bar.low,
            abs(bar.high - previous_close)
            if previous_close is not None
            else Decimal(0),
            abs(bar.low - previous_close)
            if previous_close is not None
            else Decimal(0),
        )
    except ArithmeticError:
        return WilderAtrState(period, 0.0, None, bar.close)
    tr = _safe_finite_float(tr_decimal)
    if tr is None:
        return WilderAtrState(period, 0.0, None, bar.close)
    if state.atr is None and state.count == period and state.tr_total == 0.0:
        return WilderAtrState(1, tr, None, bar.close)
    count = state.count + 1
    if state.atr is None and count < period:
        total = state.tr_total + tr
        if not isfinite(total):
            return WilderAtrState(period, 0.0, None, bar.close)
        return WilderAtrState(count, total, None, bar.close)
    if state.atr is None:
        total = state.tr_total + tr
        atr = total / period
        if not isfinite(total) or not isfinite(atr):
            return WilderAtrState(period, 0.0, None, bar.close)
        return WilderAtrState(count, total, atr, bar.close)
    atr = ((period - 1) * state.atr + tr) / period
    if not isfinite(atr):
        return WilderAtrState(period, 0.0, None, bar.close)
    return WilderAtrState(count, 0.0, atr, bar.close)


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


def _with_tracker_index(
    tracker: CupPivotTrackerState, eligible_index: int
) -> CupPivotTrackerState:
    return replace(tracker, eligible_index=eligible_index)


def _track_pivot(
    tracker: CupPivotTrackerState,
    snapshot: CupBarSnapshot,
    reversal: float,
    min_leg: int,
) -> tuple[CupPivotTrackerState, CupPivot | None]:
    high = tracker.extreme_high
    low = tracker.extreme_low
    if high is None or snapshot.bar.high > high.bar.high:
        high = snapshot
    if low is None or snapshot.bar.low < low.bar.low:
        low = snapshot

    if tracker.leg == "SEEK_DIRECTION":
        assert high is not None and low is not None
        up_distance = Fraction(snapshot.bar.close) - Fraction(low.bar.low)
        down_distance = Fraction(high.bar.high) - Fraction(snapshot.bar.close)
        reversal_value = _rational_parameter(reversal)
        low_atr = Fraction(Decimal(str(low.atr)))
        high_atr = Fraction(Decimal(str(high.atr)))
        up = (
            snapshot.eligible_index - low.eligible_index >= min_leg
            and up_distance >= reversal_value * low_atr
        )
        down = (
            snapshot.eligible_index - high.eligible_index >= min_leg
            and down_distance >= reversal_value * high_atr
        )
        if not up and not down:
            return CupPivotTrackerState(
                "SEEK_DIRECTION", high, low, None, snapshot.eligible_index
            ), None
        choose_up = False
        if up and not down:
            choose_up = True
        elif up and down:
            normalized_up = up_distance * high_atr
            normalized_down = down_distance * low_atr
            if normalized_up != normalized_down:
                choose_up = normalized_up > normalized_down
            elif low.bar.bar_end != high.bar.bar_end:
                choose_up = low.bar.bar_end < high.bar.bar_end
            else:
                choose_up = False
        if choose_up:
            confirmed = _pivot(CupPivotKind.LOW, low, snapshot)
            return CupPivotTrackerState(
                "UP_LEG", snapshot, low, confirmed, snapshot.eligible_index
            ), confirmed
        confirmed = _pivot(CupPivotKind.HIGH, high, snapshot)
        return CupPivotTrackerState(
            "DOWN_LEG", high, snapshot, confirmed, snapshot.eligible_index
        ), confirmed

    if tracker.leg == "UP_LEG":
        assert high is not None
        leg_start = tracker.last_pivot.pivot_index if tracker.last_pivot else 0
        leg_bars = high.eligible_index - leg_start
        reversed_enough = (
            Fraction(high.bar.high) - Fraction(snapshot.bar.close)
            >= _rational_parameter(reversal) * Fraction(Decimal(str(high.atr)))
        )
        if leg_bars >= min_leg and reversed_enough:
            confirmed = _pivot(CupPivotKind.HIGH, high, snapshot)
            return CupPivotTrackerState(
                "DOWN_LEG", high, snapshot, confirmed, snapshot.eligible_index
            ), confirmed
        return CupPivotTrackerState(
            "UP_LEG", high, low, tracker.last_pivot, snapshot.eligible_index
        ), None

    assert tracker.leg == "DOWN_LEG" and low is not None
    leg_start = tracker.last_pivot.pivot_index if tracker.last_pivot else 0
    leg_bars = low.eligible_index - leg_start
    reversed_enough = (
        Fraction(snapshot.bar.close) - Fraction(low.bar.low)
        >= _rational_parameter(reversal) * Fraction(Decimal(str(low.atr)))
    )
    if leg_bars >= min_leg and reversed_enough:
        confirmed = _pivot(CupPivotKind.LOW, low, snapshot)
        return CupPivotTrackerState(
            "UP_LEG", snapshot, low, confirmed, snapshot.eligible_index
        ), confirmed
    return CupPivotTrackerState(
        "DOWN_LEG", high, low, tracker.last_pivot, snapshot.eligible_index
    ), None


def _normal(direction: CupHandleDirection, value: Decimal) -> Decimal:
    return value if direction == CupHandleDirection.BULLISH else -value


def _normal_fraction(
    direction: CupHandleDirection, value: Decimal
) -> Fraction:
    normalized = Fraction(value)
    return normalized if direction == CupHandleDirection.BULLISH else -normalized


def _candidate_id(
    direction: CupHandleDirection,
    left: CupPivot,
    bottom: CupPivot,
    right: CupPivot,
    bar: NewowDailyBar,
    formula: str,
) -> str:
    return _candidate_identity(
        direction,
        left,
        bottom,
        right,
        bar.physical_contract,
        bar.segment_id,
        formula,
    )


def _ols_slope(values: list[Fraction]) -> Fraction:
    count = len(values)
    mean_x = Fraction(count - 1, 2)
    mean_y = sum(values, Fraction()) / count
    numerator = sum(
        (index - mean_x) * (value - mean_y)
        for index, value in enumerate(values)
    )
    denominator = sum((index - mean_x) ** 2 for index in range(count))
    return numerator / denominator if denominator else Fraction()


def _pretrend_score(
    direction: CupHandleDirection,
    left: CupPivot,
    by_index: Mapping[int, CupBarSnapshot],
    profile: NewowTrendProfile,
) -> float | None:
    sign = 1 if direction == CupHandleDirection.BULLISH else -1
    valid: list[tuple[Fraction, Fraction, int, Fraction, Fraction]] = []
    for window in range(profile.cup_pretrend_min_bars, profile.cup_pretrend_max_bars + 1):
        start_index = left.pivot_index - window
        indexes = range(start_index, left.pivot_index + 1)
        snapshots = [by_index[index] for index in indexes if index in by_index]
        if len(snapshots) != window + 1:
            continue
        close_start = Fraction(snapshots[0].bar.close)
        move = sign * (Fraction(left.price) - close_start)
        return_pct = move / close_start
        atr_median = median(item.atr for item in snapshots)
        move_atr = _decimal_over_fraction(move, atr_median)
        if move_atr is None:
            continue
        slope = _ols_slope(
            [sign * Fraction(item.bar.close) for item in snapshots]
        )
        return_strength = return_pct / _rational_parameter(
            profile.cup_pretrend_min_return
        )
        atr_strength = move_atr / _rational_parameter(
            profile.cup_pretrend_min_move_atr
        )
        if slope > 0 and (
            return_strength >= 1 or atr_strength >= 1
        ):
            valid.append(
                (
                    max(return_strength, atr_strength),
                    min(return_strength, atr_strength),
                    -window,
                    return_strength,
                    atr_strength,
                )
            )
    if not valid:
        return None
    _, _, _, return_strength, atr_strength = max(valid)
    if return_strength >= 1 and atr_strength >= 1:
        return 15.0
    passing_strength = max(return_strength, atr_strength)
    return 12.0 if passing_strength >= Fraction(3, 2) else 10.0


def _bottom_span(
    direction: CupHandleDirection,
    bottom: CupPivot,
    left_index: int,
    right_index: int,
    zone_top: Fraction,
    by_index: Mapping[int, CupBarSnapshot],
) -> int:
    if bottom.pivot_index not in by_index:
        return 0

    def inside(index: int) -> bool:
        snapshot = by_index.get(index)
        return (
            snapshot is not None
            and _normal_fraction(direction, snapshot.bar.close) <= zone_top
        )

    if not inside(bottom.pivot_index):
        return 0
    start = bottom.pivot_index
    end = bottom.pivot_index
    while start > left_index and inside(start - 1):
        start -= 1
    while end < right_index and inside(end + 1):
        end += 1
    return end - start + 1


def _midline_crossings(
    direction: CupHandleDirection,
    left_index: int,
    right_index: int,
    midline: Fraction,
    by_index: Mapping[int, CupBarSnapshot],
) -> int:
    previous_sign = 0
    crossings = 0
    for index in range(left_index, right_index + 1):
        snapshot = by_index.get(index)
        if snapshot is None:
            continue
        difference = _normal_fraction(direction, snapshot.bar.close) - midline
        sign = 1 if difference > 0 else -1 if difference < 0 else previous_sign
        if sign and previous_sign and sign != previous_sign:
            crossings += 1
        if sign:
            previous_sign = sign
    return crossings


def _body_facts(
    direction: CupHandleDirection,
    left: CupPivot,
    bottom: CupPivot,
    right: CupPivot,
    by_index: Mapping[int, CupBarSnapshot],
    profile: NewowTrendProfile,
) -> tuple[_BodyFacts | None, tuple[str, ...]]:
    diagnostics: list[str] = []
    cup_bars = right.pivot_index - left.pivot_index + 1
    if not profile.cup_min_bars <= cup_bars <= profile.cup_max_bars:
        return None, ("CUP_DURATION_OUT_OF_RANGE",)
    snapshots = [
        by_index[index]
        for index in range(left.pivot_index, right.pivot_index + 1)
        if index in by_index
    ]
    if len(snapshots) != cup_bars:
        return None, ("CUP_HISTORY_INSUFFICIENT",)
    pretrend = _pretrend_score(direction, left, by_index, profile)
    if pretrend is None:
        diagnostics.append("PRETREND_NOT_CONFIRMED")

    left_price = _normal_fraction(direction, left.price)
    bottom_price = _normal_fraction(direction, bottom.price)
    right_price = _normal_fraction(direction, right.price)
    rim_price = (left_price + right_price) / 2
    cup_depth = rim_price - bottom_price
    atr_median = median(item.atr for item in snapshots)
    if cup_depth <= 0 or rim_price == 0:
        diagnostics.append("CUP_DEPTH_BELOW_10_PERCENT")
        return None, _unique(diagnostics)
    cup_depth_pct = cup_depth / abs(rim_price)
    cup_depth_atr = _decimal_over_fraction(cup_depth, atr_median)
    rim_gap = abs(left_price - right_price)
    rim_gap_pct = rim_gap / abs(rim_price)
    rim_gap_atr = _decimal_over_fraction(rim_gap, atr_median)
    if cup_depth_atr is None or rim_gap_atr is None:
        return None, _unique(diagnostics + ["CUP_ATR_UNAVAILABLE"])
    if cup_depth_pct < _rational_parameter(profile.cup_depth_min_pct):
        diagnostics.append("CUP_DEPTH_BELOW_10_PERCENT")
    if cup_depth_pct > _rational_parameter(profile.cup_depth_hard_max_pct):
        diagnostics.append("CUP_DEPTH_ABOVE_50_PERCENT")
    if cup_depth_atr < _rational_parameter(profile.cup_depth_min_atr):
        diagnostics.append("CUP_DEPTH_BELOW_3_ATR")
    if rim_gap_pct > _rational_parameter(profile.cup_rim_gap_max_pct):
        diagnostics.append("RIM_GAP_PERCENT_EXCEEDED")
    if rim_gap_atr > _rational_parameter(profile.cup_rim_gap_max_atr):
        diagnostics.append("RIM_GAP_ATR_EXCEEDED")

    zone_top = bottom_price + _rational_parameter(
        profile.cup_bottom_zone_ratio
    ) * cup_depth
    bottom_span = _bottom_span(
        direction,
        bottom,
        left.pivot_index,
        right.pivot_index,
        zone_top,
        by_index,
    )
    if bottom_span <= 1:
        diagnostics.append("V_BOTTOM_SINGLE_BAR")
    left_leg = bottom.pivot_index - left.pivot_index
    right_leg = right.pivot_index - bottom.pivot_index
    leg_ratio = Fraction(left_leg, right_leg) if right_leg else None
    if leg_ratio is None:
        diagnostics.append("LEG_RATIO_EXTREME")
    elif not _rational_parameter(
        profile.cup_leg_ratio_hard_min
    ) <= leg_ratio <= _rational_parameter(profile.cup_leg_ratio_hard_max):
        diagnostics.append("LEG_RATIO_EXTREME")
    crossings = _midline_crossings(
        direction,
        left.pivot_index,
        right.pivot_index,
        bottom_price + Fraction(1, 2) * cup_depth,
        by_index,
    )
    if crossings > profile.cup_midline_crossings_hard_max:
        diagnostics.append("MIDLINE_CROSSINGS_EXCEEDED")
    hard_diagnostics = [
        diagnostic
        for diagnostic in diagnostics
        if diagnostic != "V_BOTTOM_SINGLE_BAR"
    ]
    if hard_diagnostics:
        return None, _unique(diagnostics)
    assert pretrend is not None

    duration_score = 5.0 if 35 <= cup_bars <= 70 else 3.0
    depth_pct_score = (
        8.0
        if cup_depth_pct <= _rational_parameter(profile.cup_depth_preferred_max_pct)
        else 4.0
    )
    depth_atr_score = 5.0 if cup_depth_atr >= Fraction(4) else 3.0
    rim_score = (
        7.0
        if rim_gap_pct <= Fraction(25, 1000)
        and rim_gap_atr <= Fraction(3, 4)
        else 5.0
    )
    geometry = duration_score + depth_pct_score + depth_atr_score + rim_score
    span_score = (
        8.0
        if bottom_span >= 5
        else 6.0
        if bottom_span >= 3
        else 2.0
        if bottom_span == 2
        else 0.0
    )
    assert leg_ratio is not None
    if Fraction(75, 100) <= leg_ratio <= Fraction(133, 100):
        leg_score = 6.0
    elif _rational_parameter(
        profile.cup_leg_ratio_soft_min
    ) <= leg_ratio <= _rational_parameter(profile.cup_leg_ratio_soft_max):
        leg_score = 4.0
    else:
        leg_score = 2.0
    crossing_score = 6.0 if crossings <= 1 else 4.0 if crossings == 2 else 2.0 if crossings == 3 else 0.0
    u_shape = span_score + leg_score + crossing_score
    breakdown = {
        "pretrend": pretrend,
        "cup_geometry": geometry,
        "u_shape_purity": u_shape,
        "handle_quality": 0.0,
        "volume_structure": 0.0,
    }
    if sum(breakdown.values()) < profile.cup_forming_min_body_score:
        return None, _unique(diagnostics + ["CUP_FORMING_SCORE_INSUFFICIENT"])
    return _BodyFacts(breakdown, bottom_span), _unique(diagnostics)


def _body_candidates(
    pivots: tuple[CupPivot, ...],
    bars: tuple[CupBarSnapshot, ...],
    bar: NewowDailyBar,
    profile: NewowTrendProfile,
    terminal_ids: tuple[str, ...],
    previous: NewowCupHandleOverlay | None,
) -> tuple[list[tuple[NewowCupHandleOverlay, _BodyFacts]], tuple[str, ...], int, bool]:
    checks = 0
    diagnostics: list[str] = []
    candidates: list[tuple[NewowCupHandleOverlay, _BodyFacts]] = []
    by_index = {snapshot.eligible_index: snapshot for snapshot in bars}
    for direction, rim_kind in (
        (CupHandleDirection.BULLISH, CupPivotKind.HIGH),
        (CupHandleDirection.BEARISH, CupPivotKind.LOW),
    ):
        rims = [pivot for pivot in pivots if pivot.kind == rim_kind]
        for left_position, left in enumerate(rims):
            for right in rims[left_position + 1 :]:
                if checks == profile.cup_max_candidate_checks_per_step:
                    diagnostics.append("CUP_CANDIDATE_LIMIT_EXCEEDED")
                    return candidates, _unique(diagnostics), checks, True
                checks += 1
                cup_bars = right.pivot_index - left.pivot_index + 1
                if not profile.cup_min_bars <= cup_bars <= profile.cup_max_bars:
                    diagnostics.append("CUP_DURATION_OUT_OF_RANGE")
                    continue
                bottoms = [
                    pivot
                    for pivot in pivots
                    if pivot.kind != rim_kind
                    and left.pivot_index < pivot.pivot_index < right.pivot_index
                ]
                if not bottoms:
                    continue
                bottom = min(
                    bottoms,
                    key=lambda pivot: (_normal(direction, pivot.price), pivot.pivot_index),
                )
                candidate_id = _candidate_id(
                    direction, left, bottom, right, bar, profile.cup_handle_formula
                )
                if candidate_id in terminal_ids:
                    continue
                facts, failures = _body_facts(
                    direction, left, bottom, right, by_index, profile
                )
                diagnostics.extend(failures)
                if facts is None:
                    continue
                first_seen = bar.bar_end
                state_changed = bar.bar_end
                if previous is not None and previous.candidate_id == candidate_id:
                    first_seen = previous.first_seen_at
                    state_changed = previous.state_changed_at
                overlay = NewowCupHandleOverlay(
                    candidate_id=candidate_id,
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
                    first_seen_at=first_seen,
                    state_changed_at=state_changed,
                    score=sum(facts.breakdown.values()),
                    score_breakdown=facts.breakdown,
                    hard_failures=(),
                    diagnostics=(),
                    volume_facts={},
                    formula_version=profile.cup_handle_formula,
                )
                candidates.append((overlay, facts))
    return candidates, _unique(diagnostics), checks, False


def _median_volume(items: list[CupBarSnapshot]) -> Fraction | None:
    if not items:
        return None
    values = sorted(item.bar.volume for item in items)
    if not all(type(value) is int and value >= 0 for value in values):
        return None
    middle = len(values) // 2
    if len(values) % 2:
        return Fraction(values[middle])
    return Fraction(values[middle - 1] + values[middle], 2)


def _float_volume_facts(
    right_volume: Fraction,
    handle_volume: Fraction,
    baseline_volume: Fraction,
) -> dict[str, float] | None:
    if right_volume <= 0 or handle_volume < 0 or baseline_volume <= 0:
        return None
    exact = {
        "right_leg_median": right_volume,
        "handle_median": handle_volume,
        "handle_baseline_median": baseline_volume,
        "handle_right_ratio": handle_volume / right_volume,
        "handle_baseline_ratio": handle_volume / baseline_volume,
    }
    facts = {key: _safe_finite_float(value) for key, value in exact.items()}
    if any(value is None for value in facts.values()):
        return None
    return {key: value for key, value in facts.items() if value is not None}


def _ready_candidate(
    forming: NewowCupHandleOverlay,
    body_facts: _BodyFacts,
    pivots: tuple[CupPivot, ...],
    bars: tuple[CupBarSnapshot, ...],
    current: CupBarSnapshot,
    profile: NewowTrendProfile,
) -> tuple[NewowCupHandleOverlay | None, str | None]:
    reverse_kind = (
        CupPivotKind.LOW
        if forming.right_rim.kind == CupPivotKind.HIGH
        else CupPivotKind.HIGH
    )
    all_handles = [
        pivot
        for pivot in pivots
        if pivot.kind == reverse_kind and pivot.pivot_index > forming.right_rim.pivot_index
    ]
    handles = [
        pivot
        for pivot in all_handles
        if profile.cup_handle_min_bars
        <= pivot.confirmed_index - forming.right_rim.pivot_index
        <= profile.cup_handle_max_bars
    ]
    if not handles:
        return None, "HANDLE_DURATION_OUT_OF_RANGE" if all_handles else None
    handle = min(
        handles,
        key=lambda pivot: (_normal(forming.direction, pivot.price), -pivot.pivot_index),
    )
    if body_facts.bottom_span_bars < profile.cup_bottom_span_ready_min:
        return None, "BOTTOM_SPAN_BELOW_READY_MIN"
    right_price = _normal_fraction(forming.direction, forming.right_rim.price)
    left_price = _normal_fraction(forming.direction, forming.left_rim.price)
    bottom_price = _normal_fraction(forming.direction, forming.bottom.price)
    handle_price = _normal_fraction(forming.direction, handle.price)
    handle_depth = right_price - handle_price
    cup_right_leg = right_price - bottom_price
    cup_depth = (left_price + right_price) / 2 - bottom_price
    depth_pct = handle_depth / abs(right_price)
    if handle_depth <= 0 or depth_pct > _rational_parameter(
        profile.cup_handle_depth_max_pct
    ):
        return None, "HANDLE_DEPTH_EXCEEDED"
    if handle_price < bottom_price + _rational_parameter(
        profile.cup_handle_upper_half_ratio
    ) * cup_depth:
        return None, "HANDLE_BELOW_CUP_MID"
    handle_retrace = handle_depth / cup_right_leg
    if _decimal_ratio_exceeds(
        handle_depth,
        cup_right_leg,
        profile.cup_handle_retrace_max_ratio,
    ):
        return None, "HANDLE_RETRACE_EXCEEDED"
    by_index = {snapshot.eligible_index: snapshot for snapshot in bars}
    pivot_window = [
        by_index[index]
        for index in range(forming.right_rim.pivot_index + 1, handle.confirmed_index)
        if index in by_index
    ]
    if len(pivot_window) != handle.confirmed_index - forming.right_rim.pivot_index - 1:
        return None, "HANDLE_PIVOT_UNAVAILABLE"
    if not pivot_window:
        return None, "HANDLE_PIVOT_UNAVAILABLE"
    if forming.direction == CupHandleDirection.BULLISH:
        pivot_price = max(snapshot.bar.high for snapshot in pivot_window)
    else:
        pivot_price = min(snapshot.bar.low for snapshot in pivot_window)
    right_leg = [
        snapshot
        for snapshot in bars
        if forming.bottom.pivot_index
        < snapshot.eligible_index
        <= forming.right_rim.pivot_index
    ]
    handle_window = [
        snapshot
        for snapshot in bars
        if forming.right_rim.pivot_index
        < snapshot.eligible_index
        < handle.confirmed_index
    ]
    baseline_window = [
        snapshot
        for snapshot in bars
        if forming.right_rim.pivot_index - 19
        <= snapshot.eligible_index
        <= forming.right_rim.pivot_index
    ]
    if len(baseline_window) != 20:
        return None, "HANDLE_VOLUME_UNAVAILABLE"
    right_volume = _median_volume(right_leg)
    handle_volume = _median_volume(handle_window)
    baseline_volume = _median_volume(baseline_window)
    if (
        right_volume is None
        or handle_volume is None
        or baseline_volume is None
        or right_volume <= 0
        or baseline_volume <= 0
    ):
        return None, "HANDLE_VOLUME_UNAVAILABLE"
    right_ratio = handle_volume / right_volume
    baseline_ratio = handle_volume / baseline_volume
    volume_facts = _float_volume_facts(
        right_volume,
        handle_volume,
        baseline_volume,
    )
    if volume_facts is None:
        return None, "HANDLE_VOLUME_UNAVAILABLE"
    if (
        _decimal_ratio_exceeds(
            handle_volume,
            right_volume,
            profile.cup_handle_right_volume_max_ratio,
        )
        or _decimal_ratio_exceeds(
            handle_volume,
            baseline_volume,
            profile.cup_handle_baseline_volume_max_ratio,
        )
    ):
        return None, "HANDLE_VOLUME_NOT_CONTRACTING"

    handle_bars = handle.confirmed_index - forming.right_rim.pivot_index
    length_score = 6.0 if 7 <= handle_bars <= 10 else 4.0
    depth_score = (
        5.0
        if depth_pct <= Fraction(8, 100)
        else 3.0
        if depth_pct <= Fraction(12, 100)
        else 1.0
    )
    retrace_score = (
        5.0
        if handle_retrace <= Fraction(20, 100)
        else 3.0
        if handle_retrace <= Fraction(28, 100)
        else 1.0
    )
    handle_score = length_score + depth_score + retrace_score + 4.0
    right_volume_score = (
        7.0
        if right_ratio <= Fraction(65, 100)
        else 5.0
        if right_ratio <= Fraction(75, 100)
        else 3.0
    )
    baseline_volume_score = (
        7.0
        if baseline_ratio <= Fraction(75, 100)
        else 5.0
        if baseline_ratio <= Fraction(85, 100)
        else 3.0
    )
    breakdown = dict(forming.score_breakdown)
    breakdown["handle_quality"] = handle_score
    breakdown["volume_structure"] = right_volume_score + baseline_volume_score
    score = sum(breakdown.values())
    if score < profile.cup_ready_min_score:
        return None, "CUP_READY_SCORE_INSUFFICIENT"
    return (
        replace(
            forming,
            state=CupHandleState.READY,
            handle_extreme=handle,
            pivot_price=pivot_price,
            pivot_frozen_at=current.bar.bar_end,
            confirmed_at=current.bar.bar_end,
            state_changed_at=current.bar.bar_end,
            score=score,
            score_breakdown=breakdown,
            volume_facts=volume_facts,
        ),
        None,
    )


def _pivot_facts(pivot: CupPivot) -> Mapping[str, object]:
    return {
        "kind": pivot.kind.value,
        "price": str(pivot.price),
        "pivot_at": pivot.pivot_at.isoformat(),
        "confirmed_at": pivot.confirmed_at.isoformat(),
        "pivot_index": pivot.pivot_index,
        "confirmed_index": pivot.confirmed_index,
        "atr_at_pivot": pivot.atr_at_pivot,
    }


def _marker(
    overlay: NewowCupHandleOverlay,
    marker_type: NewowMarkerType,
    bar: NewowDailyBar,
    related: tuple[str, ...],
    state_before: CupHandleState,
    extra_facts: Mapping[str, object] | None = None,
) -> NewowMainMarker:
    marker_id = _marker_identity(overlay.candidate_id, marker_type, bar.bar_end)
    facts: dict[str, object] = {
        "candidate_id": overlay.candidate_id,
        "direction": overlay.direction.value,
        "state_before": state_before.value,
        "state_after": overlay.state.value,
        "left_rim": _pivot_facts(overlay.left_rim),
        "bottom": _pivot_facts(overlay.bottom),
        "right_rim": _pivot_facts(overlay.right_rim),
        "handle_extreme": (
            _pivot_facts(overlay.handle_extreme) if overlay.handle_extreme else None
        ),
        "pivot_price": str(overlay.pivot_price) if overlay.pivot_price else None,
        "score": overlay.score,
        "score_breakdown": dict(overlay.score_breakdown),
        "volume_facts": dict(overlay.volume_facts),
        "formula_version": overlay.formula_version,
    }
    if extra_facts:
        facts.update(extra_facts)
    return NewowMainMarker(
        marker_id=marker_id,
        marker_type=marker_type,
        bar_end=bar.bar_end,
        price=bar.close,
        label=marker_type.value,
        color_token="cup_handle",
        priority=100,
        related_marker_ids=related,
        trigger_facts=facts,
        formula_version=overlay.formula_version,
    )


def _primary_candidate(
    candidates: list[NewowCupHandleOverlay],
    breakout_candidate_ids: set[str] | None = None,
) -> NewowCupHandleOverlay | None:
    if not candidates:
        return None
    state_rank = {
        CupHandleState.FORMING: 1,
        CupHandleState.READY: 2,
        CupHandleState.BREAKOUT: 3,
    }
    return min(
        candidates,
        key=lambda candidate: (
            -(
                3
                if breakout_candidate_ids
                and candidate.candidate_id in breakout_candidate_ids
                else state_rank.get(candidate.state, 0)
            ),
            -candidate.score,
            -candidate.confirmed_at.timestamp(),
            candidate.candidate_id,
        ),
    )


def _breakout_facts(
    active: NewowCupHandleOverlay,
    bars: tuple[CupBarSnapshot, ...],
    current: CupBarSnapshot,
    profile: NewowTrendProfile,
) -> tuple[Mapping[str, object] | None, bool]:
    assert active.pivot_price is not None
    by_index = {snapshot.eligible_index: snapshot for snapshot in bars}
    previous = by_index.get(current.eligible_index - 1)
    if previous is None:
        return None, False
    pivot = _normal_fraction(active.direction, active.pivot_price)
    current_threshold = pivot + _rational_parameter(
        profile.cup_breakout_buffer_atr
    ) * Fraction(Decimal(str(current.atr)))
    previous_threshold = pivot + _rational_parameter(
        profile.cup_breakout_buffer_atr
    ) * Fraction(Decimal(str(previous.atr)))
    crossed = (
        _normal_fraction(active.direction, current.bar.close) > current_threshold
        and _normal_fraction(active.direction, previous.bar.close)
        <= previous_threshold
    )
    if not crossed:
        return None, False
    breakout_window = [
        by_index[index]
        for index in range(current.eligible_index - 20, current.eligible_index)
        if index in by_index
    ]
    baseline = _median_volume(breakout_window) if len(breakout_window) == 20 else None
    assert active.handle_extreme is not None
    handle_window = [
        by_index[index]
        for index in range(
            active.right_rim.pivot_index + 1,
            active.handle_extreme.confirmed_index,
        )
        if index in by_index
    ]
    expected_handle_bars = (
        active.handle_extreme.confirmed_index - active.right_rim.pivot_index - 1
    )
    handle_volume = (
        _median_volume(handle_window)
        if len(handle_window) == expected_handle_bars
        else None
    )
    if (
        baseline is None
        or baseline <= 0
        or handle_volume is None
        or handle_volume <= 0
    ):
        return None, True
    current_volume = Fraction(current.bar.volume)
    volume20_ratio = current_volume / baseline
    handle_ratio = current_volume / handle_volume
    if (
        _decimal_ratio_below(
            current_volume,
            baseline,
            profile.cup_breakout_volume20_min_ratio,
        )
        or _decimal_ratio_below(
            current_volume,
            handle_volume,
            profile.cup_breakout_handle_volume_min_ratio,
        )
    ):
        return None, True
    baseline_fact = _safe_finite_float(baseline)
    volume20_ratio_fact = _safe_finite_float(volume20_ratio)
    handle_ratio_fact = _safe_finite_float(handle_ratio)
    if (
        baseline_fact is None
        or volume20_ratio_fact is None
        or handle_ratio_fact is None
    ):
        return None, True
    full_score = active.score + 6.0
    if full_score < profile.cup_breakout_min_score:
        return None, True
    return {
        "full_score": full_score,
        "breakout_volume20_median": baseline_fact,
        "breakout_volume20_ratio": volume20_ratio_fact,
        "breakout_handle_volume_ratio": handle_ratio_fact,
    }, True


def step_cup_handle(
    state: CupHandleStateValue,
    bar: NewowDailyBar,
    *,
    profile: NewowTrendProfile = NEWOW_TREND_D1_V1,
) -> CupHandleStepResult:
    try:
        restored_state_valid = isinstance(
            state, CupHandleStateValue
        ) and _state_is_valid(state, profile)
    except (ArithmeticError, AttributeError, LookupError, TypeError, ValueError):
        restored_state_valid = False
    if not restored_state_valid:
        return CupHandleStepResult(
            initial_cup_handle_state(), None, (), ("NEWOW_CUP_STATE_INVALID",), 0
        )
    rollover = state.physical_contract is not None and (
        state.physical_contract != bar.physical_contract or state.segment_id != bar.segment_id
    )
    if rollover:
        state = initial_cup_handle_state()
    diagnostics = ["CUP_ROLLOVER_RESET"] if rollover else []
    atr_state = _next_atr(state.atr_state, bar, profile.cup_atr_period)
    tracker = state.pivot_tracker
    active = state.active_candidate
    bars = state.eligible_bars
    pivots = state.confirmed_pivots
    emitted = state.emitted_milestones
    milestone_facts = state.emitted_milestone_facts
    ready_witness = state.ready_witness
    terminals = state.recent_terminal_candidate_ids
    eligible_started = state.eligible_started
    atr_reseed_started = (
        atr_state.atr is None
        and atr_state.count == profile.cup_atr_period
        and atr_state.tr_total == 0.0
    )
    if atr_reseed_started:
        tracker = CupPivotTrackerState(eligible_index=tracker.eligible_index)
        active = None
        bars = ()
        pivots = ()
        emitted = ()
        milestone_facts = ()
        ready_witness = None
    if not bar.observation_eligible:
        next_state = CupHandleStateValue(
            atr_state,
            tracker,
            bars,
            pivots,
            active,
            emitted,
            terminals,
            bar.physical_contract,
            bar.segment_id,
            eligible_started,
            milestone_facts,
            ready_witness,
        )
        return CupHandleStepResult(next_state, active, (), tuple(diagnostics), 0)

    eligible_index = tracker.eligible_index + 1
    eligible_started = True
    if (
        atr_state.atr is None
        or not isfinite(atr_state.atr)
        or atr_state.atr <= 0
    ):
        tracker = _with_tracker_index(tracker, eligible_index)
        next_state = CupHandleStateValue(
            atr_state,
            tracker,
            bars,
            pivots,
            active,
            emitted,
            terminals,
            bar.physical_contract,
            bar.segment_id,
            eligible_started,
            milestone_facts,
            ready_witness,
        )
        return CupHandleStepResult(
            next_state, active, (), tuple(diagnostics + ["CUP_ATR_UNAVAILABLE"]), 0
        )

    snapshot = CupBarSnapshot(bar, eligible_index, atr_state.atr)
    bars = (bars + (snapshot,))[-profile.cup_history_limit :]
    tracker, pivot = _track_pivot(
        tracker, snapshot, profile.cup_reversal_atr, profile.cup_min_leg_bars
    )
    if pivot is not None and (not pivots or pivots[-1].kind != pivot.kind):
        pivots = (pivots + (pivot,))[-profile.cup_max_confirmed_pivots :]

    markers: list[NewowMainMarker] = []
    checks = 0
    result_overlay = active
    if active is None or active.state == CupHandleState.FORMING:
        body_candidates, candidate_diagnostics, checks, limit_exceeded = _body_candidates(
            pivots, bars, bar, profile, terminals, active
        )
        diagnostics.extend(candidate_diagnostics)
        if not limit_exceeded:
            evaluated: list[NewowCupHandleOverlay] = []
            breakout_candidate_ids: set[str] = set()
            for forming, body_facts in body_candidates:
                ready, reason = _ready_candidate(
                    forming, body_facts, pivots, bars, snapshot, profile
                )
                if reason:
                    diagnostics.append(reason)
                candidate = ready or forming
                evaluated.append(candidate)
                if ready is not None:
                    breakout_facts, _ = _breakout_facts(
                        ready, bars, snapshot, profile
                    )
                    if breakout_facts is not None:
                        breakout_candidate_ids.add(ready.candidate_id)
            active = _primary_candidate(evaluated, breakout_candidate_ids)
            if active is not None and active.state == CupHandleState.READY:
                ready_witness = _ready_witness(active)
                ready_marker = _marker(
                    active,
                    NewowMarkerType.CUP_HANDLE_READY,
                    bar,
                    (),
                    CupHandleState.FORMING,
                )
                markers.append(ready_marker)
                emitted = (ready_marker.marker_id,)
                milestone_facts = (
                    _milestone_fact(ready_marker, snapshot, active.candidate_id),
                )
            else:
                ready_witness = None
        result_overlay = active

    if active is not None and active.state in {
        CupHandleState.READY,
        CupHandleState.BREAKOUT,
        CupHandleState.WEAKENED,
    }:
        assert active.handle_extreme is not None and active.pivot_price is not None
        normalized_close = _normal_fraction(active.direction, bar.close)
        normalized_handle = _normal_fraction(
            active.direction, active.handle_extreme.price
        )
        normalized_pivot = _normal_fraction(active.direction, active.pivot_price)
        invalidation = normalized_handle - _rational_parameter(
            profile.cup_breakout_buffer_atr
        ) * Fraction(Decimal(str(snapshot.atr)))
        if normalized_close < invalidation:
            state_before = active.state
            terminal_overlay = replace(
                active,
                state=CupHandleState.INVALIDATED,
                state_changed_at=bar.bar_end,
            )
            marker = _marker(
                terminal_overlay,
                NewowMarkerType.CUP_HANDLE_INVALIDATED,
                bar,
                tuple(emitted),
                state_before,
            )
            markers.append(marker)
            emitted += (marker.marker_id,)
            terminals = (terminals + (active.candidate_id,))[
                -profile.cup_recent_terminal_ids_limit :
            ]
            result_overlay = terminal_overlay
            active = None
            emitted = ()
            milestone_facts = ()
            ready_witness = None
        elif active.state == CupHandleState.BREAKOUT and normalized_close < normalized_pivot:
            active = replace(
                active,
                state=CupHandleState.WEAKENED,
                state_changed_at=bar.bar_end,
            )
            marker = _marker(
                active,
                NewowMarkerType.CUP_HANDLE_WEAKENED,
                bar,
                tuple(emitted),
                CupHandleState.BREAKOUT,
            )
            markers.append(marker)
            emitted += (marker.marker_id,)
            milestone_facts += (
                _milestone_fact(marker, snapshot, active.candidate_id),
            )
            result_overlay = active
        elif active.state == CupHandleState.READY:
            breakout_facts, crossed = _breakout_facts(active, bars, snapshot, profile)
            if breakout_facts is not None:
                active = replace(
                    active,
                    state=CupHandleState.BREAKOUT,
                    state_changed_at=bar.bar_end,
                )
                marker = _marker(
                    active,
                    NewowMarkerType.CUP_HANDLE_BREAKOUT,
                    bar,
                    tuple(emitted),
                    CupHandleState.READY,
                    breakout_facts,
                )
                markers.append(marker)
                emitted += (marker.marker_id,)
                milestone_facts += (
                    _milestone_fact(marker, snapshot, active.candidate_id),
                )
                result_overlay = active
            elif crossed:
                diagnostics.append("BREAKOUT_VOLUME_UNCONFIRMED")
            if breakout_facts is None:
                ready_snapshot = next(
                    (
                        item
                        for item in bars
                        if item.bar.bar_end == active.confirmed_at
                    ),
                    None,
                )
                if (
                    ready_snapshot is not None
                    and snapshot.eligible_index - ready_snapshot.eligible_index
                    >= profile.cup_ready_expiry_bars
                ):
                    active = replace(
                        active,
                        state=CupHandleState.EXPIRED,
                        state_changed_at=bar.bar_end,
                    )
                    marker = _marker(
                        active,
                        NewowMarkerType.CUP_HANDLE_EXPIRED,
                        bar,
                        tuple(emitted),
                        CupHandleState.READY,
                    )
                    markers.append(marker)
                    emitted += (marker.marker_id,)
                    terminals = (terminals + (active.candidate_id,))[
                        -profile.cup_recent_terminal_ids_limit :
                    ]
                    result_overlay = active
                    active = None
                    emitted = ()
                    milestone_facts = ()
                    ready_witness = None
        elif active.state == CupHandleState.BREAKOUT:
            breakout_snapshot = next(
                (
                    item
                    for item in bars
                    if item.bar.bar_end == active.state_changed_at
                ),
                None,
            )
            if (
                breakout_snapshot is not None
                and snapshot.eligible_index - breakout_snapshot.eligible_index
                >= profile.cup_post_breakout_archive_bars
            ):
                terminals = (terminals + (active.candidate_id,))[
                    -profile.cup_recent_terminal_ids_limit :
                ]
                active = None
                result_overlay = None
                emitted = ()
                milestone_facts = ()
                ready_witness = None

    next_state = CupHandleStateValue(
        atr_state,
        tracker,
        bars,
        pivots,
        active,
        emitted,
        terminals,
        bar.physical_contract,
        bar.segment_id,
        eligible_started,
        milestone_facts,
        ready_witness,
    )
    return CupHandleStepResult(
        next_state, result_overlay, tuple(markers), _unique(diagnostics), checks
    )


def calculate_cup_handle_series(
    bars: tuple[NewowDailyBar, ...],
    *,
    profile: NewowTrendProfile = NEWOW_TREND_D1_V1,
) -> tuple[CupHandleStepResult, ...]:
    state = initial_cup_handle_state()
    results: list[CupHandleStepResult] = []
    for bar in bars:
        result = step_cup_handle(state, bar, profile=profile)
        results.append(result)
        state = result.state
    return tuple(results)
