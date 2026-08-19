from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, cast

from .domain import BarFrequency, CanonicalBar, normalize_contract_for_symbol
from .subing_calibration import SubingCalibration
from .subing_lifecycle_policy import SubingLifecyclePolicy
from .subing_research import (
    MacdCross,
    SubingSignalEvaluation,
    SubingSignalStatus,
    SubingDirection,
    SubingFactorResult,
    SubingFactorSnapshot,
    SubingFactorStatus,
    evaluate_subing_signal,
    resolve_same_boundary_subing_signals,
)
from .subing_structure import (
    BreakoutAssessment,
    ConfirmedPivot,
    PivotKind,
    assess_pivot_breakout,
    assess_pivot_retest,
    confirmed_pivots,
)


class _SignalCalibrationView(Protocol):
    calibration_id: str | None
    accepted_timeframes: frozenset[BarFrequency]
    slope_flat_threshold_bps_per_bar: Mapping[BarFrequency, Decimal]


class LifecycleAvailability(StrEnum):
    READY = "ready"
    UNAVAILABLE = "unavailable"


class LifecycleStage(StrEnum):
    IDLE = "idle"
    SETUP_ARMED = "setup_armed"
    ENTRY_CONFIRMED = "entry_confirmed"
    CONTINUATION = "continuation"
    EXIT_RISK = "exit_risk"
    CLOSED = "closed"


class EntryProgress(StrEnum):
    WAITING_TRIGGER = "waiting_trigger"
    HOLD_CONFIRMING = "hold_confirming"
    RETEST_CONFIRMING = "retest_confirming"


class ConfirmationSource(StrEnum):
    FORMAL_V1 = "formal_v1"
    MOMENTUM_HOLD = "momentum_hold"
    PIVOT_BREAK_HOLD = "pivot_break_hold"
    PIVOT_RETEST_REBREAK = "pivot_retest_rebreak"


class SubingLifecycleStateError(ValueError):
    code = "SUBING_LIFECYCLE_STATE_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class SubingOpportunityKey:
    policy_id: str
    symbol: str
    contract: str
    segment_start_trading_day: date
    direction: SubingDirection
    origin_at: datetime

    def __post_init__(self) -> None:
        if (
            not isinstance(self.policy_id, str)
            or not self.policy_id.strip()
            or not isinstance(self.symbol, str)
            or not self.symbol.strip()
            or not isinstance(self.contract, str)
            or not self.contract.strip()
            or type(self.segment_start_trading_day) is not date
            or not isinstance(self.direction, SubingDirection)
            or self.direction not in {SubingDirection.LONG, SubingDirection.SHORT}
            or not isinstance(self.origin_at, datetime)
            or self.origin_at.tzinfo is None
            or self.origin_at.utcoffset() is None
        ):
            raise ValueError("SUBING_OPPORTUNITY_KEY_INVALID")


@dataclass(frozen=True, slots=True)
class SubingLifecycleState:
    availability: LifecycleAvailability
    direction: SubingDirection
    stage: LifecycleStage
    opportunity_key: SubingOpportunityKey | None = None
    entry_progress: EntryProgress | None = None
    confirmation_source: ConfirmationSource | None = None
    confirmed_at: datetime | None = None

    def __post_init__(self) -> None:
        invalid_type = (
            not isinstance(self.availability, LifecycleAvailability)
            or not isinstance(self.direction, SubingDirection)
            or not isinstance(self.stage, LifecycleStage)
            or (
                self.opportunity_key is not None
                and not isinstance(self.opportunity_key, SubingOpportunityKey)
            )
            or (
                self.entry_progress is not None
                and not isinstance(self.entry_progress, EntryProgress)
            )
            or (
                self.confirmation_source is not None
                and not isinstance(self.confirmation_source, ConfirmationSource)
            )
            or (self.confirmed_at is not None and not isinstance(self.confirmed_at, datetime))
        )
        if invalid_type:
            raise SubingLifecycleStateError()

        directional = self.direction in {
            SubingDirection.LONG,
            SubingDirection.SHORT,
        }
        has_matching_key = (
            isinstance(self.opportunity_key, SubingOpportunityKey)
            and self.opportunity_key.direction is self.direction
        )
        has_aware_confirmation_time = (
            isinstance(self.confirmed_at, datetime)
            and self.confirmed_at.tzinfo is not None
            and self.confirmed_at.utcoffset() is not None
        )
        invalid = self.confirmed_at is not None and not has_aware_confirmation_time
        if (
            has_aware_confirmation_time
            and isinstance(self.confirmed_at, datetime)
            and isinstance(self.opportunity_key, SubingOpportunityKey)
            and self.confirmed_at is not None
            and self.confirmed_at < self.opportunity_key.origin_at
        ):
            invalid = True
        if self.stage is LifecycleStage.IDLE:
            invalid = invalid or any(
                (
                    self.direction is not SubingDirection.NONE,
                    self.opportunity_key is not None,
                    self.entry_progress is not None,
                    self.confirmation_source is not None,
                    self.confirmed_at is not None,
                )
            )
        elif self.stage is LifecycleStage.SETUP_ARMED:
            invalid = invalid or not directional or not has_matching_key
            invalid = (
                invalid
                or self.entry_progress is None
                or self.confirmation_source is not None
                or self.confirmed_at is not None
            )
        elif self.stage in {
            LifecycleStage.ENTRY_CONFIRMED,
            LifecycleStage.CONTINUATION,
            LifecycleStage.EXIT_RISK,
        }:
            invalid = invalid or not directional or not has_matching_key
            invalid = (
                invalid
                or self.entry_progress is not None
                or self.confirmation_source is None
                or not has_aware_confirmation_time
            )
        else:
            invalid = invalid or not directional or not has_matching_key
            invalid = invalid or self.entry_progress is not None
            invalid = invalid or (
                (self.confirmation_source is None) != (self.confirmed_at is None)
            )

        if invalid:
            raise SubingLifecycleStateError()


