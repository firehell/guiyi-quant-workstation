from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, cast

from .domain import BarFrequency, CanonicalBar, normalize_contract_for_symbol
from .subing_calibration import SubingCalibration, is_accepted_subing_calibration
from .subing_lifecycle_policy import (
    _FORMULA_VERSION,
    _POLICY_ID,
    SubingLifecyclePolicy,
)
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


class SubingLifecycleContractError(ValueError):
    code = "SUBING_LIFECYCLE_CONTRACT_INVALID"

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
            or self.policy_id != _POLICY_ID
            or not isinstance(self.symbol, str)
            or not self.symbol.strip()
            or self.symbol != self.symbol.strip()
            or not isinstance(self.contract, str)
            or normalize_contract_for_symbol(self.symbol, self.contract)
            != self.contract
            or type(self.segment_start_trading_day) is not date
            or not isinstance(self.direction, SubingDirection)
            or self.direction not in {SubingDirection.LONG, SubingDirection.SHORT}
            or not isinstance(self.origin_at, datetime)
            or self.origin_at.tzinfo is None
            or self.origin_at.utcoffset() is None
        ):
            raise ValueError("SUBING_OPPORTUNITY_KEY_INVALID")
        object.__setattr__(self, "origin_at", self.origin_at.astimezone(UTC))


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

    def __post_init__(self) -> None:
        try:
            allowed_targets = {
                LifecycleStage.IDLE: {
                    LifecycleStage.SETUP_ARMED,
                    LifecycleStage.ENTRY_CONFIRMED,
                },
                LifecycleStage.SETUP_ARMED: {
                    LifecycleStage.ENTRY_CONFIRMED,
                    LifecycleStage.CLOSED,
                },
                LifecycleStage.ENTRY_CONFIRMED: {
                    LifecycleStage.CONTINUATION,
                    LifecycleStage.EXIT_RISK,
                    LifecycleStage.CLOSED,
                },
                LifecycleStage.CONTINUATION: {
                    LifecycleStage.EXIT_RISK,
                    LifecycleStage.CLOSED,
                },
                LifecycleStage.EXIT_RISK: {
                    LifecycleStage.CONTINUATION,
                    LifecycleStage.CLOSED,
                },
                LifecycleStage.CLOSED: set(),
            }
            if not _is_aware_datetime(self.transition_at):
                raise SubingLifecycleContractError()
            object.__setattr__(
                self,
                "transition_at",
                self.transition_at.astimezone(UTC),
            )
            if (
                not isinstance(self.transition_id, str)
                or not isinstance(self.opportunity_key, SubingOpportunityKey)
                or not _is_aware_datetime(self.transition_at)
                or not isinstance(self.from_stage, LifecycleStage)
                or not isinstance(self.to_stage, LifecycleStage)
                or self.from_stage is self.to_stage
                or self.to_stage not in allowed_targets.get(self.from_stage, set())
                or type(self.reason_codes) is not tuple
                or not self.reason_codes
                or any(
                    not isinstance(code, str) or not code.strip()
                    for code in self.reason_codes
                )
                or self.transition_at < self.opportunity_key.origin_at
                or self.transition_id
                != _transition_identity(
                    opportunity_key=self.opportunity_key,
                    transition_at=self.transition_at,
                    to_stage=self.to_stage,
                )
            ):
                raise SubingLifecycleContractError()
        except (AttributeError, TypeError, ValueError) as exc:
            if isinstance(exc, SubingLifecycleContractError):
                raise
            raise SubingLifecycleContractError() from exc


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
    current_risk_codes: tuple[str, ...] = ()
    risk_progress: str | None = None
    lower_tf_risk_count: int = 0
    last_confirmed_stage: LifecycleStage = LifecycleStage.IDLE
    last_confirmed_at: datetime | None = None
    crossed_trading_day: bool = False
    boundary_reset: str | None = None

    def __post_init__(self) -> None:
        try:
            _validate_snapshot_contract(self)
        except (AttributeError, TypeError, ValueError) as exc:
            if isinstance(exc, SubingLifecycleContractError):
                raise
            raise SubingLifecycleContractError() from exc


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

    def __post_init__(self) -> None:
        try:
            _validate_trace_contract(self)
        except (AttributeError, TypeError, ValueError) as exc:
            if isinstance(exc, SubingLifecycleContractError):
                raise
            raise SubingLifecycleContractError() from exc

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
    current_risk_codes: tuple[str, ...] = ()
    risk_progress: str | None = None
    lower_tf_risk_count: int = 0
    crossed_trading_day: bool = False


def _is_aware_datetime(value: object) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )


