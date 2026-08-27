from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from guiyi_quant.indicators import (
    FormalPolicy,
    IndicatorPoint,
    MacdState,
    get_formal_policy,
    get_indicator,
    initial_macd_state,
    require_formal_policy,
    step_macd,
)

from .domain import BarFrequency, CanonicalBar
from .subing_ema_trend import (
    PriceSide,
    SubingEmaTrendResult,
    SubingEmaTrendStreamState,
    initial_subing_ema_trend_state,
    step_subing_ema_trend,
)


class SubingFactorStatus(StrEnum):
    READY = "ready"
    INSUFFICIENT_DATA = "insufficient_data"


class MacdCross(StrEnum):
    GOLDEN = "golden"
    DEAD = "dead"
    NONE = "none"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class SubingFactorSnapshot:
    timeframe: BarFrequency
    bar_end: datetime
    trading_day: date
    contract: str
    segment_start_trading_day: date
    bar_source: str
    close: Decimal
    ema21: Decimal
    price_side: PriceSide
    slope_5_raw: Decimal
    slope_10_raw: Decimal
    slope_5_bps_per_bar: Decimal
    slope_10_bps_per_bar: Decimal
    macd_dif: Decimal
    macd_dea: Decimal
    macd_histogram: Decimal
    macd_cross: MacdCross
    macd_cross_level: Decimal
    macd_zero_distance_abs: Decimal
    macd_zero_distance_bps: Decimal
    volume: Decimal
    previous_volume: Decimal
    volume_ratio_prev: Decimal | None


@dataclass(frozen=True, slots=True)
class SubingFactorResult:
    status: SubingFactorStatus
    snapshot: SubingFactorSnapshot | None


@dataclass(frozen=True, slots=True)
class SubingFactorStreamState:
    timeframe: BarFrequency
    contract: str
    segment_start_trading_day: date
    latest_bar_source: str
    trend: SubingEmaTrendStreamState
    macd: MacdState
    previous_dif: IndicatorPoint | None
    previous_dea: IndicatorPoint | None
    previous_volume: Decimal | None
    last_bar_end: datetime | None


class SubingSignalStatus(StrEnum):
    MATCHED = "matched"
    NOT_MATCHED = "not_matched"
    RESEARCH_PENDING = "research_pending"
    INSUFFICIENT_DATA = "insufficient_data"


class SubingDirection(StrEnum):
    LONG = "long"
    SHORT = "short"
    NONE = "none"