@dataclass(frozen=True, slots=True)
class SubingLifecycleTransition:
    transition_id: str
    opportunity_key: SubingOpportunityKey
    transition_at: datetime
    from_stage: LifecycleStage
    to_stage: LifecycleStage
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SubingLifecycleSnapshot:
    formula_version: str
    policy_id: str
    research_only: bool
    observed_at: datetime | None
    anchor_bar_end: datetime | None
    availability: LifecycleAvailability
    unavailable_reason: str | None
    direction: SubingDirection
    stage: LifecycleStage
    opportunity_key: SubingOpportunityKey | None
    entry_progress: EntryProgress | None
    trigger_kind: str | None = None
    trigger_timeframe: BarFrequency | None = None
    triggered_at: datetime | None = None
    confirmation_source: ConfirmationSource | None = None
    confirmed_at: datetime | None = None
    hold_count: int = 0
    hold_required: int = 3
    bound_reference_pivot: ConfirmedPivot | None = None
    rebreak_reference_price: Decimal | None = None
    retest_at: datetime | None = None
    retest_rebreak_count: int = 0
    latest_transition: SubingLifecycleTransition | None = None
    formal_v1_matched: bool = False
    volume_ratio_prev: Decimal | None = None
    open_interest_delta: Decimal | None = None


@dataclass(frozen=True, slots=True)
class SubingLifecycleTrace:
    formula_version: str
    policy_id: str
    symbol: str
    contract: str
    segment_start_trading_day: date
    confirmed_pivots: tuple[ConfirmedPivot, ...]
    completed_opportunities: tuple[SubingLifecycleState, ...]
    transitions: tuple[SubingLifecycleTransition, ...]
    snapshots: tuple[SubingLifecycleSnapshot, ...]
    current_snapshot: SubingLifecycleSnapshot

    @property
    def confirmed_transitions(self) -> tuple[SubingLifecycleTransition, ...]:
        return self.transitions


@dataclass(slots=True)
class _ActiveOpportunity:
    key: SubingOpportunityKey
    origin_trading_day: date
    stage: LifecycleStage = LifecycleStage.SETUP_ARMED
    progress: EntryProgress | None = EntryProgress.WAITING_TRIGGER
    confirmation_source: ConfirmationSource | None = None
    confirmed_at: datetime | None = None
    trigger_kind: str | None = None
    trigger_timeframe: BarFrequency | None = None
    triggered_at: datetime | None = None
    hold_count: int = 0
    volume_ratio_prev: Decimal | None = None
    open_interest_delta: Decimal | None = None
    bound_reference_pivot: ConfirmedPivot | None = None
    rebreak_reference_price: Decimal | None = None
    retest_at: datetime | None = None
    retest_rebreak_count: int = 0
    last_evaluable_close: Decimal | None = None