def _validate_snapshot_contract(snapshot: SubingLifecycleSnapshot) -> None:
    lower_tf_risk_codes = {
        "LOWER_TF_EMA21_BREACH",
        "LOWER_TF_SLOPE5_REVERSAL",
        "LOWER_TF_MACD_OPPOSITE_CROSS",
        "LOWER_TF_BOUND_PIVOT_REENTRY",
    }
    approved_risk_codes = lower_tf_risk_codes | {
        "ANCHOR_EMA21_BREACH",
        "ANCHOR_SLOPE5_REVERSAL",
        "ANCHOR_MACD_OPPOSITE_CROSS",
        "TIMEFRAME_ALIGNMENT_LOST",
    }
    anchor_risk_codes = approved_risk_codes - lower_tf_risk_codes
    if (
        snapshot.formula_version != _FORMULA_VERSION
        or snapshot.policy_id != _POLICY_ID
        or snapshot.research_only is not True
        or not isinstance(snapshot.availability, LifecycleAvailability)
        or not isinstance(snapshot.direction, SubingDirection)
        or not isinstance(snapshot.stage, LifecycleStage)
        or type(snapshot.hold_count) is not int
        or type(snapshot.hold_required) is not int
        or snapshot.hold_required != 3
        or not 0 <= snapshot.hold_count <= snapshot.hold_required
        or type(snapshot.retest_rebreak_count) is not int
        or not 0 <= snapshot.retest_rebreak_count <= 3
        or type(snapshot.formal_v1_matched) is not bool
        or type(snapshot.current_risk_codes) is not tuple
        or any(
            not isinstance(code, str) or not code.strip()
            for code in snapshot.current_risk_codes
        )
        or snapshot.risk_progress not in {None, "watching"}
        or type(snapshot.lower_tf_risk_count) is not int
        or not 0 <= snapshot.lower_tf_risk_count <= 2
        or not isinstance(snapshot.last_confirmed_stage, LifecycleStage)
        or type(snapshot.crossed_trading_day) is not bool
        or snapshot.boundary_reset not in {None, "segment_changed"}
    ):
        raise SubingLifecycleContractError()

    if snapshot.lower_tf_risk_count == 0 and snapshot.risk_progress is not None:
        raise SubingLifecycleContractError()
    if snapshot.lower_tf_risk_count == 1 and snapshot.risk_progress != "watching":
        raise SubingLifecycleContractError()
    if snapshot.lower_tf_risk_count > 0 and not snapshot.current_risk_codes:
        raise SubingLifecycleContractError()
    if (
        snapshot.lower_tf_risk_count == 2
        and snapshot.stage is not LifecycleStage.EXIT_RISK
    ):
        raise SubingLifecycleContractError()
    if any(code not in approved_risk_codes for code in snapshot.current_risk_codes):
        raise SubingLifecycleContractError()
    has_lower_tf_risk = any(
        code in lower_tf_risk_codes for code in snapshot.current_risk_codes
    )
    has_anchor_risk = any(
        code in anchor_risk_codes for code in snapshot.current_risk_codes
    )
    if has_lower_tf_risk and has_anchor_risk:
        raise SubingLifecycleContractError()
    if has_lower_tf_risk and snapshot.lower_tf_risk_count not in {1, 2}:
        raise SubingLifecycleContractError()
    if has_anchor_risk and (
        snapshot.stage is not LifecycleStage.EXIT_RISK
        or snapshot.lower_tf_risk_count != 0
        or snapshot.risk_progress is not None
    ):
        raise SubingLifecycleContractError()
    has_risk_projection = bool(snapshot.current_risk_codes) or any(
        (
            snapshot.risk_progress is not None,
            snapshot.lower_tf_risk_count != 0,
        )
    )
    if has_risk_projection and snapshot.stage not in {
        LifecycleStage.CONTINUATION,
        LifecycleStage.EXIT_RISK,
    }:
        raise SubingLifecycleContractError()
    if snapshot.lower_tf_risk_count > 0 and not any(
        code in lower_tf_risk_codes for code in snapshot.current_risk_codes
    ):
        raise SubingLifecycleContractError()
    if (
        snapshot.stage is LifecycleStage.CONTINUATION
        and snapshot.current_risk_codes
        and (
            snapshot.lower_tf_risk_count != 1
            or snapshot.risk_progress != "watching"
        )
    ):
        raise SubingLifecycleContractError()
    confirmed_stages = {
        LifecycleStage.CONTINUATION,
        LifecycleStage.EXIT_RISK,
        LifecycleStage.CLOSED,
    }
    if snapshot.crossed_trading_day and (
        snapshot.stage not in confirmed_stages
        or snapshot.confirmation_source is None
        or snapshot.confirmed_at is None
    ):
        raise SubingLifecycleContractError()
    if snapshot.boundary_reset == "segment_changed" and (
        snapshot.stage is not LifecycleStage.IDLE
        or snapshot.opportunity_key is not None
        or has_risk_projection
        or snapshot.crossed_trading_day
    ):
        raise SubingLifecycleContractError()
    if snapshot.last_confirmed_at is not None and (
        not _is_aware_datetime(snapshot.last_confirmed_at)
        or snapshot.observed_at is None
        or snapshot.last_confirmed_at > snapshot.observed_at
    ):
        raise SubingLifecycleContractError()

    if snapshot.observed_at is None:
        if snapshot.anchor_bar_end is not None:
            raise SubingLifecycleContractError()
    elif not _is_aware_datetime(snapshot.observed_at):
        raise SubingLifecycleContractError()
    if snapshot.anchor_bar_end is not None and (
        not _is_aware_datetime(snapshot.anchor_bar_end)
        or snapshot.observed_at is None
        or snapshot.anchor_bar_end > snapshot.observed_at
    ):
        raise SubingLifecycleContractError()

    has_reason = (
        isinstance(snapshot.unavailable_reason, str)
        and bool(snapshot.unavailable_reason.strip())
    )
    if (
        snapshot.availability is LifecycleAvailability.READY
        and snapshot.unavailable_reason is not None
    ) or (
        snapshot.availability is LifecycleAvailability.UNAVAILABLE
        and not has_reason
    ):
        raise SubingLifecycleContractError()

    try:
        SubingLifecycleState(
            availability=snapshot.availability,
            direction=snapshot.direction,
            stage=snapshot.stage,
            opportunity_key=snapshot.opportunity_key,
            entry_progress=snapshot.entry_progress,
            confirmation_source=snapshot.confirmation_source,
            confirmed_at=snapshot.confirmed_at,
        )
    except SubingLifecycleStateError as exc:
        raise SubingLifecycleContractError() from exc

    key = snapshot.opportunity_key
    if key is not None and key.policy_id != snapshot.policy_id:
        raise SubingLifecycleContractError()
    if key is None and any(
        (
            snapshot.trigger_kind is not None,
            snapshot.trigger_timeframe is not None,
            snapshot.triggered_at is not None,
            snapshot.confirmation_source is not None,
            snapshot.confirmed_at is not None,
            snapshot.hold_count != 0,
            snapshot.bound_reference_pivot is not None,
            snapshot.rebreak_reference_price is not None,
            snapshot.retest_at is not None,
            snapshot.retest_rebreak_count != 0,
            snapshot.formal_v1_matched,
            snapshot.volume_ratio_prev is not None,
            snapshot.open_interest_delta is not None,
            snapshot.current_risk_codes,
            snapshot.risk_progress is not None,
            snapshot.lower_tf_risk_count != 0,
            snapshot.crossed_trading_day,
        )
    ):
        raise SubingLifecycleContractError()

    for timestamp in (
        snapshot.triggered_at,
        snapshot.confirmed_at,
        snapshot.retest_at,
    ):
        if timestamp is not None and (
            not _is_aware_datetime(timestamp)
            or snapshot.observed_at is None
            or timestamp > snapshot.observed_at
        ):
            raise SubingLifecycleContractError()
    if key is not None and (
        (snapshot.triggered_at is not None and snapshot.triggered_at < key.origin_at)
        or (snapshot.retest_at is not None and snapshot.retest_at < key.origin_at)
    ):
        raise SubingLifecycleContractError()

    trigger_fields = (
        snapshot.trigger_kind,
        snapshot.trigger_timeframe,
        snapshot.triggered_at,
    )
    if snapshot.trigger_kind is None:
        if any(value is not None for value in trigger_fields[1:]):
            raise SubingLifecycleContractError()
    elif (
        snapshot.trigger_kind not in {"macd_cross", "pivot_break"}
        or not isinstance(snapshot.trigger_timeframe, BarFrequency)
        or not _is_aware_datetime(snapshot.triggered_at)
    ):
        raise SubingLifecycleContractError()

    if snapshot.entry_progress is EntryProgress.WAITING_TRIGGER and (
        snapshot.trigger_kind is not None or snapshot.hold_count != 0
    ):
        raise SubingLifecycleContractError()
    if snapshot.entry_progress is EntryProgress.HOLD_CONFIRMING and (
        snapshot.trigger_kind is None or snapshot.hold_count < 1
    ):
        raise SubingLifecycleContractError()
    if snapshot.entry_progress is EntryProgress.RETEST_CONFIRMING and (
        snapshot.trigger_kind != "pivot_break"
        or snapshot.retest_at is None
        or snapshot.hold_count < 1
    ):
        raise SubingLifecycleContractError()

    pivot = snapshot.bound_reference_pivot
    if snapshot.trigger_kind == "pivot_break":
        if (
            not isinstance(pivot, ConfirmedPivot)
            or snapshot.trigger_timeframe is not BarFrequency.M5
            or not isinstance(snapshot.rebreak_reference_price, Decimal)
            or not snapshot.rebreak_reference_price.is_finite()
            or key is None
            or pivot.contract != key.contract
            or pivot.segment_start_trading_day != key.segment_start_trading_day
        ):
            raise SubingLifecycleContractError()
    elif (
        pivot is not None
        or snapshot.rebreak_reference_price is not None
        or snapshot.retest_at is not None
        or snapshot.retest_rebreak_count != 0
    ):
        raise SubingLifecycleContractError()

    if snapshot.confirmation_source is ConfirmationSource.FORMAL_V1:
        if (snapshot.trigger_kind is None and snapshot.hold_count != 0) or (
            snapshot.trigger_kind is not None
            and (
                snapshot.triggered_at is None
                or snapshot.confirmed_at is None
                or snapshot.triggered_at >= snapshot.confirmed_at
                or not 1 <= snapshot.hold_count < snapshot.hold_required
            )
        ):
            raise SubingLifecycleContractError()
    elif snapshot.confirmation_source is ConfirmationSource.MOMENTUM_HOLD:
        if snapshot.trigger_kind != "macd_cross":
            raise SubingLifecycleContractError()
    elif snapshot.confirmation_source in {
        ConfirmationSource.PIVOT_BREAK_HOLD,
        ConfirmationSource.PIVOT_RETEST_REBREAK,
    } and snapshot.trigger_kind != "pivot_break":
        raise SubingLifecycleContractError()

    if snapshot.latest_transition is not None:
        transition = snapshot.latest_transition
        if (
            not isinstance(transition, SubingLifecycleTransition)
            or snapshot.observed_at is None
            or transition.transition_at > snapshot.observed_at
            or (key is not None and transition.opportunity_key != key)
            or (
                transition.transition_at == snapshot.observed_at
                and (
                    transition.to_stage is not snapshot.stage
                    or transition.opportunity_key != key
                )
            )
        ):
            raise SubingLifecycleContractError()
        replace(transition)

    if snapshot.last_confirmed_at is None and (
        snapshot.last_confirmed_stage is not LifecycleStage.IDLE
    ):
        raise SubingLifecycleContractError()
    if snapshot.last_confirmed_at is not None and (
        snapshot.last_confirmed_stage is not snapshot.stage
    ):
        raise SubingLifecycleContractError()
    if (
        snapshot.availability is LifecycleAvailability.READY
        and snapshot.observed_at is not None
        and (
            snapshot.last_confirmed_stage is not snapshot.stage
            or snapshot.last_confirmed_at != snapshot.observed_at
        )
    ):
        raise SubingLifecycleContractError()

    for evidence in (snapshot.volume_ratio_prev, snapshot.open_interest_delta):
        if evidence is not None and (
            not isinstance(evidence, Decimal) or not evidence.is_finite()
        ):
            raise SubingLifecycleContractError()