class SubingConditionState(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    PENDING = "pending"
    UNAVAILABLE = "unavailable"


class SubingSignalResolution(StrEnum):
    HIGHER_TIMEFRAME_WINS = "higher_timeframe_wins"
    DIRECTION_CONFLICT = "direction_conflict"


@dataclass(frozen=True, slots=True)
class SubingConditionResult:
    code: str
    state: SubingConditionState


@dataclass(frozen=True, slots=True)
class SubingSignalEvaluation:
    status: SubingSignalStatus
    direction: SubingDirection
    trigger_timeframe: BarFrequency | None
    bar_end: datetime | None
    lower_tf_confirmation: bool
    resolution: SubingSignalResolution | None
    conditions: tuple[SubingConditionResult, ...]
    error_code: str | None = None

    def __post_init__(self) -> None:
        directional = self.direction in {SubingDirection.LONG, SubingDirection.SHORT}
        if (self.status is SubingSignalStatus.MATCHED and not directional) or (
            self.status
            in {SubingSignalStatus.NOT_MATCHED, SubingSignalStatus.INSUFFICIENT_DATA}
            and directional
        ):
            raise ValueError("SUBING_SIGNAL_STATE_INVALID")


class _CalibrationView(Protocol):
    @property
    def calibration_id(self) -> str | None: ...

    @property
    def accepted_timeframes(self) -> frozenset[BarFrequency]: ...

    @property
    def slope_flat_threshold_bps_per_bar(
        self,
    ) -> Mapping[BarFrequency, Decimal]: ...


_INTRADAY_TIMEFRAMES = frozenset({BarFrequency.M5, BarFrequency.M15})
_MACD_EQUIVALENCE_FIELDS = (
    "seed_policy",
    "histogram_scale",
    "lookback",
    "confirmed_only",
)
_SUBING_MACD_EQUIVALENCE_TARGET = (
    "sma_window",
    2,
    "fast12_slow26_signal9",
    True,
)


def initial_subing_factor_state(
    *,
    timeframe: BarFrequency,
    contract: str,
    segment_start_trading_day: date,
    latest_bar_source: str,
) -> SubingFactorStreamState:
    _validate_identity(
        contract=contract,
        latest_bar_source=latest_bar_source,
    )
    policy = require_formal_policy(
        "web_macd_legacy_v1",
        consumer="subing_factor_observation",
    )
    definition = get_indicator("macd")
    assert policy.policy_id == definition.formal_policy_id
    parameters = definition.default_parameters
    assert definition.seed_policy is not None
    assert definition.histogram_scale is not None
    return SubingFactorStreamState(
        timeframe=timeframe,
        contract=contract,
        segment_start_trading_day=segment_start_trading_day,
        latest_bar_source=latest_bar_source,
        trend=initial_subing_ema_trend_state(
            timeframe=timeframe,
            contract=contract,
            segment_start_trading_day=segment_start_trading_day,
        ),
        macd=initial_macd_state(
            int(parameters["fast"]),
            int(parameters["slow"]),
            int(parameters["signal"]),
            ema_seed_policy=definition.seed_policy,
            histogram_scale=definition.histogram_scale,
            round_digits=int(parameters["round_digits"]),
        ),
        previous_dif=None,
        previous_dea=None,
        previous_volume=None,
        last_bar_end=None,
    )


def step_subing_factor(
    state: SubingFactorStreamState,
    bar: CanonicalBar,
) -> tuple[SubingFactorStreamState, SubingFactorResult]:
    """Advance one physical-segment SuBing Factor observation."""

    _validate_factor_state(state)
    _validate_identity(
        contract=state.contract,
        latest_bar_source=state.latest_bar_source,
    )
    _validate_stream_bar(
        bar,
        segment_start_trading_day=state.segment_start_trading_day,
        last_bar_end=state.last_bar_end,
    )
    trend, trend_result = step_subing_ema_trend(state.trend, bar)
    macd, macd_points = step_macd(
        state.macd,
        float(bar.close),
        bar_end=bar.bar_end.isoformat(),
    )
    dif, dea, histogram = macd_points
    result = _result_for_step(
        bar,
        timeframe=state.timeframe,
        contract=state.contract,
        segment_start_trading_day=state.segment_start_trading_day,
        bar_source=state.latest_bar_source,
        trend_result=trend_result,
        current_dif=dif,
        previous_dif=state.previous_dif,
        current_dea=dea,
        previous_dea=state.previous_dea,
        current_histogram=histogram,
        previous_volume=state.previous_volume,
    )
    return (
        SubingFactorStreamState(
            timeframe=state.timeframe,
            contract=state.contract,
            segment_start_trading_day=state.segment_start_trading_day,
            latest_bar_source=state.latest_bar_source,
            trend=trend,
            macd=macd,
            previous_dif=dif,
            previous_dea=dea,
            previous_volume=bar.volume,
            last_bar_end=bar.bar_end,
        ),
        result,
    )


def evaluate_subing_signal(
    primary: SubingFactorResult,
    *,
    companion: SubingFactorResult | None,
    calibration: _CalibrationView,
) -> SubingSignalEvaluation:
    """Evaluate one pure, confirmed Factor pair without persistence or I/O."""

    primary_snapshot = _ready_signal_snapshot(primary)
    if primary_snapshot is None:
        return _signal_state(
            SubingSignalStatus.INSUFFICIENT_DATA,
            error_code="SUBING_FACTOR_UNAVAILABLE",
            condition=SubingConditionResult(
                "PRIMARY_FACTOR_READY",
                SubingConditionState.UNAVAILABLE,
            ),
        )

    candidate = _candidate_direction(primary_snapshot, None)
    if primary_snapshot.timeframe is BarFrequency.D1:
        return _signal_state(
            SubingSignalStatus.RESEARCH_PENDING,
            direction=candidate,
            trigger_timeframe=primary_snapshot.timeframe,
            bar_end=primary_snapshot.bar_end,
            error_code="SUBING_DAILY_RESEARCH_PENDING",
            condition=SubingConditionResult(
                "INTRADAY_CALIBRATION_SCOPE",
                SubingConditionState.PENDING,
            ),
        )
    if primary_snapshot.timeframe not in _INTRADAY_TIMEFRAMES:
        return _signal_state(
            SubingSignalStatus.INSUFFICIENT_DATA,
            trigger_timeframe=primary_snapshot.timeframe,
            bar_end=primary_snapshot.bar_end,
            error_code="SUBING_TIMEFRAME_UNSUPPORTED",
            condition=SubingConditionResult(
                "PRIMARY_TIMEFRAME_SUPPORTED",
                SubingConditionState.UNAVAILABLE,
            ),
        )

    companion_snapshot = (
        None if companion is None else _ready_signal_snapshot(companion)
    )
    if companion_snapshot is None:
        return _signal_state(
            SubingSignalStatus.INSUFFICIENT_DATA,
            trigger_timeframe=primary_snapshot.timeframe,
            bar_end=primary_snapshot.bar_end,
            error_code="SUBING_COMPANION_UNAVAILABLE",
            condition=SubingConditionResult(
                "COMPANION_FACTOR_READY",
                SubingConditionState.UNAVAILABLE,
            ),
        )
    expected_companion = (
        BarFrequency.M15
        if primary_snapshot.timeframe is BarFrequency.M5
        else BarFrequency.M5
    )
    if companion_snapshot.timeframe is not expected_companion:
        return _signal_state(
            SubingSignalStatus.INSUFFICIENT_DATA,
            trigger_timeframe=primary_snapshot.timeframe,
            bar_end=primary_snapshot.bar_end,
            error_code="SUBING_COMPANION_TIMEFRAME_MISMATCH",
            condition=SubingConditionResult(
                "COMPANION_TIMEFRAME",
                SubingConditionState.UNAVAILABLE,
            ),
        )
    if companion_snapshot.bar_end > primary_snapshot.bar_end:
        return _signal_state(
            SubingSignalStatus.INSUFFICIENT_DATA,
            trigger_timeframe=primary_snapshot.timeframe,
            bar_end=primary_snapshot.bar_end,
            error_code="SUBING_COMPANION_FUTURE",
            condition=SubingConditionResult(
                "COMPANION_CONFIRMED_CUTOFF",
                SubingConditionState.UNAVAILABLE,
            ),
        )
    if (
        companion_snapshot.contract != primary_snapshot.contract
        or companion_snapshot.segment_start_trading_day
        != primary_snapshot.segment_start_trading_day
    ):
        return _signal_state(
            SubingSignalStatus.INSUFFICIENT_DATA,
            trigger_timeframe=primary_snapshot.timeframe,
            bar_end=primary_snapshot.bar_end,
            error_code="SUBING_COMPANION_IDENTITY_MISMATCH",
            condition=SubingConditionResult(
                "COMPANION_SEGMENT_IDENTITY",
                SubingConditionState.UNAVAILABLE,
            ),
        )
    if primary_snapshot.volume_ratio_prev is None:
        return _signal_state(
            SubingSignalStatus.INSUFFICIENT_DATA,
            trigger_timeframe=primary_snapshot.timeframe,
            bar_end=primary_snapshot.bar_end,
            error_code="SUBING_VOLUME_RATIO_UNAVAILABLE",
            condition=SubingConditionResult(
                "PRIMARY_VOLUME_RATIO",
                SubingConditionState.UNAVAILABLE,
            ),
        )

    candidate = _candidate_direction(primary_snapshot, companion_snapshot)
    condition_direction = (
        candidate
        if candidate is not SubingDirection.NONE
        else _condition_direction(primary_snapshot)
    )
    known_conditions = _known_direction_conditions(
        condition_direction,
        primary_snapshot,
        companion_snapshot,
    )
    if any(
        condition.state is SubingConditionState.FAIL for condition in known_conditions
    ):
        return _signal_state(
            SubingSignalStatus.NOT_MATCHED,
            trigger_timeframe=primary_snapshot.timeframe,
            bar_end=primary_snapshot.bar_end,
            conditions=known_conditions,
        )
    thresholds = _calibration_thresholds(
        calibration,
        primary_snapshot.timeframe,
        companion_snapshot.timeframe,
    )
    if thresholds is None:
        return _signal_state(
            SubingSignalStatus.RESEARCH_PENDING,
            direction=candidate,
            trigger_timeframe=primary_snapshot.timeframe,
            bar_end=primary_snapshot.bar_end,
            error_code="SUBING_CALIBRATION_PENDING",
            condition=SubingConditionResult(
                "SLOPE_CALIBRATION",
                SubingConditionState.PENDING,
            ),
        )

    policy_error = _subing_macd_policy_error()
    if policy_error is not None:
        return _signal_state(
            SubingSignalStatus.RESEARCH_PENDING,
            direction=candidate,
            trigger_timeframe=primary_snapshot.timeframe,
            bar_end=primary_snapshot.bar_end,
            error_code=policy_error,
            condition=SubingConditionResult(
                "MACD_POLICY_EQUIVALENCE",
                (
                    SubingConditionState.PENDING
                    if policy_error == "SUBING_MACD_POLICY_UNAVAILABLE"
                    else SubingConditionState.FAIL
                ),
            ),
        )

    primary_threshold, companion_threshold = thresholds
    long_conditions = _direction_conditions(
        SubingDirection.LONG,
        primary_snapshot,
        companion_snapshot,
        primary_threshold=primary_threshold,
        companion_threshold=companion_threshold,
    )
    if all(
        condition.state is SubingConditionState.PASS for condition in long_conditions
    ):
        return _signal_state(
            SubingSignalStatus.MATCHED,
            direction=SubingDirection.LONG,
            trigger_timeframe=primary_snapshot.timeframe,
            bar_end=primary_snapshot.bar_end,
            conditions=long_conditions,
        )

    short_conditions = _direction_conditions(
        SubingDirection.SHORT,
        primary_snapshot,
        companion_snapshot,
        primary_threshold=primary_threshold,
        companion_threshold=companion_threshold,
    )
    if all(
        condition.state is SubingConditionState.PASS for condition in short_conditions
    ):
        return _signal_state(
            SubingSignalStatus.MATCHED,
            direction=SubingDirection.SHORT,
            trigger_timeframe=primary_snapshot.timeframe,
            bar_end=primary_snapshot.bar_end,
            conditions=short_conditions,
        )

    failed_conditions = (
        short_conditions
        if _condition_direction(primary_snapshot) is SubingDirection.SHORT
        else long_conditions
    )
    return _signal_state(
        SubingSignalStatus.NOT_MATCHED,
        trigger_timeframe=primary_snapshot.timeframe,
        bar_end=primary_snapshot.bar_end,
        conditions=failed_conditions,
    )


def resolve_same_boundary_subing_signals(
    first: SubingSignalEvaluation,
    second: SubingSignalEvaluation,
) -> SubingSignalEvaluation:
    """Resolve the two intraday evaluations for one confirmed bar boundary."""

    by_timeframe = {
        first.trigger_timeframe: first,
        second.trigger_timeframe: second,
    }
    if set(by_timeframe) != _INTRADAY_TIMEFRAMES or first.bar_end != second.bar_end:
        raise ValueError("same-boundary 5m and 15m evaluations are required")
    m5 = by_timeframe[BarFrequency.M5]
    m15 = by_timeframe[BarFrequency.M15]
    if (
        m5.status is SubingSignalStatus.MATCHED
        and m15.status is SubingSignalStatus.MATCHED
    ):
        if m5.direction is not m15.direction:
            return SubingSignalEvaluation(
                status=SubingSignalStatus.NOT_MATCHED,
                direction=SubingDirection.NONE,
                trigger_timeframe=None,
                bar_end=m15.bar_end,
                lower_tf_confirmation=False,
                resolution=SubingSignalResolution.DIRECTION_CONFLICT,
                conditions=(),
                error_code="SUBING_SIGNAL_DIRECTION_CONFLICT",
            )
        return replace(
            m15,
            lower_tf_confirmation=True,
            resolution=SubingSignalResolution.HIGHER_TIMEFRAME_WINS,
        )
    if m15.status is SubingSignalStatus.MATCHED:
        return m15
    if m5.status is SubingSignalStatus.MATCHED:
        return m5
    return m15


def resolve_subing_matched_signal(
    primary: SubingFactorResult,
    companion: SubingFactorResult | None,
    *,
    calibration: _CalibrationView,
) -> SubingSignalEvaluation | None:
    """Resolve one confirmed Factor pair without I/O or persistence."""

    primary_signal = evaluate_subing_signal(
        primary,
        companion=companion,
        calibration=calibration,
    )
    if not _same_ready_boundary(primary, companion):
        return (
            primary_signal
            if primary_signal.status is SubingSignalStatus.MATCHED
            else None
        )
    assert companion is not None
    reciprocal = evaluate_subing_signal(
        companion,
        companion=primary,
        calibration=calibration,
    )
    if (
        primary_signal.status is SubingSignalStatus.MATCHED
        and reciprocal.status is SubingSignalStatus.MATCHED
    ):
        return resolve_same_boundary_subing_signals(primary_signal, reciprocal)
    if primary_signal.status is SubingSignalStatus.MATCHED:
        return primary_signal
    if reciprocal.status is SubingSignalStatus.MATCHED:
        return reciprocal
    return None


def _same_ready_boundary(
    primary: SubingFactorResult,
    companion: SubingFactorResult | None,
) -> bool:
    return (
        primary.status is SubingFactorStatus.READY
        and primary.snapshot is not None
        and companion is not None
        and companion.status is SubingFactorStatus.READY
        and companion.snapshot is not None
        and primary.snapshot.bar_end == companion.snapshot.bar_end
    )


def _ready_signal_snapshot(
    result: SubingFactorResult,
) -> SubingFactorSnapshot | None:
    if result.status is not SubingFactorStatus.READY:
        return None
    return result.snapshot


def _candidate_direction(
    primary: SubingFactorSnapshot,
    companion: SubingFactorSnapshot | None,
) -> SubingDirection:
    if (
        primary.price_side is PriceSide.ABOVE
        and primary.slope_5_bps_per_bar > 0
        and primary.slope_10_bps_per_bar > 0
        and primary.macd_cross is MacdCross.GOLDEN
        and (
            companion is None
            or (
                companion.price_side is PriceSide.ABOVE
                and companion.slope_5_bps_per_bar > 0
                and companion.slope_10_bps_per_bar > 0
            )
        )
    ):
        return SubingDirection.LONG
    if (
        primary.price_side is PriceSide.BELOW
        and primary.slope_5_bps_per_bar < 0
        and primary.slope_10_bps_per_bar < 0
        and primary.macd_cross is MacdCross.DEAD
        and (
            companion is None
            or (
                companion.price_side is PriceSide.BELOW
                and companion.slope_5_bps_per_bar < 0
                and companion.slope_10_bps_per_bar < 0
            )
        )
    ):
        return SubingDirection.SHORT
    return SubingDirection.NONE


def _condition_direction(primary: SubingFactorSnapshot) -> SubingDirection:
    if primary.macd_cross is MacdCross.GOLDEN:
        return SubingDirection.LONG
    if primary.macd_cross is MacdCross.DEAD:
        return SubingDirection.SHORT
    if primary.price_side is PriceSide.ABOVE:
        return SubingDirection.LONG
    if primary.price_side is PriceSide.BELOW:
        return SubingDirection.SHORT
    if primary.slope_10_bps_per_bar < 0:
        return SubingDirection.SHORT
    return SubingDirection.LONG


def _calibration_thresholds(
    calibration: _CalibrationView,
    primary_timeframe: BarFrequency,
    companion_timeframe: BarFrequency,
) -> tuple[Decimal, Decimal] | None:
    if calibration.calibration_id is None:
        return None
    required = {primary_timeframe, companion_timeframe}
    if not required.issubset(calibration.accepted_timeframes):
        return None
    primary = calibration.slope_flat_threshold_bps_per_bar.get(primary_timeframe)
    companion = calibration.slope_flat_threshold_bps_per_bar.get(companion_timeframe)
    if primary is None or companion is None:
        return None
    return primary, companion


def _subing_macd_policy_error() -> str | None:
    try:
        observation = get_formal_policy("web_macd_legacy_v1")
        signal = require_formal_policy(
            "subing_macd_sma_window_scale2_v1",
            consumer="subing_signal",
        )
    except (KeyError, ValueError):
        return "SUBING_MACD_POLICY_UNAVAILABLE"
    if not (
        _policy_equivalence(observation)
        == _policy_equivalence(signal)
        == _SUBING_MACD_EQUIVALENCE_TARGET
    ):
        return "SUBING_MACD_POLICY_MISMATCH"
    return None


def _policy_equivalence(policy: FormalPolicy) -> tuple[object, ...]:
    return tuple(getattr(policy, field) for field in _MACD_EQUIVALENCE_FIELDS)


def _direction_conditions(
    direction: SubingDirection,
    primary: SubingFactorSnapshot,
    companion: SubingFactorSnapshot,
    *,
    primary_threshold: Decimal,
    companion_threshold: Decimal,
) -> tuple[SubingConditionResult, ...]:
    assert primary.volume_ratio_prev is not None
    if direction is SubingDirection.LONG:
        checks = (
            ("PRIMARY_PRICE_DIRECTION", primary.price_side is PriceSide.ABOVE),
            (
                "PRIMARY_SLOPE5_THRESHOLD",
                primary.slope_5_bps_per_bar > primary_threshold,
            ),
            ("PRIMARY_SLOPE10_DIRECTION", primary.slope_10_bps_per_bar > 0),
            ("PRIMARY_MACD_CROSS", primary.macd_cross is MacdCross.GOLDEN),
            ("PRIMARY_VOLUME_RATIO", primary.volume_ratio_prev >= 3),
            ("COMPANION_PRICE_DIRECTION", companion.price_side is PriceSide.ABOVE),
            (
                "COMPANION_SLOPE5_THRESHOLD",
                companion.slope_5_bps_per_bar > companion_threshold,
            ),
            ("COMPANION_SLOPE10_DIRECTION", companion.slope_10_bps_per_bar > 0),
        )
    elif direction is SubingDirection.SHORT:
        checks = (
            ("PRIMARY_PRICE_DIRECTION", primary.price_side is PriceSide.BELOW),
            (
                "PRIMARY_SLOPE5_THRESHOLD",
                primary.slope_5_bps_per_bar < -primary_threshold,
            ),
            ("PRIMARY_SLOPE10_DIRECTION", primary.slope_10_bps_per_bar < 0),
            ("PRIMARY_MACD_CROSS", primary.macd_cross is MacdCross.DEAD),
            ("PRIMARY_VOLUME_RATIO", primary.volume_ratio_prev >= 3),
            ("COMPANION_PRICE_DIRECTION", companion.price_side is PriceSide.BELOW),
            (
                "COMPANION_SLOPE5_THRESHOLD",
                companion.slope_5_bps_per_bar < -companion_threshold,
            ),
            ("COMPANION_SLOPE10_DIRECTION", companion.slope_10_bps_per_bar < 0),
        )
    else:
        raise ValueError("LONG or SHORT direction required")
    return (
        *tuple(
            SubingConditionResult(
                code,
                SubingConditionState.PASS if passed else SubingConditionState.FAIL,
            )
            for code, passed in checks
        ),
        SubingConditionResult(
            "MACD_POLICY_EQUIVALENCE",
            SubingConditionState.PASS,
        ),
    )


def _known_direction_conditions(
    direction: SubingDirection,
    primary: SubingFactorSnapshot,
    companion: SubingFactorSnapshot,
) -> tuple[SubingConditionResult, ...]:
    assert primary.volume_ratio_prev is not None
    if direction is SubingDirection.LONG:
        checks = (
            ("PRIMARY_PRICE_DIRECTION", primary.price_side is PriceSide.ABOVE),
            ("PRIMARY_SLOPE5_DIRECTION", primary.slope_5_bps_per_bar > 0),
            ("PRIMARY_SLOPE10_DIRECTION", primary.slope_10_bps_per_bar > 0),
            ("PRIMARY_MACD_CROSS", primary.macd_cross is MacdCross.GOLDEN),
            ("PRIMARY_VOLUME_RATIO", primary.volume_ratio_prev >= 3),
            ("COMPANION_PRICE_DIRECTION", companion.price_side is PriceSide.ABOVE),
            ("COMPANION_SLOPE5_DIRECTION", companion.slope_5_bps_per_bar > 0),
            ("COMPANION_SLOPE10_DIRECTION", companion.slope_10_bps_per_bar > 0),
        )
    elif direction is SubingDirection.SHORT:
        checks = (
            ("PRIMARY_PRICE_DIRECTION", primary.price_side is PriceSide.BELOW),
            ("PRIMARY_SLOPE5_DIRECTION", primary.slope_5_bps_per_bar < 0),
            ("PRIMARY_SLOPE10_DIRECTION", primary.slope_10_bps_per_bar < 0),
            ("PRIMARY_MACD_CROSS", primary.macd_cross is MacdCross.DEAD),
            ("PRIMARY_VOLUME_RATIO", primary.volume_ratio_prev >= 3),
            ("COMPANION_PRICE_DIRECTION", companion.price_side is PriceSide.BELOW),
            ("COMPANION_SLOPE5_DIRECTION", companion.slope_5_bps_per_bar < 0),
            ("COMPANION_SLOPE10_DIRECTION", companion.slope_10_bps_per_bar < 0),
        )
    else:
        raise ValueError("LONG or SHORT direction required")
    return tuple(
        SubingConditionResult(
            code,
            SubingConditionState.PASS if passed else SubingConditionState.FAIL,
        )
        for code, passed in checks
    )


def _signal_state(
    status: SubingSignalStatus,
    *,
    direction: SubingDirection = SubingDirection.NONE,
    trigger_timeframe: BarFrequency | None = None,
    bar_end: datetime | None = None,
    conditions: tuple[SubingConditionResult, ...] = (),
    condition: SubingConditionResult | None = None,
    error_code: str | None = None,
) -> SubingSignalEvaluation:
    if condition is not None:
        conditions = (condition,)
    return SubingSignalEvaluation(
        status=status,
        direction=direction,
        trigger_timeframe=trigger_timeframe,
        bar_end=bar_end,
        lower_tf_confirmation=False,
        resolution=None,
        conditions=conditions,
        error_code=error_code,
    )


def calculate_subing_factor_series(
    bars: Sequence[CanonicalBar],
    *,
    timeframe: BarFrequency,
    contract: str,
    segment_start_trading_day: date,
    latest_bar_source: str,
) -> tuple[SubingFactorResult, ...]:
    """Calculate aligned, segment-local SuBing Factor observations."""

    _validate_inputs(
        bars,
        contract=contract,
        segment_start_trading_day=segment_start_trading_day,
        latest_bar_source=latest_bar_source,
    )
    state = initial_subing_factor_state(
        timeframe=timeframe,
        contract=contract,
        segment_start_trading_day=segment_start_trading_day,
        latest_bar_source=latest_bar_source,
    )
    results: list[SubingFactorResult] = []
    for bar in bars:
        state, result = step_subing_factor(state, bar)
        results.append(result)
    return tuple(results)


def calculate_subing_factor(
    bars: Sequence[CanonicalBar],
    *,
    timeframe: BarFrequency,
    contract: str,
    segment_start_trading_day: date,
    latest_bar_source: str,
) -> SubingFactorResult:
    """Return the latest aligned SuBing Factor result."""

    results = calculate_subing_factor_series(
        bars,
        timeframe=timeframe,
        contract=contract,
        segment_start_trading_day=segment_start_trading_day,
        latest_bar_source=latest_bar_source,
    )
    if not results:
        return _insufficient()
    return results[-1]


def _result_for_step(
    bar: CanonicalBar,
    *,
    timeframe: BarFrequency,
    contract: str,
    segment_start_trading_day: date,
    bar_source: str,
    trend_result: SubingEmaTrendResult,
    current_dif: IndicatorPoint,
    previous_dif: IndicatorPoint | None,
    current_dea: IndicatorPoint,
    previous_dea: IndicatorPoint | None,
    current_histogram: IndicatorPoint,
    previous_volume: Decimal | None,
) -> SubingFactorResult:
    trend = trend_result.snapshot
    if trend is None or previous_dif is None or previous_dea is None:
        return _insufficient()

    required_points = (
        current_dif,
        previous_dif,
        current_dea,
        previous_dea,
        current_histogram,
    )
    if not all(_point_has_value(point) for point in required_points):
        return _insufficient()

    if bar.close == 0 or previous_volume is None:
        return _insufficient()

    dif = _point_decimal(current_dif)
    previous_dif_value = _point_decimal(previous_dif)
    dea = _point_decimal(current_dea)
    previous_dea_value = _point_decimal(previous_dea)
    histogram = _point_decimal(current_histogram)
    cross_level = (dif + dea) / Decimal(2)
    zero_distance_abs = abs(cross_level)

    if previous_dif_value <= previous_dea_value and dif > dea:
        cross = MacdCross.GOLDEN
    elif previous_dif_value >= previous_dea_value and dif < dea:
        cross = MacdCross.DEAD
    else:
        cross = MacdCross.NONE

    volume_ratio = None
    if previous_volume > 0:
        volume_ratio = bar.volume / previous_volume

    return SubingFactorResult(
        status=SubingFactorStatus.READY,
        snapshot=SubingFactorSnapshot(
            timeframe=timeframe,
            bar_end=bar.bar_end,
            trading_day=bar.trading_day,
            contract=contract,
            segment_start_trading_day=segment_start_trading_day,
            bar_source=bar_source,
            close=bar.close,
            ema21=trend.ema21,
            price_side=trend.price_side,
            slope_5_raw=trend.slope_5_raw,
            slope_10_raw=trend.slope_10_raw,
            slope_5_bps_per_bar=trend.slope_5_bps_per_bar,
            slope_10_bps_per_bar=trend.slope_10_bps_per_bar,
            macd_dif=dif,
            macd_dea=dea,
            macd_histogram=histogram,
            macd_cross=cross,
            macd_cross_level=cross_level,
            macd_zero_distance_abs=zero_distance_abs,
            macd_zero_distance_bps=zero_distance_abs / bar.close * Decimal(10000),
            volume=bar.volume,
            previous_volume=previous_volume,
            volume_ratio_prev=volume_ratio,
        ),
    )


def _validate_inputs(
    bars: Sequence[CanonicalBar],
    *,
    contract: str,
    segment_start_trading_day: date,
    latest_bar_source: str,
) -> None:
    _validate_identity(
        contract=contract,
        latest_bar_source=latest_bar_source,
    )
    if any(bar.trading_day < segment_start_trading_day for bar in bars):
        raise ValueError("bars before segment_start_trading_day are not allowed")
    if any(
        current.bar_end <= previous.bar_end
        for previous, current in zip(bars, bars[1:], strict=False)
    ):
        raise ValueError("bar_end must be strictly increasing")


def _validate_identity(*, contract: str, latest_bar_source: str) -> None:
    if not contract.strip():
        raise ValueError("contract must not be empty")
    if not latest_bar_source.strip():
        raise ValueError("latest_bar_source must not be empty")


def _validate_factor_state(state: SubingFactorStreamState) -> None:
    if (
        state.trend.timeframe is not state.timeframe
        or state.trend.contract != state.contract
        or state.trend.segment_start_trading_day != state.segment_start_trading_day
        or state.trend.last_bar_end != state.last_bar_end
    ):
        raise ValueError("SUBING_FACTOR_STATE_IDENTITY_MISMATCH")


def _validate_stream_bar(
    bar: CanonicalBar,
    *,
    segment_start_trading_day: date,
    last_bar_end: datetime | None,
) -> None:
    if bar.trading_day < segment_start_trading_day:
        raise ValueError("bars before segment_start_trading_day are not allowed")
    if last_bar_end is not None and bar.bar_end <= last_bar_end:
        raise ValueError("bar_end must be strictly increasing")


def _point_has_value(point: IndicatorPoint) -> bool:
    return point.ready and point.valid and point.value is not None


def _point_decimal(point: IndicatorPoint) -> Decimal:
    value = point.value
    assert value is not None
    return Decimal(str(value))


def _insufficient() -> SubingFactorResult:
    return SubingFactorResult(
        status=SubingFactorStatus.INSUFFICIENT_DATA,
        snapshot=None,
    )