def evaluate_subing_lifecycle(
    *,
    symbol: str,
    contract: str,
    segment_start_trading_day: date,
    bars_5m: Sequence[CanonicalBar],
    factors_5m: Sequence[SubingFactorResult],
    bars_15m: Sequence[CanonicalBar],
    factors_15m: Sequence[SubingFactorResult],
    calibration: SubingCalibration,
    policy: SubingLifecyclePolicy,
) -> SubingLifecycleTrace:
    """Reduce aligned completed 5m/15m facts into a research-only trace."""

    snapshots: list[SubingLifecycleSnapshot] = []
    transitions: list[SubingLifecycleTransition] = []
    completed: list[SubingLifecycleState] = []
    opportunity: _ActiveOpportunity | None = None
    anchor_index = -1
    input_error = _input_contract_error(
        symbol=symbol,
        contract=contract,
        segment_start_trading_day=segment_start_trading_day,
        bars_5m=bars_5m,
        factors_5m=factors_5m,
        bars_15m=bars_15m,
        factors_15m=factors_15m,
        calibration=calibration,
        policy=policy,
    )
    pivots: tuple[ConfirmedPivot, ...] = ()
    pivot_trading_days: dict[str, date] = {}
    if input_error is None:
        try:
            pivots = _all_confirmed_pivots(
                bars_5m,
                contract=contract,
                segment_start_trading_day=segment_start_trading_day,
            )
            trading_day_by_bar_end = {
                bar.bar_end: bar.trading_day for bar in bars_5m
            }
            pivot_trading_days = {
                pivot.pivot_id: trading_day_by_bar_end[pivot.pivot_time]
                for pivot in pivots
            }
        except ValueError:
            input_error = "SUBING_STRUCTURE_INVALID"

    for index, bar_5m in enumerate(bars_5m):
        transition_count_before = len(transitions)
        while (
            anchor_index + 1 < len(bars_15m)
            and bars_15m[anchor_index + 1].bar_end <= bar_5m.bar_end
        ):
            anchor_index += 1
        anchor_bar = bars_15m[anchor_index] if anchor_index >= 0 else None
        anchor_factor = factors_15m[anchor_index] if anchor_index >= 0 else None
        boundary_error = input_error or _boundary_contract_error(
            bar=bar_5m,
            factor=factors_5m[index] if index < len(factors_5m) else None,
            timeframe=BarFrequency.M5,
            contract=contract,
            segment_start_trading_day=segment_start_trading_day,
        )
        if anchor_bar is None or anchor_factor is None:
            boundary_error = boundary_error or "SUBING_15M_ANCHOR_UNAVAILABLE"
        elif boundary_error is None:
            boundary_error = _boundary_contract_error(
                bar=anchor_bar,
                factor=anchor_factor,
                timeframe=BarFrequency.M15,
                contract=contract,
                segment_start_trading_day=segment_start_trading_day,
            )

        if boundary_error is not None:
            snapshots.append(
                _snapshot(
                    policy=policy,
                    observed_at=bar_5m.bar_end,
                    anchor_bar_end=(None if anchor_bar is None else anchor_bar.bar_end),
                    availability=LifecycleAvailability.UNAVAILABLE,
                    unavailable_reason=boundary_error,
                    direction=(
                        opportunity.key.direction
                        if opportunity is not None
                        else SubingDirection.NONE
                    ),
                    opportunity=opportunity,
                    latest_transition=(transitions[-1] if transitions else None),
                )
            )
            assert len(transitions) == transition_count_before
            continue

        assert anchor_bar is not None and anchor_factor is not None
        factor_5m = factors_5m[index].snapshot
        factor_15m = anchor_factor.snapshot
        assert factor_5m is not None and factor_15m is not None
        direction = _direction_context(factor_5m, factor_15m, calibration)
        formal = _formal_v1_at_boundary(
            factor_5m=factors_5m[index],
            factor_15m=anchor_factor,
            same_boundary=anchor_bar.bar_end == bar_5m.bar_end,
            calibration=calibration,
        )
        formal_match = formal.status is SubingSignalStatus.MATCHED

        if opportunity is not None and opportunity.stage is LifecycleStage.CLOSED:
            opportunity = None

        if opportunity is None:
            if formal_match:
                opportunity = _new_opportunity(
                    policy=policy,
                    symbol=symbol,
                    contract=contract,
                    segment_start_trading_day=segment_start_trading_day,
                    direction=formal.direction,
                    origin_at=bar_5m.bar_end,
                    origin_trading_day=bar_5m.trading_day,
                )
                opportunity.stage = LifecycleStage.ENTRY_CONFIRMED
                opportunity.progress = None
                opportunity.confirmation_source = ConfirmationSource.FORMAL_V1
                opportunity.confirmed_at = bar_5m.bar_end
                transitions.append(
                    _transition(
                        opportunity_key=opportunity.key,
                        transition_at=bar_5m.bar_end,
                        from_stage=LifecycleStage.IDLE,
                        to_stage=LifecycleStage.ENTRY_CONFIRMED,
                        reason_code="FORMAL_V1_MATCHED",
                    )
                )
            elif direction is not SubingDirection.NONE:
                opportunity = _new_opportunity(
                    policy=policy,
                    symbol=symbol,
                    contract=contract,
                    segment_start_trading_day=segment_start_trading_day,
                    direction=direction,
                    origin_at=bar_5m.bar_end,
                    origin_trading_day=bar_5m.trading_day,
                )
                transitions.append(
                    _transition(
                        opportunity_key=opportunity.key,
                        transition_at=bar_5m.bar_end,
                        from_stage=LifecycleStage.IDLE,
                        to_stage=LifecycleStage.SETUP_ARMED,
                        reason_code="DIRECTION_CONTEXT_ALIGNED",
                    )
                )
        elif opportunity.stage is LifecycleStage.SETUP_ARMED:
            if formal_match and formal.direction is opportunity.key.direction:
                _confirm_entry(
                    opportunity,
                    source=ConfirmationSource.FORMAL_V1,
                    confirmed_at=bar_5m.bar_end,
                )
                transitions.append(
                    _transition(
                        opportunity_key=opportunity.key,
                        transition_at=bar_5m.bar_end,
                        from_stage=LifecycleStage.SETUP_ARMED,
                        to_stage=LifecycleStage.ENTRY_CONFIRMED,
                        reason_code="FORMAL_V1_MATCHED",
                    )
                )
            elif bar_5m.trading_day > opportunity.origin_trading_day:
                _close_setup(
                    opportunity,
                    transition_at=bar_5m.bar_end,
                    reason_code="UNCONFIRMED_TRADING_DAY_ROLLOVER",
                    transitions=transitions,
                    completed=completed,
                )
            elif opportunity.progress is EntryProgress.RETEST_CONFIRMING:
                pivot = opportunity.bound_reference_pivot
                assert pivot is not None
                retest = assess_pivot_retest(
                    bar_5m,
                    pivot=pivot,
                    direction=opportunity.key.direction,
                )
                if retest.hard_invalidated or not _persistence_context(
                    factor_5m,
                    factor_15m,
                    opportunity.key.direction,
                ):
                    _close_setup(
                        opportunity,
                        transition_at=bar_5m.bar_end,
                        reason_code="PIVOT_RETEST_INVALIDATED",
                        transitions=transitions,
                        completed=completed,
                    )
                else:
                    previous_close = opportunity.last_evaluable_close
                    opportunity.retest_rebreak_count += 1
                    if _rebreak_crossed(
                        previous_close=previous_close,
                        current_close=bar_5m.close,
                        reference_price=opportunity.rebreak_reference_price,
                        pivot_price=pivot.price,
                        direction=opportunity.key.direction,
                    ):
                        _confirm_entry(
                            opportunity,
                            source=ConfirmationSource.PIVOT_RETEST_REBREAK,
                            confirmed_at=bar_5m.bar_end,
                        )
                        transitions.append(
                            _transition(
                                opportunity_key=opportunity.key,
                                transition_at=bar_5m.bar_end,
                                from_stage=LifecycleStage.SETUP_ARMED,
                                to_stage=LifecycleStage.ENTRY_CONFIRMED,
                                reason_code="PIVOT_RETEST_REBREAK_CONFIRMED",
                            )
                        )
                    elif (
                        opportunity.retest_rebreak_count
                        >= policy.retest_rebreak_max_bars
                    ):
                        _close_setup(
                            opportunity,
                            transition_at=bar_5m.bar_end,
                            reason_code="RETEST_REBREAK_TIMEOUT",
                            transitions=transitions,
                            completed=completed,
                        )
                    opportunity.last_evaluable_close = bar_5m.close
            elif opportunity.progress is EntryProgress.HOLD_CONFIRMING and (
                opportunity.trigger_kind == "pivot_break"
            ):
                pivot = opportunity.bound_reference_pivot
                assert pivot is not None
                retest = assess_pivot_retest(
                    bar_5m,
                    pivot=pivot,
                    direction=opportunity.key.direction,
                )
                if retest.hard_invalidated:
                    _close_setup(
                        opportunity,
                        transition_at=bar_5m.bar_end,
                        reason_code="PIVOT_RETEST_INVALIDATED",
                        transitions=transitions,
                        completed=completed,
                    )
                elif retest.touched_reference and retest.close_preserved_side:
                    opportunity.progress = EntryProgress.RETEST_CONFIRMING
                    opportunity.retest_at = bar_5m.bar_end
                    opportunity.retest_rebreak_count = 0
                    opportunity.last_evaluable_close = bar_5m.close
                elif not _persistence_context(
                    factor_5m,
                    factor_15m,
                    opportunity.key.direction,
                ):
                    _close_setup(
                        opportunity,
                        transition_at=bar_5m.bar_end,
                        reason_code="PIVOT_BREAK_HOLD_FAILED",
                        transitions=transitions,
                        completed=completed,
                    )
                else:
                    opportunity.hold_count += 1
                    opportunity.last_evaluable_close = bar_5m.close
                    if opportunity.hold_count >= policy.hold_required_bars:
                        _confirm_entry(
                            opportunity,
                            source=ConfirmationSource.PIVOT_BREAK_HOLD,
                            confirmed_at=bar_5m.bar_end,
                        )
                        transitions.append(
                            _transition(
                                opportunity_key=opportunity.key,
                                transition_at=bar_5m.bar_end,
                                from_stage=LifecycleStage.SETUP_ARMED,
                                to_stage=LifecycleStage.ENTRY_CONFIRMED,
                                reason_code="PIVOT_BREAK_HOLD_CONFIRMED",
                            )
                        )
            elif opportunity.progress is EntryProgress.HOLD_CONFIRMING:
                if _momentum_hold_failed(
                    opportunity,
                    factor_5m,
                    factor_15m,
                    same_boundary=anchor_bar.bar_end == bar_5m.bar_end,
                    formal=formal,
                ):
                    _close_setup(
                        opportunity,
                        transition_at=bar_5m.bar_end,
                        reason_code="MOMENTUM_HOLD_FAILED",
                        transitions=transitions,
                        completed=completed,
                    )
                else:
                    opportunity.hold_count += 1
                    if opportunity.hold_count >= policy.hold_required_bars:
                        _confirm_entry(
                            opportunity,
                            source=ConfirmationSource.MOMENTUM_HOLD,
                            confirmed_at=bar_5m.bar_end,
                        )
                        transitions.append(
                            _transition(
                                opportunity_key=opportunity.key,
                                transition_at=bar_5m.bar_end,
                                from_stage=LifecycleStage.SETUP_ARMED,
                                to_stage=LifecycleStage.ENTRY_CONFIRMED,
                                reason_code="MOMENTUM_HOLD_CONFIRMED",
                            )
                        )
            elif direction is not opportunity.key.direction:
                _close_setup(
                    opportunity,
                    transition_at=bar_5m.bar_end,
                    reason_code="DIRECTION_CONTEXT_INVALIDATED",
                    transitions=transitions,
                    completed=completed,
                )
            else:
                pivot_trigger = (
                    _pivot_breakout_at(
                        pivots,
                        pivot_trading_days=pivot_trading_days,
                        previous=bars_5m[index - 1],
                        current=bar_5m,
                        direction=opportunity.key.direction,
                    )
                    if index > 0
                    else None
                )
                if pivot_trigger is not None:
                    pivot, assessment = pivot_trigger
                    opportunity.progress = EntryProgress.HOLD_CONFIRMING
                    opportunity.trigger_kind = "pivot_break"
                    opportunity.trigger_timeframe = BarFrequency.M5
                    opportunity.triggered_at = bar_5m.bar_end
                    opportunity.hold_count = 1
                    opportunity.bound_reference_pivot = pivot
                    opportunity.rebreak_reference_price = (
                        bar_5m.high
                        if opportunity.key.direction is SubingDirection.LONG
                        else bar_5m.low
                    )
                    opportunity.last_evaluable_close = bar_5m.close
                    opportunity.volume_ratio_prev = assessment.volume_ratio_prev
                    opportunity.open_interest_delta = assessment.open_interest_delta
                else:
                    trigger_timeframe = _same_direction_macd_trigger(
                        factor_5m,
                        factor_15m,
                        same_boundary=anchor_bar.bar_end == bar_5m.bar_end,
                        direction=opportunity.key.direction,
                    )
                    if trigger_timeframe is not None:
                        opportunity.progress = EntryProgress.HOLD_CONFIRMING
                        opportunity.trigger_kind = "macd_cross"
                        opportunity.trigger_timeframe = trigger_timeframe
                        opportunity.triggered_at = bar_5m.bar_end
                        opportunity.hold_count = 1
                        opportunity.volume_ratio_prev = factor_5m.volume_ratio_prev
                        if index > 0:
                            previous = bars_5m[index - 1]
                            if (
                                previous.open_interest is not None
                                and bar_5m.open_interest is not None
                            ):
                                opportunity.open_interest_delta = (
                                    bar_5m.open_interest - previous.open_interest
                                )
        assert len(transitions) - transition_count_before <= 1
        snapshots.append(
            _snapshot(
                policy=policy,
                observed_at=bar_5m.bar_end,
                anchor_bar_end=anchor_bar.bar_end,
                availability=LifecycleAvailability.READY,
                unavailable_reason=None,
                direction=(
                    opportunity.key.direction
                    if opportunity is not None
                    else SubingDirection.NONE
                ),
                opportunity=opportunity,
                latest_transition=(transitions[-1] if transitions else None),
                formal_v1_matched=formal_match,
            )
        )

    current_snapshot = snapshots[-1] if snapshots else _snapshot(
        policy=policy,
        observed_at=None,
        anchor_bar_end=None,
        availability=LifecycleAvailability.UNAVAILABLE,
        unavailable_reason="SUBING_5M_CLOCK_UNAVAILABLE",
        direction=SubingDirection.NONE,
        opportunity=None,
        latest_transition=None,
    )
    return SubingLifecycleTrace(
        formula_version=policy.formula_version,
        policy_id=policy.policy_id,
        symbol=symbol,
        contract=contract,
        segment_start_trading_day=segment_start_trading_day,
        confirmed_pivots=pivots,
        completed_opportunities=tuple(completed),
        transitions=tuple(transitions),
        snapshots=tuple(snapshots),
        current_snapshot=current_snapshot,
    )