def _validate_trace_contract(trace: SubingLifecycleTrace) -> None:
    if (
        trace.formula_version != _FORMULA_VERSION
        or trace.policy_id != _POLICY_ID
        or not isinstance(trace.symbol, str)
        or not trace.symbol.strip()
        or trace.symbol != trace.symbol.strip()
        or not isinstance(trace.contract, str)
        or normalize_contract_for_symbol(trace.symbol, trace.contract)
        != trace.contract
        or type(trace.segment_start_trading_day) is not date
        or type(trace.confirmed_pivots) is not tuple
        or type(trace.completed_opportunities) is not tuple
        or type(trace.transitions) is not tuple
        or type(trace.snapshots) is not tuple
        or not isinstance(trace.current_snapshot, SubingLifecycleSnapshot)
    ):
        raise SubingLifecycleContractError()

    replace(trace.current_snapshot)
    if trace.snapshots:
        if trace.current_snapshot != trace.snapshots[-1]:
            raise SubingLifecycleContractError()
    elif trace.current_snapshot.observed_at is not None:
        raise SubingLifecycleContractError()

    observed_at: list[datetime] = []
    for snapshot in trace.snapshots:
        if not isinstance(snapshot, SubingLifecycleSnapshot):
            raise SubingLifecycleContractError()
        replace(snapshot)
        if snapshot.observed_at is None:
            raise SubingLifecycleContractError()
        observed_at.append(snapshot.observed_at)
        key = snapshot.opportunity_key
        if key is not None and not _key_matches_trace(key, trace):
            raise SubingLifecycleContractError()
    if any(left >= right for left, right in zip(observed_at, observed_at[1:])):
        raise SubingLifecycleContractError()

    transition_times: set[datetime] = set()
    previous_transition_at: datetime | None = None
    stage_by_opportunity: dict[SubingOpportunityKey, LifecycleStage] = {}
    terminal_opportunities: set[SubingOpportunityKey] = set()
    for transition in trace.transitions:
        if not isinstance(transition, SubingLifecycleTransition):
            raise SubingLifecycleContractError()
        replace(transition)
        if (
            not _key_matches_trace(transition.opportunity_key, trace)
            or transition.transition_at in transition_times
            or transition.transition_at not in observed_at
        ):
            raise SubingLifecycleContractError()
        if (
            previous_transition_at is not None
            and transition.transition_at <= previous_transition_at
        ):
            raise SubingLifecycleContractError()
        expected_from_stage = stage_by_opportunity.get(
            transition.opportunity_key,
            LifecycleStage.IDLE,
        )
        if (
            transition.opportunity_key in terminal_opportunities
            or transition.from_stage is not expected_from_stage
        ):
            raise SubingLifecycleContractError()
        stage_by_opportunity[transition.opportunity_key] = transition.to_stage
        if transition.to_stage is LifecycleStage.CLOSED:
            terminal_opportunities.add(transition.opportunity_key)
        transition_times.add(transition.transition_at)
        previous_transition_at = transition.transition_at

    latest_transition: SubingLifecycleTransition | None = None
    transitions_by_time = {
        transition.transition_at: transition for transition in trace.transitions
    }
    for snapshot in trace.snapshots:
        if snapshot.observed_at is None:
            raise SubingLifecycleContractError()
        projected_transition = transitions_by_time.get(snapshot.observed_at)
        if projected_transition is not None:
            latest_transition = projected_transition
        if snapshot.latest_transition != latest_transition:
            raise SubingLifecycleContractError()

    snapshots_by_time = {
        snapshot.observed_at: snapshot for snapshot in trace.snapshots
    }
    expected_completed: list[SubingLifecycleState] = []
    for transition in trace.transitions:
        if transition.to_stage is not LifecycleStage.CLOSED:
            continue
        closing_snapshot = snapshots_by_time.get(transition.transition_at)
        if (
            closing_snapshot is None
            or closing_snapshot.availability is not LifecycleAvailability.READY
            or closing_snapshot.stage is not LifecycleStage.CLOSED
            or closing_snapshot.opportunity_key != transition.opportunity_key
            or closing_snapshot.direction is not transition.opportunity_key.direction
        ):
            raise SubingLifecycleContractError()
        closes_confirmed_stage = transition.from_stage in {
            LifecycleStage.ENTRY_CONFIRMED,
            LifecycleStage.CONTINUATION,
            LifecycleStage.EXIT_RISK,
        }
        entry_transitions = tuple(
            candidate
            for candidate in trace.transitions
            if candidate.opportunity_key == transition.opportunity_key
            and candidate.to_stage is LifecycleStage.ENTRY_CONFIRMED
            and candidate.transition_at < transition.transition_at
        )
        if closes_confirmed_stage:
            if len(entry_transitions) != 1:
                raise SubingLifecycleContractError()
            confirmation_snapshot = snapshots_by_time.get(
                entry_transitions[0].transition_at
            )
            if (
                confirmation_snapshot is None
                or confirmation_snapshot.stage is not LifecycleStage.ENTRY_CONFIRMED
                or confirmation_snapshot.opportunity_key != transition.opportunity_key
                or confirmation_snapshot.confirmation_source is None
                or confirmation_snapshot.confirmed_at is None
                or closing_snapshot.confirmation_source
                is not confirmation_snapshot.confirmation_source
                or closing_snapshot.confirmed_at != confirmation_snapshot.confirmed_at
            ):
                raise SubingLifecycleContractError()
        elif (
            closing_snapshot.confirmation_source is not None
            or closing_snapshot.confirmed_at is not None
        ):
            raise SubingLifecycleContractError()
        expected_completed.append(
            SubingLifecycleState(
                availability=closing_snapshot.availability,
                direction=closing_snapshot.direction,
                stage=LifecycleStage.CLOSED,
                opportunity_key=closing_snapshot.opportunity_key,
                confirmation_source=closing_snapshot.confirmation_source,
                confirmed_at=closing_snapshot.confirmed_at,
            )
        )
    for state in trace.completed_opportunities:
        if not isinstance(state, SubingLifecycleState):
            raise SubingLifecycleContractError()
        replace(state)
    if trace.completed_opportunities != tuple(expected_completed):
        raise SubingLifecycleContractError()

    pivot_ids: set[str] = set()
    for pivot in trace.confirmed_pivots:
        if (
            not isinstance(pivot, ConfirmedPivot)
            or pivot.contract != trace.contract
            or pivot.segment_start_trading_day != trace.segment_start_trading_day
            or pivot.pivot_id in pivot_ids
            or (observed_at and pivot.confirmed_at > observed_at[-1])
        ):
            raise SubingLifecycleContractError()
        replace(pivot)
        pivot_ids.add(pivot.pivot_id)