def _input_contract_error(
    *,
    symbol: str,
    contract: str,
    segment_start_trading_day: date,
    bars_5m: Sequence[CanonicalBar],
    factors_5m: Sequence[SubingFactorResult],
    bars_15m: Sequence[CanonicalBar],
    factors_15m: Sequence[SubingFactorResult],
    calibration: SubingCalibration,
    policy: SubingLifecyclePolicy,
) -> str | None:
    if (
        not isinstance(symbol, str)
        or not symbol.strip()
        or not isinstance(contract, str)
        or not contract.strip()
        or normalize_contract_for_symbol(symbol, contract) != contract
        or type(segment_start_trading_day) is not date
    ):
        return "SUBING_LIFECYCLE_IDENTITY_INVALID"
    try:
        if not isinstance(policy, SubingLifecyclePolicy):
            raise TypeError
        replace(policy)
    except (TypeError, ValueError):
        return "SUBING_LIFECYCLE_POLICY_INVALID"
    if (
        not isinstance(calibration, SubingCalibration)
        or calibration.calibration_id != "subing_intraday_v1"
        or not {BarFrequency.M5, BarFrequency.M15}.issubset(
            calibration.accepted_timeframes
        )
        or any(
            timeframe not in calibration.slope_flat_threshold_bps_per_bar
            for timeframe in (BarFrequency.M5, BarFrequency.M15)
        )
    ):
        return "SUBING_CALIBRATION_INVALID"
    if len(bars_5m) != len(factors_5m) or len(bars_15m) != len(factors_15m):
        return "SUBING_LIFECYCLE_SERIES_ALIGNMENT_INVALID"
    for bars in (bars_5m, bars_15m):
        if any(
            not isinstance(bar, CanonicalBar)
            or bar.trading_day < segment_start_trading_day
            for bar in bars
        ) or any(
            left.bar_end >= right.bar_end for left, right in zip(bars, bars[1:])
        ):
            return "SUBING_LIFECYCLE_SERIES_IDENTITY_INVALID"
    return None


def _boundary_contract_error(
    *,
    bar: CanonicalBar,
    factor: SubingFactorResult | None,
    timeframe: BarFrequency,
    contract: str,
    segment_start_trading_day: date,
) -> str | None:
    if (
        factor is None
        or not isinstance(factor, SubingFactorResult)
        or factor.status is not SubingFactorStatus.READY
        or factor.snapshot is None
    ):
        return "SUBING_FACTOR_UNAVAILABLE"
    snapshot = factor.snapshot
    if (
        snapshot.timeframe is not timeframe
        or snapshot.bar_end != bar.bar_end
        or snapshot.trading_day != bar.trading_day
        or snapshot.close != bar.close
        or snapshot.contract != contract
        or snapshot.segment_start_trading_day != segment_start_trading_day
    ):
        return "SUBING_FACTOR_IDENTITY_MISMATCH"
    return None


def _direction_context(
    factor_5m: SubingFactorSnapshot,
    factor_15m: SubingFactorSnapshot,
    calibration: SubingCalibration,
) -> SubingDirection:
    threshold_5m = calibration.slope_flat_threshold_bps_per_bar[BarFrequency.M5]
    threshold_15m = calibration.slope_flat_threshold_bps_per_bar[BarFrequency.M15]
    if (
        factor_5m.close > factor_5m.ema21
        and factor_15m.close > factor_15m.ema21
        and factor_5m.slope_5_bps_per_bar > threshold_5m
        and factor_15m.slope_5_bps_per_bar > threshold_15m
        and factor_5m.slope_10_bps_per_bar > 0
        and factor_15m.slope_10_bps_per_bar > 0
    ):
        return SubingDirection.LONG
    if (
        factor_5m.close < factor_5m.ema21
        and factor_15m.close < factor_15m.ema21
        and factor_5m.slope_5_bps_per_bar < -threshold_5m
        and factor_15m.slope_5_bps_per_bar < -threshold_15m
        and factor_5m.slope_10_bps_per_bar < 0
        and factor_15m.slope_10_bps_per_bar < 0
    ):
        return SubingDirection.SHORT
    return SubingDirection.NONE