def _key_matches_trace(
    key: SubingOpportunityKey,
    trace: SubingLifecycleTrace,
) -> bool:
    return (
        key.policy_id == trace.policy_id
        and key.symbol == trace.symbol
        and key.contract == trace.contract
        and key.segment_start_trading_day == trace.segment_start_trading_day
    )


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
    last_confirmed_stage = LifecycleStage.IDLE
    last_confirmed_at: datetime | None = None
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
                bars_5m[1:],
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

        if index == 0:
            snapshots.append(
                _snapshot(
                    policy=policy,
                    observed_at=bar_5m.bar_end,
                    anchor_bar_end=(None if anchor_bar is None else anchor_bar.bar_end),
                    availability=(
                        LifecycleAvailability.UNAVAILABLE
                        if boundary_error is not None
                        else LifecycleAvailability.READY
                    ),
                    unavailable_reason=boundary_error,
                    direction=SubingDirection.NONE,
                    opportunity=None,
                    latest_transition=None,
                    last_confirmed_at=(
                        bar_5m.bar_end if boundary_error is None else None
                    ),
                    boundary_reset="segment_changed",
                )
            )
            assert len(transitions) == transition_count_before
            continue

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
                    last_confirmed_stage=last_confirmed_stage,
                    last_confirmed_at=last_confirmed_at,
                )
            )
            assert len(transitions) == transition_count_before
            continue

        assert anchor_bar is not None and anchor_factor is not None
        factor_5m = factors_5m[index].snapshot
        factor_15m = anchor_factor.snapshot
        assert factor_5m is not None and factor_15m is not None
        direction = evaluate_subing_direction_context(
            factor_5m,
            factor_15m,
            calibration,
        )
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
        elif opportunity.stage in {
            LifecycleStage.ENTRY_CONFIRMED,
            LifecycleStage.CONTINUATION,
            LifecycleStage.EXIT_RISK,
        }:
            _advance_confirmed_opportunity(
                opportunity,
                transition_at=bar_5m.bar_end,
                trading_day=bar_5m.trading_day,
                factor_5m=factor_5m,
                factor_15m=factor_15m,
                same_boundary=anchor_bar.bar_end == bar_5m.bar_end,
                formal=formal,
                direction_context=direction,
                policy=policy,
                transitions=transitions,
                completed=completed,
            )
        elif opportunity.stage is LifecycleStage.SETUP_ARMED:
            if bar_5m.trading_day > opportunity.origin_trading_day:
                _close_setup(
                    opportunity,
                    transition_at=bar_5m.bar_end,
                    reason_code="UNCONFIRMED_TRADING_DAY_ROLLOVER",
                    transitions=transitions,
                    completed=completed,
                )
            elif formal_match and formal.direction is opportunity.key.direction:
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
        last_confirmed_stage = (
            opportunity.stage if opportunity is not None else LifecycleStage.IDLE
        )
        last_confirmed_at = bar_5m.bar_end
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
                last_confirmed_stage=last_confirmed_stage,
                last_confirmed_at=last_confirmed_at,
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
        boundary_reset="segment_changed",
    )
    trace_symbol, trace_contract = _canonical_trace_identity(symbol, contract)
    return SubingLifecycleTrace(
        formula_version=_FORMULA_VERSION,
        policy_id=_POLICY_ID,
        symbol=trace_symbol,
        contract=trace_contract,
        segment_start_trading_day=(
            segment_start_trading_day
            if type(segment_start_trading_day) is date
            else date.min
        ),
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
    if not is_accepted_subing_calibration(calibration):
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


def evaluate_subing_direction_context(
    factor_5m: SubingFactorSnapshot,
    factor_15m: SubingFactorSnapshot,
    calibration: SubingCalibration,
) -> SubingDirection:
    """Return the reducer's exact instantaneous 5m/15m direction context."""
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


def _advance_confirmed_opportunity(
    opportunity: _ActiveOpportunity,
    *,
    transition_at: datetime,
    trading_day: date,
    factor_5m: SubingFactorSnapshot,
    factor_15m: SubingFactorSnapshot,
    same_boundary: bool,
    formal: SubingSignalEvaluation,
    direction_context: SubingDirection,
    policy: SubingLifecyclePolicy,
    transitions: list[SubingLifecycleTransition],
    completed: list[SubingLifecycleState],
) -> None:
    opportunity.crossed_trading_day = (
        opportunity.crossed_trading_day
        or trading_day > opportunity.origin_trading_day
    )
    previous_stage = opportunity.stage
    hard_close_reason = _hard_close_reason(
        opportunity,
        factor_15m=factor_15m,
        same_boundary=same_boundary,
        formal=formal,
        direction_context=direction_context,
    )
    if hard_close_reason is not None:
        _close_confirmed(
            opportunity,
            transition_at=transition_at,
            from_stage=previous_stage,
            reason_code=hard_close_reason,
            transitions=transitions,
            completed=completed,
        )
        return

    if (
        previous_stage is LifecycleStage.EXIT_RISK
        and same_boundary
        and _recovery_allowed(opportunity, factor_5m, factor_15m)
    ):
        opportunity.stage = LifecycleStage.CONTINUATION
        opportunity.current_risk_codes = ()
        opportunity.lower_tf_risk_count = 0
        opportunity.risk_progress = None
        transitions.append(
            _transition(
                opportunity_key=opportunity.key,
                transition_at=transition_at,
                from_stage=LifecycleStage.EXIT_RISK,
                to_stage=LifecycleStage.CONTINUATION,
                reason_code="ANCHOR_RECOVERY_CONFIRMED",
            )
        )
        return

    anchor_risk_codes = (
        _anchor_soft_risk_codes(
            opportunity,
            factor_15m,
            direction_context=direction_context,
        )
        if same_boundary
        else ()
    )
    if anchor_risk_codes:
        opportunity.current_risk_codes = anchor_risk_codes
        opportunity.lower_tf_risk_count = 0
        opportunity.risk_progress = None
        if previous_stage is not LifecycleStage.EXIT_RISK:
            opportunity.stage = LifecycleStage.EXIT_RISK
            transitions.append(
                _transition(
                    opportunity_key=opportunity.key,
                    transition_at=transition_at,
                    from_stage=previous_stage,
                    to_stage=LifecycleStage.EXIT_RISK,
                    reason_code=anchor_risk_codes[0],
                )
            )
        return

    risk_codes = _lower_tf_risk_codes(opportunity, factor_5m)
    opportunity.current_risk_codes = risk_codes
    if risk_codes:
        opportunity.lower_tf_risk_count = min(
            opportunity.lower_tf_risk_count + 1,
            policy.lower_tf_risk_consecutive_bars,
        )
    else:
        opportunity.lower_tf_risk_count = 0
    opportunity.risk_progress = (
        "watching" if opportunity.lower_tf_risk_count == 1 else None
    )

    if (
        opportunity.lower_tf_risk_count
        >= policy.lower_tf_risk_consecutive_bars
        and previous_stage is not LifecycleStage.EXIT_RISK
    ):
        opportunity.stage = LifecycleStage.EXIT_RISK
        transitions.append(
            _transition(
                opportunity_key=opportunity.key,
                transition_at=transition_at,
                from_stage=previous_stage,
                to_stage=LifecycleStage.EXIT_RISK,
                reason_code=risk_codes[0],
            )
        )
    elif previous_stage is LifecycleStage.ENTRY_CONFIRMED:
        opportunity.stage = LifecycleStage.CONTINUATION
        transitions.append(
            _transition(
                opportunity_key=opportunity.key,
                transition_at=transition_at,
                from_stage=LifecycleStage.ENTRY_CONFIRMED,
                to_stage=LifecycleStage.CONTINUATION,
                reason_code=(
                    risk_codes[0] if risk_codes else "CONFIRMED_TREND_CONTINUES"
                ),
            )
        )


def _lower_tf_risk_codes(
    opportunity: _ActiveOpportunity,
    factor_5m: SubingFactorSnapshot,
) -> tuple[str, ...]:
    direction = opportunity.key.direction
    long = direction is SubingDirection.LONG
    opposite_cross = MacdCross.DEAD if long else MacdCross.GOLDEN
    codes: list[str] = []
    if (long and factor_5m.close < factor_5m.ema21) or (
        not long and factor_5m.close > factor_5m.ema21
    ):
        codes.append("LOWER_TF_EMA21_BREACH")
    if (long and factor_5m.slope_5_bps_per_bar < 0) or (
        not long and factor_5m.slope_5_bps_per_bar > 0
    ):
        codes.append("LOWER_TF_SLOPE5_REVERSAL")
    if factor_5m.macd_cross is opposite_cross:
        codes.append("LOWER_TF_MACD_OPPOSITE_CROSS")
    pivot = opportunity.bound_reference_pivot
    if pivot is not None and (
        (long and factor_5m.close < pivot.price)
        or (not long and factor_5m.close > pivot.price)
    ):
        codes.append("LOWER_TF_BOUND_PIVOT_REENTRY")
    return tuple(codes)


def _anchor_soft_risk_codes(
    opportunity: _ActiveOpportunity,
    factor_15m: SubingFactorSnapshot,
    *,
    direction_context: SubingDirection,
) -> tuple[str, ...]:
    long = opportunity.key.direction is SubingDirection.LONG
    opposite_cross = MacdCross.DEAD if long else MacdCross.GOLDEN
    anchor_side_preserved = (
        factor_15m.close > factor_15m.ema21
        if long
        else factor_15m.close < factor_15m.ema21
    )
    codes: list[str] = []
    if not anchor_side_preserved:
        codes.append("ANCHOR_EMA21_BREACH")
    if (long and factor_15m.slope_5_bps_per_bar < 0) or (
        not long and factor_15m.slope_5_bps_per_bar > 0
    ):
        codes.append("ANCHOR_SLOPE5_REVERSAL")
    if factor_15m.macd_cross is opposite_cross:
        codes.append("ANCHOR_MACD_OPPOSITE_CROSS")
    if direction_context is not opportunity.key.direction:
        codes.append("TIMEFRAME_ALIGNMENT_LOST")
    return tuple(codes)


def _recovery_allowed(
    opportunity: _ActiveOpportunity,
    factor_5m: SubingFactorSnapshot,
    factor_15m: SubingFactorSnapshot,
) -> bool:
    long = opportunity.key.direction is SubingDirection.LONG
    opposite_cross = MacdCross.DEAD if long else MacdCross.GOLDEN
    anchor_recovered = (
        factor_15m.close > factor_15m.ema21
        and factor_15m.slope_10_bps_per_bar > 0
        if long
        else factor_15m.close < factor_15m.ema21
        and factor_15m.slope_10_bps_per_bar < 0
    )
    pivot = opportunity.bound_reference_pivot
    pivot_side_preserved = pivot is None or (
        factor_15m.close >= pivot.price
        if long
        else factor_15m.close <= pivot.price
    )
    return (
        anchor_recovered
        and factor_15m.macd_cross is not opposite_cross
        and not _lower_tf_risk_codes(opportunity, factor_5m)
        and pivot_side_preserved
    )


def _hard_close_reason(
    opportunity: _ActiveOpportunity,
    *,
    factor_15m: SubingFactorSnapshot,
    same_boundary: bool,
    formal: SubingSignalEvaluation,
    direction_context: SubingDirection,
) -> str | None:
    direction = opportunity.key.direction
    opposite = (
        SubingDirection.SHORT
        if direction is SubingDirection.LONG
        else SubingDirection.LONG
    )
    if (
        formal.status is SubingSignalStatus.MATCHED
        and formal.direction is opposite
    ):
        return "OPPOSITE_FORMAL_V1"
    if direction_context is opposite:
        return "OPPOSITE_DIRECTION_CONTEXT_CONFIRMED"
    if not same_boundary:
        return None

    anchor_broken = (
        factor_15m.close < factor_15m.ema21
        and factor_15m.slope_10_bps_per_bar < 0
        if direction is SubingDirection.LONG
        else factor_15m.close > factor_15m.ema21
        and factor_15m.slope_10_bps_per_bar > 0
    )
    if anchor_broken:
        return "ANCHOR_TREND_BROKEN"

    pivot = opportunity.bound_reference_pivot
    pivot_confirmed = opportunity.confirmation_source in {
        ConfirmationSource.PIVOT_BREAK_HOLD,
        ConfirmationSource.PIVOT_RETEST_REBREAK,
    }
    if pivot_confirmed and pivot is not None and (
        (direction is SubingDirection.LONG and factor_15m.close < pivot.price)
        or (direction is SubingDirection.SHORT and factor_15m.close > pivot.price)
    ):
        return "STRUCTURE_INVALIDATED"
    return None


def _close_confirmed(
    opportunity: _ActiveOpportunity,
    *,
    transition_at: datetime,
    from_stage: LifecycleStage,
    reason_code: str,
    transitions: list[SubingLifecycleTransition],
    completed: list[SubingLifecycleState],
) -> None:
    opportunity.stage = LifecycleStage.CLOSED
    opportunity.current_risk_codes = ()
    opportunity.risk_progress = None
    opportunity.lower_tf_risk_count = 0
    transitions.append(
        _transition(
            opportunity_key=opportunity.key,
            transition_at=transition_at,
            from_stage=from_stage,
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
            confirmation_source=opportunity.confirmation_source,
            confirmed_at=opportunity.confirmed_at,
        )
    )


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
    return SubingLifecycleTransition(
        transition_id=_transition_identity(
            opportunity_key=opportunity_key,
            transition_at=transition_at,
            to_stage=to_stage,
        ),
        opportunity_key=opportunity_key,
        transition_at=transition_at,
        from_stage=from_stage,
        to_stage=to_stage,
        reason_codes=(reason_code,),
    )


def _transition_identity(
    *,
    opportunity_key: SubingOpportunityKey,
    transition_at: datetime,
    to_stage: LifecycleStage,
) -> str:
    return ":".join(
        (
            opportunity_key.policy_id,
            opportunity_key.symbol,
            opportunity_key.contract,
            opportunity_key.segment_start_trading_day.isoformat(),
            opportunity_key.direction.value,
            opportunity_key.origin_at.astimezone(UTC).isoformat(),
            transition_at.astimezone(UTC).isoformat(),
            to_stage.value,
        )
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
    last_confirmed_stage: LifecycleStage = LifecycleStage.IDLE,
    last_confirmed_at: datetime | None = None,
    boundary_reset: str | None = None,
) -> SubingLifecycleSnapshot:
    stage = opportunity.stage if opportunity is not None else LifecycleStage.IDLE
    return SubingLifecycleSnapshot(
        formula_version=_FORMULA_VERSION,
        policy_id=_POLICY_ID,
        research_only=True,
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
        hold_required=3,
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
        current_risk_codes=(
            opportunity.current_risk_codes if opportunity is not None else ()
        ),
        risk_progress=(opportunity.risk_progress if opportunity is not None else None),
        lower_tf_risk_count=(
            opportunity.lower_tf_risk_count if opportunity is not None else 0
        ),
        last_confirmed_stage=last_confirmed_stage,
        last_confirmed_at=last_confirmed_at,
        crossed_trading_day=(
            opportunity.crossed_trading_day if opportunity is not None else False
        ),
        boundary_reset=boundary_reset,
    )


def _canonical_trace_identity(symbol: object, contract: object) -> tuple[str, str]:
    if (
        isinstance(symbol, str)
        and isinstance(contract, str)
        and normalize_contract_for_symbol(symbol, contract) == contract
    ):
        return symbol, contract
    if isinstance(contract, str):
        normalized_contract = contract.strip().upper()
        candidate_symbol = normalized_contract.rstrip("0123456789")
        if (
            candidate_symbol
            and normalize_contract_for_symbol(candidate_symbol, normalized_contract)
            == normalized_contract
        ):
            return candidate_symbol, normalized_contract
    return "INVALID", "INVALID0001"