def _all_confirmed_pivots(
    bars: Sequence[CanonicalBar],
    *,
    contract: str,
    segment_start_trading_day: date,
) -> tuple[ConfirmedPivot, ...]:
    bars_by_trading_day: dict[date, list[CanonicalBar]] = {}
    for bar in bars:
        bars_by_trading_day.setdefault(bar.trading_day, []).append(bar)
    return tuple(
        sorted(
            (
                pivot
                for trading_day, day_bars in bars_by_trading_day.items()
                for pivot in confirmed_pivots(
                    day_bars,
                    source_timeframe=BarFrequency.M5,
                    contract=contract,
                    segment_start_trading_day=segment_start_trading_day,
                    trading_day=trading_day,
                )
            ),
            key=lambda pivot: (pivot.confirmed_at, pivot.pivot_time, pivot.kind.value),
        )
    )


def _pivot_breakout_at(
    pivots: Sequence[ConfirmedPivot],
    *,
    pivot_trading_days: dict[str, date],
    previous: CanonicalBar,
    current: CanonicalBar,
    direction: SubingDirection,
) -> tuple[ConfirmedPivot, BreakoutAssessment] | None:
    expected_kind = (
        PivotKind.HIGH
        if direction is SubingDirection.LONG
        else PivotKind.LOW
    )
    candidates = tuple(
        pivot
        for pivot in pivots
        if pivot.kind is expected_kind
        and pivot.confirmed_at < current.bar_end
        and pivot_trading_days[pivot.pivot_id] == current.trading_day
    )
    if not candidates:
        return None
    pivot = max(candidates, key=lambda item: (item.confirmed_at, item.pivot_time))
    assessment = assess_pivot_breakout(
        previous,
        current,
        pivot=pivot,
        direction=direction,
    )
    return (pivot, assessment) if assessment.crossed_on_close else None


def _rebreak_crossed(
    *,
    previous_close: Decimal | None,
    current_close: Decimal,
    reference_price: Decimal | None,
    pivot_price: Decimal,
    direction: SubingDirection,
) -> bool:
    if previous_close is None or reference_price is None:
        return False
    if direction is SubingDirection.LONG:
        return (
            previous_close <= reference_price
            and current_close > reference_price
            and current_close >= pivot_price
        )
    return (
        previous_close >= reference_price
        and current_close < reference_price
        and current_close <= pivot_price
    )


def _formal_v1_at_boundary(
    *,
    factor_5m: SubingFactorResult,
    factor_15m: SubingFactorResult,
    same_boundary: bool,
    calibration: SubingCalibration,
) -> SubingSignalEvaluation:
    m5 = evaluate_subing_signal(
        factor_5m,
        companion=factor_15m,
        calibration=cast(_SignalCalibrationView, calibration),
    )
    if not same_boundary:
        return m5
    m15 = evaluate_subing_signal(
        factor_15m,
        companion=factor_5m,
        calibration=cast(_SignalCalibrationView, calibration),
    )
    return resolve_same_boundary_subing_signals(m5, m15)


def _new_opportunity(
    *,
    policy: SubingLifecyclePolicy,
    symbol: str,
    contract: str,
    segment_start_trading_day: date,
    direction: SubingDirection,
    origin_at: datetime,
    origin_trading_day: date,
) -> _ActiveOpportunity:
    return _ActiveOpportunity(
        key=SubingOpportunityKey(
            policy_id=policy.policy_id,
            symbol=symbol,
            contract=contract,
            segment_start_trading_day=segment_start_trading_day,
            direction=direction,
            origin_at=origin_at,
        ),
        origin_trading_day=origin_trading_day,
    )


def _same_direction_macd_trigger(
    factor_5m: SubingFactorSnapshot,
    factor_15m: SubingFactorSnapshot,
    *,
    same_boundary: bool,
    direction: SubingDirection,
) -> BarFrequency | None:
    expected = (
        MacdCross.GOLDEN
        if direction is SubingDirection.LONG
        else MacdCross.DEAD
    )
    if same_boundary and factor_15m.macd_cross is expected:
        return BarFrequency.M15
    if factor_5m.macd_cross is expected:
        return BarFrequency.M5
    return None


def _persistence_context(
    factor_5m: SubingFactorSnapshot,
    factor_15m: SubingFactorSnapshot,
    direction: SubingDirection,
) -> bool:
    if direction is SubingDirection.LONG:
        return (
            factor_5m.close > factor_5m.ema21
            and factor_5m.slope_10_bps_per_bar > 0
            and factor_15m.close > factor_15m.ema21
            and factor_15m.slope_10_bps_per_bar > 0
        )
    return (
        factor_5m.close < factor_5m.ema21
        and factor_5m.slope_10_bps_per_bar < 0
        and factor_15m.close < factor_15m.ema21
        and factor_15m.slope_10_bps_per_bar < 0
    )


def _momentum_hold_failed(
    opportunity: _ActiveOpportunity,
    factor_5m: SubingFactorSnapshot,
    factor_15m: SubingFactorSnapshot,
    *,
    same_boundary: bool,
    formal: SubingSignalEvaluation,
) -> bool:
    if (
        formal.status is SubingSignalStatus.MATCHED
        and formal.direction is not opportunity.key.direction
    ):
        return True
    opposite = (
        MacdCross.DEAD
        if opportunity.key.direction is SubingDirection.LONG
        else MacdCross.GOLDEN
    )
    if (
        opportunity.trigger_timeframe is BarFrequency.M5
        and factor_5m.macd_cross is opposite
    ) or (
        opportunity.trigger_timeframe is BarFrequency.M15
        and same_boundary
        and factor_15m.macd_cross is opposite
    ):
        return True
    return not _persistence_context(
        factor_5m,
        factor_15m,
        opportunity.key.direction,
    )


def _confirm_entry(
    opportunity: _ActiveOpportunity,
    *,
    source: ConfirmationSource,
    confirmed_at: datetime,
) -> None:
    opportunity.stage = LifecycleStage.ENTRY_CONFIRMED
    opportunity.progress = None
    opportunity.confirmation_source = source
    opportunity.confirmed_at = confirmed_at


def _close_setup(
    opportunity: _ActiveOpportunity,
    *,
    transition_at: datetime,
    reason_code: str,
    transitions: list[SubingLifecycleTransition],
    completed: list[SubingLifecycleState],
) -> None:
    opportunity.stage = LifecycleStage.CLOSED
    opportunity.progress = None
    transitions.append(
        _transition(
            opportunity_key=opportunity.key,
            transition_at=transition_at,
            from_stage=LifecycleStage.SETUP_ARMED,
            to_stage=LifecycleStage.CLOSED,
            reason_code=reason_code,
        )
    )
    completed.append(
        SubingLifecycleState(
            availability=LifecycleAvailability.READY,
            direction=opportunity.key.direction,
            stage=LifecycleStage.CLOSED,
            opportunity_key=opportunity.key,
        )
    )


def _transition(
    *,
    opportunity_key: SubingOpportunityKey,
    transition_at: datetime,
    from_stage: LifecycleStage,
    to_stage: LifecycleStage,
    reason_code: str,
) -> SubingLifecycleTransition:
    transition_id = ":".join(
        (
            opportunity_key.policy_id,
            opportunity_key.symbol,
            opportunity_key.contract,
            opportunity_key.segment_start_trading_day.isoformat(),
            opportunity_key.direction.value,
            opportunity_key.origin_at.isoformat(),
            transition_at.isoformat(),
            to_stage.value,
        )
    )
    return SubingLifecycleTransition(
        transition_id=transition_id,
        opportunity_key=opportunity_key,
        transition_at=transition_at,
        from_stage=from_stage,
        to_stage=to_stage,
        reason_codes=(reason_code,),
    )


def _snapshot(
    *,
    policy: SubingLifecyclePolicy,
    observed_at: datetime | None,
    anchor_bar_end: datetime | None,
    availability: LifecycleAvailability,
    unavailable_reason: str | None,
    direction: SubingDirection,
    opportunity: _ActiveOpportunity | None,
    latest_transition: SubingLifecycleTransition | None,
    formal_v1_matched: bool = False,
) -> SubingLifecycleSnapshot:
    stage = opportunity.stage if opportunity is not None else LifecycleStage.IDLE
    return SubingLifecycleSnapshot(
        formula_version=policy.formula_version,
        policy_id=policy.policy_id,
        research_only=policy.research_only,
        observed_at=observed_at,
        anchor_bar_end=anchor_bar_end,
        availability=availability,
        unavailable_reason=unavailable_reason,
        direction=direction,
        stage=stage,
        opportunity_key=(opportunity.key if opportunity is not None else None),
        entry_progress=(opportunity.progress if opportunity is not None else None),
        trigger_kind=(opportunity.trigger_kind if opportunity is not None else None),
        trigger_timeframe=(
            opportunity.trigger_timeframe if opportunity is not None else None
        ),
        triggered_at=(opportunity.triggered_at if opportunity is not None else None),
        confirmation_source=(
            opportunity.confirmation_source if opportunity is not None else None
        ),
        confirmed_at=(opportunity.confirmed_at if opportunity is not None else None),
        hold_count=(opportunity.hold_count if opportunity is not None else 0),
        hold_required=policy.hold_required_bars,
        bound_reference_pivot=(
            opportunity.bound_reference_pivot if opportunity is not None else None
        ),
        rebreak_reference_price=(
            opportunity.rebreak_reference_price if opportunity is not None else None
        ),
        retest_at=(opportunity.retest_at if opportunity is not None else None),
        retest_rebreak_count=(
            opportunity.retest_rebreak_count if opportunity is not None else 0
        ),
        latest_transition=latest_transition,
        formal_v1_matched=formal_v1_matched,
        volume_ratio_prev=(
            opportunity.volume_ratio_prev if opportunity is not None else None
        ),
        open_interest_delta=(
            opportunity.open_interest_delta if opportunity is not None else None
        ),
    )
