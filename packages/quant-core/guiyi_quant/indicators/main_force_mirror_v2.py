"""Historical Main Force Mirror V2 pressure and frozen caution kernel.

The output is a directional position-pressure proxy for manual research.  It
does not measure fund flow, infer participant identity, emit trade signals, or
create orders.  Member observations are an inert Task 4 input seam here.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence, Sized
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Literal, SupportsFloat, SupportsIndex, cast

import numpy as np


INDICATOR_CODE: Literal["main_force_mirror_v2"] = "main_force_mirror_v2"
INDICATOR_VERSION: Literal["futures-member-research-v2"] = (
    "futures-member-research-v2"
)
FORMAL_POLICY_ID: Literal["main_force_mirror_observation_v2"] = (
    "main_force_mirror_observation_v2"
)

MainForceMirrorV2State = Literal[
    "long_build",
    "short_build",
    "short_cover",
    "long_liquidation",
    "turnover",
]
MainForceMirrorV2Caution = Literal[
    "long_chase_caution",
    "short_chase_caution",
]
MainForceMirrorV2ResetBoundary = Literal[
    "series_start",
    "physical_contract_change",
    "invalid_input",
]
MainForceMirrorV2RearmReason = Literal[
    "long_range",
    "long_build",
    "short_range",
    "short_build",
]
MemberRankDirection = Literal["long", "short", "neutral"]
MemberRankRelation = Literal[
    "strong_aligned",
    "aligned",
    "divergent",
    "neutral",
    "unavailable",
]

_DEFAULT_PARAMETERS_LITERAL: dict[str, int | float | str] = {
    "atr_period": 14,
    "volume_window": 20,
    "oi_impulse_ema_period": 20,
    "range_window": 20,
    "pressure_divergence_window": 10,
    "accumulated_ema_period": 5,
    "direction_price_weight": 0.7,
    "direction_clv_weight": 0.3,
    "direction_deadband": 0.15,
    "oi_deadband": 0.25,
    "caution_threshold": 70,
    "rearm_score_threshold": 40,
    "rearm_low_score_bars": 3,
    "rearm_build_bars": 2,
    "member_neutral_strength": 0.5,
    "member_strong_strength": 2.0,
    "member_baseline_days": 60,
    "member_min_baseline_days": 20,
    "round_digits": 6,
    "rounding_policy": "half_away_from_zero_binary64",
}
DEFAULT_PARAMETERS: Mapping[str, int | float | str] = MappingProxyType(
    _DEFAULT_PARAMETERS_LITERAL
)

_VOLUME_RATIO_CLIP = 3.0
_PRICE_IMPULSE_CLIP = 3.0
_OI_IMPULSE_CLIP = 3.0
_STRENGTH_SCALE = 25.0
_TURNOVER_DISPLAY_CAP = 15.0
_UPPER_LOCATION_THRESHOLD = 0.85
_LOWER_LOCATION_THRESHOLD = 0.15
_LIQUIDATION_DOMINATED_OI_THRESHOLD = 0.5
_PRESSURE_CONFIRMATION_RATIO = 0.7
_HIGH_VOLUME_THRESHOLD = 1.5
_CLV_REJECTION_THRESHOLD = 0.25
_WICK_REJECTION_THRESHOLD = 0.35
_LONG_REARM_RANGE_THRESHOLD = 0.65
_SHORT_REARM_RANGE_THRESHOLD = 0.35

_PHYSICAL_CONTRACT_MISSING = "MFM_V2_PHYSICAL_CONTRACT_MISSING"
_MARKET_IDENTITY_CONFLICT = "MFM_V2_MARKET_IDENTITY_CONFLICT"
_TIMESTAMP_INVALID = "MFM_V2_TIMESTAMP_INVALID"
_OPEN_INTEREST_UNAVAILABLE = "MFM_V2_OPEN_INTEREST_UNAVAILABLE"
_INPUT_INVALID = "MFM_V2_INPUT_INVALID"
_WARMUP = "MFM_V2_WARMUP"
_CAUTION_WARMUP = "MFM_V2_CAUTION_WARMUP"
_ATR_INVALID = "MFM_V2_ATR_INVALID"
_VOLUME_BASELINE_INVALID = "MFM_V2_VOLUME_BASELINE_INVALID"
_RANGE_INVALID = "MFM_V2_RANGE_INVALID"
_CAUTION_DIRECTION_CONFLICT = "MFM_V2_CAUTION_DIRECTION_CONFLICT"
_MEMBER_INPUT_INVALID = "MFM_V2_MEMBER_INPUT_INVALID"
_MEMBER_WARMUP = "MFM_V2_MEMBER_WARMUP"


@dataclass(frozen=True, slots=True)
class MemberRankDailyInput:
    """Complete T-1 Top20 aggregates selected by the read-only service."""

    member_trade_date: date
    long_total: Decimal
    short_total: Decimal
    long_change_total: Decimal
    short_change_total: Decimal
    top5_volume_total: Decimal
    top20_volume_total: Decimal

    def is_valid(self) -> bool:
        values = (
            self.long_total,
            self.short_total,
            self.long_change_total,
            self.short_change_total,
            self.top5_volume_total,
            self.top20_volume_total,
        )
        if not all(value.is_finite() for value in values):
            return False
        if (
            self.long_total < 0
            or self.short_total < 0
            or self.top5_volume_total < 0
            or self.top20_volume_total <= 0
            or self.top5_volume_total > self.top20_volume_total
        ):
            return False
        return self.long_total + self.short_total > 0

    @property
    def change_bias(self) -> Decimal:
        return (self.long_change_total - self.short_change_total) / (
            self.long_total + self.short_total
        )

    @property
    def position_skew(self) -> Decimal:
        return (self.long_total - self.short_total) / (
            self.long_total + self.short_total
        )

    @property
    def top5_volume_share(self) -> Decimal:
        return self.top5_volume_total / self.top20_volume_total


@dataclass(frozen=True, slots=True)
class MemberRankObservation:
    status: Literal["ready", "unavailable"]
    member_trade_date: date | None
    direction: MemberRankDirection | None
    change_bias: float | None
    strength: float | None
    position_skew: float | None
    top5_volume_share: float | None
    relation_to_accumulated: MemberRankRelation
    relation_to_caution: MemberRankRelation
    unavailable_reason: str | None
    raw_strength: Decimal | None = None

    @classmethod
    def unavailable(
        cls,
        reason: str,
        *,
        member_trade_date: date | None = None,
    ) -> MemberRankObservation:
        return cls(
            status="unavailable",
            member_trade_date=member_trade_date,
            direction=None,
            change_bias=None,
            strength=None,
            position_skew=None,
            top5_volume_share=None,
            relation_to_accumulated="unavailable",
            relation_to_caution="unavailable",
            unavailable_reason=reason,
            raw_strength=None,
        )


@dataclass(frozen=True, slots=True)
class MainForceMirrorV2Point:
    bar_end: datetime
    trading_day: date
    physical_contract: str | None
    pressure_ready: bool
    pressure_state: MainForceMirrorV2State | None
    instant_pressure: float | None
    accumulated_ready: bool
    accumulated_pressure: float | None
    caution_ready: bool
    caution: MainForceMirrorV2Caution | None
    caution_conflict: bool
    long_caution_score: float | None
    short_caution_score: float | None
    caution_reason_codes: tuple[str, ...]
    member: MemberRankObservation | None
    unavailable_reason: str | None
    price_impulse: float | None
    clv: float | None
    volume_ratio: float | None
    delta_oi: float | None
    oi_impulse: float | None
    range_position: float | None


@dataclass(frozen=True, slots=True)
class MainForceMirrorV2Result:
    indicator_code: Literal["main_force_mirror_v2"]
    indicator_version: Literal["futures-member-research-v2"]
    formal_policy_id: Literal["main_force_mirror_observation_v2"]
    parameters_hash: str
    points: tuple[MainForceMirrorV2Point, ...]


@dataclass(frozen=True, slots=True)
class MainForceMirrorV2CautionComponents:
    long_upper_extreme: bool
    long_short_cover_dominated: bool
    long_open_pressure_divergence: bool
    long_high_volume_exhaustion: bool
    short_lower_extreme: bool
    short_long_liquidation_dominated: bool
    short_open_pressure_divergence: bool
    short_low_price_absorption: bool


@dataclass(frozen=True, slots=True)
class MainForceMirrorV2LatchSnapshot:
    long_armed: bool
    short_armed: bool
    long_low_score_streak: int
    short_low_score_streak: int
    long_build_streak: int
    short_build_streak: int


@dataclass(frozen=True, slots=True)
class MainForceMirrorV2AuditTraceItem:
    bar_end: datetime
    trading_day: date
    physical_contract: str | None
    atr14: float | None
    volume_mean20: float | None
    range_high20: float | None
    range_low20: float | None
    oi_baseline20: float | None
    price_impulse: float | None
    clv: float | None
    direction: float | None
    volume_ratio: float | None
    delta_oi: float | None
    oi_impulse: float | None
    range_position: float | None
    long_open_pressure: float | None
    short_open_pressure: float | None
    prior_long_open_pressure_max: float | None
    prior_short_open_pressure_max: float | None
    instant_pressure: float | None
    accumulated_pressure: float | None
    long_score: float | None
    short_score: float | None
    components: MainForceMirrorV2CautionComponents | None
    long_candidate: bool | None
    short_candidate: bool | None
    conflict: bool
    latch_before: MainForceMirrorV2LatchSnapshot
    latch_after: MainForceMirrorV2LatchSnapshot
    trigger: MainForceMirrorV2Caution | None
    long_disarmed_suppressed: bool
    short_disarmed_suppressed: bool
    rearm_reasons: tuple[MainForceMirrorV2RearmReason, ...]
    reset_boundary: MainForceMirrorV2ResetBoundary | None
    unavailable_reason: str | None
    prior_high_max: float | None = None
    prior_low_min: float | None = None
    upper_wick_ratio: float | None = None
    lower_wick_ratio: float | None = None


@dataclass(frozen=True, slots=True)
class MainForceMirrorV2AuditResult:
    result: MainForceMirrorV2Result
    trace: tuple[MainForceMirrorV2AuditTraceItem, ...]


@dataclass(frozen=True, slots=True)
class _CautionEvidence:
    long_score: float
    short_score: float
    reason_codes: tuple[str, ...]
    components: MainForceMirrorV2CautionComponents
    prior_high_max: float
    prior_low_min: float
    upper_wick_ratio: float
    lower_wick_ratio: float


@dataclass(frozen=True, slots=True)
class _LatchState:
    long_armed: bool = True
    short_armed: bool = True
    long_low_score_streak: int = 0
    short_low_score_streak: int = 0
    long_build_streak: int = 0
    short_build_streak: int = 0


@dataclass(frozen=True, slots=True)
class _LatchStep:
    state: _LatchState
    caution: MainForceMirrorV2Caution | None
    conflict: bool
    long_candidate: bool
    short_candidate: bool
    long_disarmed_suppressed: bool
    short_disarmed_suppressed: bool
    rearm_reasons: tuple[MainForceMirrorV2RearmReason, ...]


def round_half_away_from_zero_binary64(value: float, digits: int) -> float:
    """Round public binary64 values and normalize both signed zeros."""

    if not np.isfinite(value):
        return value
    if isinstance(digits, bool) or not isinstance(digits, int) or digits < 0:
        raise ValueError("digits must be a non-negative integer")
    scale = float(10**digits)
    if value == 0.0:
        return 0.0
    magnitude = np.floor(abs(value) * scale + 0.5) / scale
    rounded = float(np.copysign(magnitude, value))
    return 0.0 if rounded == 0.0 else rounded


def compute_member_rank_observation(
    current: MemberRankDailyInput,
    prior_change_biases: Sequence[Decimal],
    *,
    accumulated_pressure: float | None,
    caution: MainForceMirrorV2Caution | None,
) -> MemberRankObservation:
    """Derive causal T-1 member context without affecting the pressure kernel."""

    if not current.is_valid():
        return MemberRankObservation.unavailable(
            _MEMBER_INPUT_INVALID,
            member_trade_date=current.member_trade_date,
        )

    prior_values = tuple(prior_change_biases[-60:])
    if len(prior_values) < 20 or not all(
        value.is_finite() for value in prior_values
    ):
        return MemberRankObservation.unavailable(
            _MEMBER_WARMUP,
            member_trade_date=current.member_trade_date,
        )
    baseline_values = tuple(sorted(abs(value) for value in prior_values))
    midpoint = len(baseline_values) // 2
    baseline = (
        baseline_values[midpoint]
        if len(baseline_values) % 2
        else (baseline_values[midpoint - 1] + baseline_values[midpoint]) / Decimal(2)
    )
    if baseline <= 0:
        return MemberRankObservation.unavailable(
            _MEMBER_WARMUP,
            member_trade_date=current.member_trade_date,
        )

    change_bias = current.change_bias
    strength = abs(change_bias) / baseline
    direction: MemberRankDirection = (
        "neutral"
        if strength < Decimal("0.5")
        else "long"
        if change_bias > 0
        else "short"
    )
    return MemberRankObservation(
        status="ready",
        member_trade_date=current.member_trade_date,
        direction=direction,
        change_bias=_round_member_value(change_bias),
        strength=_round_member_value(strength),
        position_skew=_round_member_value(current.position_skew),
        top5_volume_share=_round_member_value(current.top5_volume_share),
        relation_to_accumulated=_relation_to_accumulated(
            direction,
            change_bias,
            accumulated_pressure,
        ),
        relation_to_caution=_relation_to_caution(direction, change_bias, strength, caution),
        unavailable_reason=None,
        raw_strength=strength,
    )


def _round_member_value(value: Decimal) -> float:
    return round_half_away_from_zero_binary64(
        float(value),
        int(DEFAULT_PARAMETERS["round_digits"]),
    )


def _relation_to_accumulated(
    direction: MemberRankDirection,
    change_bias: Decimal,
    accumulated_pressure: float | None,
) -> MemberRankRelation:
    if (
        direction == "neutral"
        or accumulated_pressure is None
        or not np.isfinite(accumulated_pressure)
        or accumulated_pressure == 0.0
    ):
        return "neutral"
    return (
        "aligned"
        if (change_bias > 0) == (accumulated_pressure > 0)
        else "divergent"
    )


def _relation_to_caution(
    direction: MemberRankDirection,
    change_bias: Decimal,
    strength: Decimal,
    caution: MainForceMirrorV2Caution | None,
) -> MemberRankRelation:
    if direction == "neutral" or caution is None:
        return "neutral"
    crowded_long = caution == "long_chase_caution"
    if (change_bias > 0) != crowded_long:
        return "divergent"
    return "strong_aligned" if strength >= Decimal("2.0") else "aligned"


def is_main_force_mirror_v2_candidate(score: float) -> bool:
    """Apply the threshold to an unrounded caution score."""

    return score >= float(DEFAULT_PARAMETERS["caution_threshold"])


def _classify_state(
    direction: float,
    oi_impulse: float,
) -> MainForceMirrorV2State:
    if (
        abs(direction) < float(DEFAULT_PARAMETERS["direction_deadband"])
        or abs(oi_impulse) < float(DEFAULT_PARAMETERS["oi_deadband"])
    ):
        return "turnover"
    if direction >= float(DEFAULT_PARAMETERS["direction_deadband"]):
        return (
            "long_build"
            if oi_impulse >= float(DEFAULT_PARAMETERS["oi_deadband"])
            else "short_cover"
        )
    return (
        "short_build"
        if oi_impulse >= float(DEFAULT_PARAMETERS["oi_deadband"])
        else "long_liquidation"
    )


def _signed_pressure(
    state: MainForceMirrorV2State,
    strength: float,
    direction: float,
) -> float:
    if state in ("long_build", "short_cover"):
        return strength
    if state in ("short_build", "long_liquidation"):
        return -strength
    if direction == 0.0:
        return 0.0
    return float(np.copysign(min(strength, _TURNOVER_DISPLAY_CAP), direction))


def compute_main_force_mirror_v2(
    bar_end: Sequence[Any],
    trading_day: Sequence[Any],
    physical_contract: Sequence[str | None],
    open_: Sequence[float],
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    volume: Sequence[float],
    open_interest: Sequence[float | None],
    member_inputs: Sequence[MemberRankObservation | None] | None = None,
) -> MainForceMirrorV2Result:
    """Compute aligned historical-only pressure points by calculation block."""

    return _compute_main_force_mirror_v2(
        bar_end=bar_end,
        trading_day=trading_day,
        physical_contract=physical_contract,
        open_=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        open_interest=open_interest,
        member_inputs=member_inputs,
        include_audit=False,
    ).result


def compute_main_force_mirror_v2_with_audit(
    bar_end: Sequence[Any],
    trading_day: Sequence[Any],
    physical_contract: Sequence[str | None],
    open_: Sequence[float],
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    volume: Sequence[float],
    open_interest: Sequence[float | None],
    member_inputs: Sequence[MemberRankObservation | None] | None = None,
) -> MainForceMirrorV2AuditResult:
    """Compute the unchanged V2 result plus research-only calculation trace."""

    return _compute_main_force_mirror_v2(
        bar_end=bar_end,
        trading_day=trading_day,
        physical_contract=physical_contract,
        open_=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        open_interest=open_interest,
        member_inputs=member_inputs,
        include_audit=True,
    )


def _compute_main_force_mirror_v2(
    *,
    bar_end: Sequence[Any],
    trading_day: Sequence[Any],
    physical_contract: Sequence[str | None],
    open_: Sequence[float],
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    volume: Sequence[float],
    open_interest: Sequence[float | None],
    member_inputs: Sequence[MemberRankObservation | None] | None,
    include_audit: bool,
) -> MainForceMirrorV2AuditResult:

    raw_bar_end = _object_array(bar_end, name="bar_end")
    raw_trading_day = _object_array(trading_day, name="trading_day")
    raw_contracts = _object_array(physical_contract, name="physical_contract")
    raw_open = _object_array(open_, name="open")
    raw_high = _object_array(high, name="high")
    raw_low = _object_array(low, name="low")
    raw_close = _object_array(close, name="close")
    raw_volume = _object_array(volume, name="volume")
    raw_open_interest = _object_array(open_interest, name="open_interest")
    arrays: dict[str, Sized] = {
        "bar_end": raw_bar_end,
        "trading_day": raw_trading_day,
        "physical_contract": raw_contracts,
        "open": raw_open,
        "high": raw_high,
        "low": raw_low,
        "close": raw_close,
        "volume": raw_volume,
        "open_interest": raw_open_interest,
    }
    raw_members: np.ndarray | None = None
    if member_inputs is not None:
        raw_members = _object_array(member_inputs, name="member_inputs")
        arrays["member_inputs"] = raw_members
    _require_same_length(**arrays)

    count = len(raw_bar_end)
    normalized_bar_end: list[datetime] = []
    normalized_trading_day: list[date] = []
    normalized_contracts: list[str | None] = []
    members: list[MemberRankObservation | None] = []
    open_values = np.full(count, np.nan, dtype=float)
    high_values = np.full(count, np.nan, dtype=float)
    low_values = np.full(count, np.nan, dtype=float)
    close_values = np.full(count, np.nan, dtype=float)
    volume_values = np.full(count, np.nan, dtype=float)
    oi_values = np.full(count, np.nan, dtype=float)
    valid = np.zeros(count, dtype=bool)
    reasons: list[str | None] = [None] * count
    max_seen_time: datetime | None = None

    for index in range(count):
        parsed_time = _parse_datetime(raw_bar_end[index])
        parsed_day = _parse_trading_day(raw_trading_day[index])
        contract = _normalize_contract(raw_contracts[index])
        normalized_bar_end.append(parsed_time or datetime.min.replace(tzinfo=UTC))
        normalized_trading_day.append(parsed_day or date.min)
        normalized_contracts.append(contract)

        member = None if raw_members is None else raw_members[index]
        if member is not None and not isinstance(member, MemberRankObservation):
            raise ValueError("member_inputs must contain MemberRankObservation or None")
        members.append(member)

        timestamp_invalid = parsed_time is None
        if parsed_time is not None:
            timestamp_invalid = max_seen_time is not None and parsed_time <= max_seen_time
            if max_seen_time is None or parsed_time > max_seen_time:
                max_seen_time = parsed_time

        values = (
            _finite_number(raw_open[index]),
            _finite_number(raw_high[index]),
            _finite_number(raw_low[index]),
            _finite_number(raw_close[index]),
            _finite_number(raw_volume[index]),
            _finite_number(raw_open_interest[index]),
        )
        open_value, high_value, low_value, close_value, volume_value, oi_value = values
        for target, value in zip(
            (
                open_values,
                high_values,
                low_values,
                close_values,
                volume_values,
                oi_values,
            ),
            values,
            strict=True,
        ):
            if value is not None:
                target[index] = value

        reason: str | None = None
        if contract is None:
            reason = _PHYSICAL_CONTRACT_MISSING
        elif parsed_day is None:
            reason = _MARKET_IDENTITY_CONFLICT
        elif timestamp_invalid:
            reason = _TIMESTAMP_INVALID
        elif oi_value is None or oi_value < 0:
            reason = _OPEN_INTEREST_UNAVAILABLE
        elif not _valid_ohlcv(
            open_value, high_value, low_value, close_value, volume_value
        ):
            reason = _INPUT_INVALID
        reasons[index] = reason
        valid[index] = reason is None

    points = [
        MainForceMirrorV2Point(
            bar_end=normalized_bar_end[index],
            trading_day=normalized_trading_day[index],
            physical_contract=normalized_contracts[index],
            pressure_ready=False,
            pressure_state=None,
            instant_pressure=None,
            accumulated_ready=False,
            accumulated_pressure=None,
            caution_ready=False,
            caution=None,
            caution_conflict=False,
            long_caution_score=None,
            short_caution_score=None,
            caution_reason_codes=(),
            member=members[index],
            unavailable_reason=reasons[index],
            price_impulse=None,
            clv=None,
            volume_ratio=None,
            delta_oi=None,
            oi_impulse=None,
            range_position=None,
        )
        for index in range(count)
    ]
    default_latch = _latch_snapshot(_LatchState())
    trace = (
        [
            MainForceMirrorV2AuditTraceItem(
                bar_end=normalized_bar_end[index],
                trading_day=normalized_trading_day[index],
                physical_contract=normalized_contracts[index],
                atr14=None,
                volume_mean20=None,
                range_high20=None,
                range_low20=None,
                oi_baseline20=None,
                price_impulse=None,
                clv=None,
                direction=None,
                volume_ratio=None,
                delta_oi=None,
                oi_impulse=None,
                range_position=None,
                long_open_pressure=None,
                short_open_pressure=None,
                prior_long_open_pressure_max=None,
                prior_short_open_pressure_max=None,
                instant_pressure=None,
                accumulated_pressure=None,
                long_score=None,
                short_score=None,
                components=None,
                long_candidate=None,
                short_candidate=None,
                conflict=False,
                latch_before=default_latch,
                latch_after=default_latch,
                trigger=None,
                long_disarmed_suppressed=False,
                short_disarmed_suppressed=False,
                rearm_reasons=(),
                reset_boundary=None,
                unavailable_reason=reasons[index],
            )
            for index in range(count)
        ]
        if include_audit
        else None
    )
    _apply_blocks(
        valid=valid,
        contracts=normalized_contracts,
        open_=open_values,
        high=high_values,
        low=low_values,
        close=close_values,
        volume=volume_values,
        open_interest=oi_values,
        points=points,
        trace=trace,
    )

    parameters_payload = json.dumps(
        dict(DEFAULT_PARAMETERS),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    parameters_hash = hashlib.sha256(parameters_payload.encode("utf-8")).hexdigest()[
        :16
    ]
    result = MainForceMirrorV2Result(
        indicator_code=INDICATOR_CODE,
        indicator_version=INDICATOR_VERSION,
        formal_policy_id=FORMAL_POLICY_ID,
        parameters_hash=parameters_hash,
        points=tuple(points),
    )
    if trace is not None:
        trace = [
            replace(item, unavailable_reason=points[index].unavailable_reason)
            for index, item in enumerate(trace)
        ]
    return MainForceMirrorV2AuditResult(
        result=result,
        trace=() if trace is None else tuple(trace),
    )


def _apply_blocks(
    *,
    valid: np.ndarray,
    contracts: Sequence[str | None],
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
    open_interest: np.ndarray,
    points: list[MainForceMirrorV2Point],
    trace: list[MainForceMirrorV2AuditTraceItem] | None,
) -> None:
    index = 0
    previous_latch = _LatchState()
    while index < len(valid):
        if not valid[index]:
            if trace is not None:
                trace[index] = replace(
                    trace[index],
                    latch_before=_latch_snapshot(previous_latch),
                    latch_after=_latch_snapshot(_LatchState()),
                    reset_boundary="invalid_input",
                )
            previous_latch = _LatchState()
            index += 1
            continue
        start = index
        contract = contracts[index]
        while (
            index + 1 < len(valid)
            and valid[index + 1]
            and contracts[index + 1] == contract
        ):
            index += 1
        reset_boundary: MainForceMirrorV2ResetBoundary | None = None
        latch_before_reset = previous_latch
        if start == 0:
            reset_boundary = "series_start"
        elif valid[start - 1] and contracts[start - 1] != contract:
            reset_boundary = "physical_contract_change"
        previous_latch = _apply_block(
            start=start,
            end=index + 1,
            open_=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
            open_interest=open_interest,
            points=points,
            trace=trace,
            latch_before_reset=latch_before_reset,
            reset_boundary=reset_boundary,
        )
        index += 1


def _apply_block(
    *,
    start: int,
    end: int,
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
    open_interest: np.ndarray,
    points: list[MainForceMirrorV2Point],
    trace: list[MainForceMirrorV2AuditTraceItem] | None,
    latch_before_reset: _LatchState,
    reset_boundary: MainForceMirrorV2ResetBoundary | None,
) -> _LatchState:
    block_open = open_[start:end]
    block_high = high[start:end]
    block_low = low[start:end]
    block_close = close[start:end]
    block_volume = volume[start:end]
    block_oi = open_interest[start:end]
    atr = _wilder_atr(block_high, block_low, block_close, period=14)
    volume_mean = _rolling_mean(block_volume, window=20)
    range_high = _rolling_extreme(block_high, window=20, maximum=True)
    range_low = _rolling_extreme(block_low, window=20, maximum=False)
    oi_delta = np.diff(block_oi)
    oi_baseline = _ema_sma_seed(np.abs(oi_delta), period=20)
    raw_long_pressures = np.full(end - start, np.nan, dtype=float)
    raw_short_pressures = np.full(end - start, np.nan, dtype=float)
    pressure_ready = np.zeros(end - start, dtype=bool)
    accumulated_seed: list[float] = []
    accumulated_previous: float | None = None
    accumulated_alpha = 2.0 / 6.0
    latch = _LatchState()

    for block_index in range(end - start):
        output_index = start + block_index
        point = points[output_index]
        if trace is not None:
            latch_before = latch_before_reset if block_index == 0 else latch
            trace[output_index] = replace(
                trace[output_index],
                latch_before=_latch_snapshot(latch_before),
                latch_after=_latch_snapshot(latch),
                reset_boundary=(reset_boundary if block_index == 0 else None),
            )
        if block_index < 20:
            points[output_index] = replace(point, unavailable_reason=_WARMUP)
            continue
        if not np.isfinite(atr[block_index]) or atr[block_index] <= 0:
            points[output_index] = replace(point, unavailable_reason=_ATR_INVALID)
            continue
        if not np.isfinite(volume_mean[block_index]) or volume_mean[block_index] <= 0:
            points[output_index] = replace(
                point, unavailable_reason=_VOLUME_BASELINE_INVALID
            )
            continue
        if (
            not np.isfinite(range_high[block_index])
            or not np.isfinite(range_low[block_index])
            or range_high[block_index] == range_low[block_index]
        ):
            points[output_index] = replace(point, unavailable_reason=_RANGE_INVALID)
            continue
        baseline_index = block_index - 1
        if baseline_index < 0 or not np.isfinite(oi_baseline[baseline_index]):
            points[output_index] = replace(point, unavailable_reason=_WARMUP)
            continue

        raw_price_impulse = float(
            np.clip(
                (block_close[block_index] - block_close[block_index - 1])
                / atr[block_index],
                -_PRICE_IMPULSE_CLIP,
                _PRICE_IMPULSE_CLIP,
            )
        )
        raw_clv = (
            float(
                np.clip(
                    (
                        2.0 * block_close[block_index]
                        - block_high[block_index]
                        - block_low[block_index]
                    )
                    / (block_high[block_index] - block_low[block_index]),
                    -1.0,
                    1.0,
                )
            )
            if block_high[block_index] > block_low[block_index]
            else 0.0
        )
        raw_direction = float(
            float(DEFAULT_PARAMETERS["direction_price_weight"]) * raw_price_impulse
            + float(DEFAULT_PARAMETERS["direction_clv_weight"]) * raw_clv
        )
        raw_volume_ratio = float(
            np.clip(
                block_volume[block_index] / volume_mean[block_index],
                0.0,
                _VOLUME_RATIO_CLIP,
            )
        )
        participation = float(np.sqrt(raw_volume_ratio))
        raw_delta_oi = float(block_oi[block_index] - block_oi[block_index - 1])
        oi_denominator = float(oi_baseline[baseline_index])
        raw_oi_impulse = (
            0.0
            if oi_denominator == 0.0
            else float(
                np.clip(
                    raw_delta_oi / oi_denominator,
                    -_OI_IMPULSE_CLIP,
                    _OI_IMPULSE_CLIP,
                )
            )
        )
        raw_range_position = float(
            np.clip(
                (block_close[block_index] - range_low[block_index])
                / (range_high[block_index] - range_low[block_index]),
                0.0,
                1.0,
            )
        )
        raw_long_pressure = (
            max(raw_direction, 0.0) * max(raw_oi_impulse, 0.0) * participation
        )
        raw_short_pressure = (
            max(-raw_direction, 0.0) * max(raw_oi_impulse, 0.0) * participation
        )
        raw_strength = float(
            np.clip(
                abs(raw_direction)
                * abs(raw_oi_impulse)
                * participation
                * _STRENGTH_SCALE,
                0.0,
                100.0,
            )
        )
        raw_state = _classify_state(raw_direction, raw_oi_impulse)
        raw_instant = _signed_pressure(raw_state, raw_strength, raw_direction)
        raw_long_pressures[block_index] = raw_long_pressure
        raw_short_pressures[block_index] = raw_short_pressure
        pressure_ready[block_index] = True

        accumulated_seed.append(raw_instant)
        raw_accumulated: float | None = None
        if accumulated_previous is None:
            if len(accumulated_seed) >= 5:
                accumulated_previous = float(np.mean(accumulated_seed[-5:]))
                raw_accumulated = accumulated_previous
        else:
            accumulated_previous = (
                accumulated_alpha * raw_instant
                + (1.0 - accumulated_alpha) * accumulated_previous
            )
            raw_accumulated = accumulated_previous

        if trace is not None:
            trace[output_index] = replace(
                trace[output_index],
                atr14=float(atr[block_index]),
                volume_mean20=float(volume_mean[block_index]),
                range_high20=float(range_high[block_index]),
                range_low20=float(range_low[block_index]),
                oi_baseline20=oi_denominator,
                price_impulse=raw_price_impulse,
                clv=raw_clv,
                direction=raw_direction,
                volume_ratio=raw_volume_ratio,
                delta_oi=raw_delta_oi,
                oi_impulse=raw_oi_impulse,
                range_position=raw_range_position,
                long_open_pressure=raw_long_pressure,
                short_open_pressure=raw_short_pressure,
                instant_pressure=raw_instant,
                accumulated_pressure=raw_accumulated,
            )

        digits = int(DEFAULT_PARAMETERS["round_digits"])
        point = replace(
            point,
            pressure_ready=True,
            pressure_state=raw_state,
            instant_pressure=round_half_away_from_zero_binary64(raw_instant, digits),
            accumulated_ready=raw_accumulated is not None,
            accumulated_pressure=(
                None
                if raw_accumulated is None
                else round_half_away_from_zero_binary64(raw_accumulated, digits)
            ),
            unavailable_reason=_CAUTION_WARMUP,
            price_impulse=round_half_away_from_zero_binary64(
                raw_price_impulse, digits
            ),
            clv=round_half_away_from_zero_binary64(raw_clv, digits),
            volume_ratio=round_half_away_from_zero_binary64(
                raw_volume_ratio, digits
            ),
            delta_oi=round_half_away_from_zero_binary64(raw_delta_oi, digits),
            oi_impulse=round_half_away_from_zero_binary64(
                raw_oi_impulse, digits
            ),
            range_position=round_half_away_from_zero_binary64(
                raw_range_position, digits
            ),
        )

        if block_index >= 30 and bool(
            np.all(pressure_ready[block_index - 10 : block_index])
        ):
            prior_slice = slice(block_index - 10, block_index)
            evidence = _evaluate_caution(
                state=raw_state,
                oi_impulse=raw_oi_impulse,
                range_position=raw_range_position,
                high=float(block_high[block_index]),
                low=float(block_low[block_index]),
                open_=float(block_open[block_index]),
                close=float(block_close[block_index]),
                volume_ratio=raw_volume_ratio,
                clv=raw_clv,
                long_open_pressure=raw_long_pressure,
                short_open_pressure=raw_short_pressure,
                prior_highs=block_high[prior_slice],
                prior_lows=block_low[prior_slice],
                prior_long_open_pressures=raw_long_pressures[prior_slice],
                prior_short_open_pressures=raw_short_pressures[prior_slice],
            )
            latch_before_step = latch
            step = _step_latch(
                latch,
                long_score=evidence.long_score,
                short_score=evidence.short_score,
                position_state=raw_state,
                range_position=raw_range_position,
            )
            latch = step.state
            caution = step.caution
            conflict = step.conflict
            point = replace(
                point,
                caution_ready=True,
                caution=caution,
                caution_conflict=conflict,
                long_caution_score=round_half_away_from_zero_binary64(
                    evidence.long_score, digits
                ),
                short_caution_score=round_half_away_from_zero_binary64(
                    evidence.short_score, digits
                ),
                caution_reason_codes=evidence.reason_codes,
                unavailable_reason=(
                    _CAUTION_DIRECTION_CONFLICT if conflict else None
                ),
            )
            if trace is not None:
                trace[output_index] = replace(
                    trace[output_index],
                    prior_long_open_pressure_max=float(
                        np.max(raw_long_pressures[prior_slice])
                    ),
                    prior_short_open_pressure_max=float(
                        np.max(raw_short_pressures[prior_slice])
                    ),
                    prior_high_max=evidence.prior_high_max,
                    prior_low_min=evidence.prior_low_min,
                    upper_wick_ratio=evidence.upper_wick_ratio,
                    lower_wick_ratio=evidence.lower_wick_ratio,
                    long_score=evidence.long_score,
                    short_score=evidence.short_score,
                    components=evidence.components,
                    long_candidate=step.long_candidate,
                    short_candidate=step.short_candidate,
                    conflict=step.conflict,
                    latch_before=_latch_snapshot(latch_before_step),
                    latch_after=_latch_snapshot(latch),
                    trigger=step.caution,
                    long_disarmed_suppressed=step.long_disarmed_suppressed,
                    short_disarmed_suppressed=step.short_disarmed_suppressed,
                    rearm_reasons=step.rearm_reasons,
                )
        points[output_index] = point
    return latch


def _evaluate_caution(
    *,
    state: MainForceMirrorV2State,
    oi_impulse: float,
    range_position: float,
    high: float,
    low: float,
    open_: float,
    close: float,
    volume_ratio: float,
    clv: float,
    long_open_pressure: float,
    short_open_pressure: float,
    prior_highs: Sequence[float] | np.ndarray,
    prior_lows: Sequence[float] | np.ndarray,
    prior_long_open_pressures: Sequence[float] | np.ndarray,
    prior_short_open_pressures: Sequence[float] | np.ndarray,
) -> _CautionEvidence:
    window = int(DEFAULT_PARAMETERS["pressure_divergence_window"])
    if any(
        len(values) != window
        for values in (
            prior_highs,
            prior_lows,
            prior_long_open_pressures,
            prior_short_open_pressures,
        )
    ):
        raise ValueError(f"prior caution evidence must contain exactly {window} points")

    long_score = 0.0
    short_score = 0.0
    reasons: list[str] = []
    prior_high = max(prior_highs)
    prior_low = min(prior_lows)
    prior_long_pressure = max(prior_long_open_pressures)
    prior_short_pressure = max(prior_short_open_pressures)
    price_range = high - low
    upper_wick_ratio = (
        0.0 if price_range == 0.0 else (high - max(open_, close)) / price_range
    )
    lower_wick_ratio = (
        0.0 if price_range == 0.0 else (min(open_, close) - low) / price_range
    )

    long_upper_extreme = bool(range_position >= _UPPER_LOCATION_THRESHOLD)
    long_short_cover_dominated = bool(
        state == "short_cover"
        and oi_impulse <= -_LIQUIDATION_DOMINATED_OI_THRESHOLD
    )
    long_open_pressure_divergence = bool(
        high > prior_high
        and prior_long_pressure > 0.0
        and long_open_pressure <= _PRESSURE_CONFIRMATION_RATIO * prior_long_pressure
    )
    long_high_volume_exhaustion = bool(
        volume_ratio >= _HIGH_VOLUME_THRESHOLD
        and (
            clv <= _CLV_REJECTION_THRESHOLD
            or upper_wick_ratio >= _WICK_REJECTION_THRESHOLD
        )
    )
    short_lower_extreme = bool(range_position <= _LOWER_LOCATION_THRESHOLD)
    short_long_liquidation_dominated = bool(
        state == "long_liquidation"
        and oi_impulse <= -_LIQUIDATION_DOMINATED_OI_THRESHOLD
    )
    short_open_pressure_divergence = bool(
        low < prior_low
        and prior_short_pressure > 0.0
        and short_open_pressure <= _PRESSURE_CONFIRMATION_RATIO * prior_short_pressure
    )
    short_low_price_absorption = bool(
        volume_ratio >= _HIGH_VOLUME_THRESHOLD
        and (
            clv >= -_CLV_REJECTION_THRESHOLD
            or lower_wick_ratio >= _WICK_REJECTION_THRESHOLD
        )
    )

    if long_upper_extreme:
        long_score += 30.0
        reasons.append("LONG_UPPER_EXTREME")
    if long_short_cover_dominated:
        long_score += 30.0
        reasons.append("LONG_SHORT_COVER_DOMINATED")
    if long_open_pressure_divergence:
        long_score += 25.0
        reasons.append("LONG_OPEN_PRESSURE_DIVERGENCE")
    if long_high_volume_exhaustion:
        long_score += 15.0
        reasons.append("LONG_HIGH_VOLUME_EXHAUSTION")

    if short_lower_extreme:
        short_score += 30.0
        reasons.append("SHORT_LOWER_EXTREME")
    if short_long_liquidation_dominated:
        short_score += 30.0
        reasons.append("SHORT_LONG_LIQUIDATION_DOMINATED")
    if short_open_pressure_divergence:
        short_score += 25.0
        reasons.append("SHORT_OPEN_PRESSURE_DIVERGENCE")
    if short_low_price_absorption:
        short_score += 15.0
        reasons.append("SHORT_LOW_PRICE_ABSORPTION")
    return _CautionEvidence(
        long_score,
        short_score,
        tuple(reasons),
        MainForceMirrorV2CautionComponents(
            long_upper_extreme=long_upper_extreme,
            long_short_cover_dominated=long_short_cover_dominated,
            long_open_pressure_divergence=long_open_pressure_divergence,
            long_high_volume_exhaustion=long_high_volume_exhaustion,
            short_lower_extreme=short_lower_extreme,
            short_long_liquidation_dominated=short_long_liquidation_dominated,
            short_open_pressure_divergence=short_open_pressure_divergence,
            short_low_price_absorption=short_low_price_absorption,
        ),
        float(prior_high),
        float(prior_low),
        float(upper_wick_ratio),
        float(lower_wick_ratio),
    )


def _step_latch(
    state: _LatchState,
    *,
    long_score: float,
    short_score: float,
    position_state: MainForceMirrorV2State,
    range_position: float,
) -> _LatchStep:
    long_candidate = is_main_force_mirror_v2_candidate(long_score)
    short_candidate = is_main_force_mirror_v2_candidate(short_score)
    if long_candidate and short_candidate:
        return _LatchStep(
            state=state,
            caution=None,
            conflict=True,
            long_candidate=True,
            short_candidate=True,
            long_disarmed_suppressed=False,
            short_disarmed_suppressed=False,
            rearm_reasons=(),
        )

    long_triggered = state.long_armed and long_candidate
    short_triggered = state.short_armed and short_candidate
    long_disarmed_suppressed = not state.long_armed and long_candidate
    short_disarmed_suppressed = not state.short_armed and short_candidate
    caution: MainForceMirrorV2Caution | None = None
    rearm_reasons: list[MainForceMirrorV2RearmReason] = []
    if long_triggered:
        caution = "long_chase_caution"
    elif short_triggered:
        caution = "short_chase_caution"

    long_armed = state.long_armed
    long_low = state.long_low_score_streak
    long_build = state.long_build_streak
    if long_triggered:
        long_armed, long_low, long_build = False, 0, 0
    elif long_armed:
        long_low, long_build = 0, 0
    else:
        long_low = (
            long_low + 1
            if long_score < float(DEFAULT_PARAMETERS["rearm_score_threshold"])
            else 0
        )
        long_build = long_build + 1 if position_state == "long_build" else 0
        long_low_ready = long_low >= int(
            DEFAULT_PARAMETERS["rearm_low_score_bars"]
        )
        long_range_ready = range_position < _LONG_REARM_RANGE_THRESHOLD
        long_build_ready = long_build >= int(
            DEFAULT_PARAMETERS["rearm_build_bars"]
        )
        if long_low_ready and (long_range_ready or long_build_ready):
            if long_range_ready:
                rearm_reasons.append("long_range")
            if long_build_ready:
                rearm_reasons.append("long_build")
            long_armed, long_low, long_build = True, 0, 0

    short_armed = state.short_armed
    short_low = state.short_low_score_streak
    short_build = state.short_build_streak
    if short_triggered:
        short_armed, short_low, short_build = False, 0, 0
    elif short_armed:
        short_low, short_build = 0, 0
    else:
        short_low = (
            short_low + 1
            if short_score < float(DEFAULT_PARAMETERS["rearm_score_threshold"])
            else 0
        )
        short_build = short_build + 1 if position_state == "short_build" else 0
        short_low_ready = short_low >= int(
            DEFAULT_PARAMETERS["rearm_low_score_bars"]
        )
        short_range_ready = range_position > _SHORT_REARM_RANGE_THRESHOLD
        short_build_ready = short_build >= int(
            DEFAULT_PARAMETERS["rearm_build_bars"]
        )
        if short_low_ready and (short_range_ready or short_build_ready):
            if short_range_ready:
                rearm_reasons.append("short_range")
            if short_build_ready:
                rearm_reasons.append("short_build")
            short_armed, short_low, short_build = True, 0, 0

    return _LatchStep(
        state=_LatchState(
            long_armed=long_armed,
            short_armed=short_armed,
            long_low_score_streak=long_low,
            short_low_score_streak=short_low,
            long_build_streak=long_build,
            short_build_streak=short_build,
        ),
        caution=caution,
        conflict=False,
        long_candidate=long_candidate,
        short_candidate=short_candidate,
        long_disarmed_suppressed=long_disarmed_suppressed,
        short_disarmed_suppressed=short_disarmed_suppressed,
        rearm_reasons=tuple(rearm_reasons),
    )


def _latch_snapshot(state: _LatchState) -> MainForceMirrorV2LatchSnapshot:
    return MainForceMirrorV2LatchSnapshot(
        long_armed=state.long_armed,
        short_armed=state.short_armed,
        long_low_score_streak=state.long_low_score_streak,
        short_low_score_streak=state.short_low_score_streak,
        long_build_streak=state.long_build_streak,
        short_build_streak=state.short_build_streak,
    )


def _wilder_atr(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    *,
    period: int,
) -> np.ndarray:
    output = np.full(len(close), np.nan, dtype=float)
    previous_close: float | None = None
    previous_atr: float | None = None
    seed: list[float] = []
    for index, (high_value, low_value, close_value) in enumerate(
        zip(high, low, close, strict=True)
    ):
        true_range = float(high_value - low_value)
        if previous_close is not None:
            true_range = max(
                true_range,
                abs(float(high_value) - previous_close),
                abs(float(low_value) - previous_close),
            )
        previous_close = float(close_value)
        if previous_atr is None:
            seed.append(true_range)
            if len(seed) < period:
                continue
            previous_atr = float(np.mean(seed[-period:]))
        else:
            previous_atr = (
                previous_atr * float(period - 1) + true_range
            ) / float(period)
        output[index] = previous_atr
    return output


def _ema_sma_seed(values: np.ndarray, period: int) -> np.ndarray:
    output = np.full(len(values), np.nan, dtype=float)
    alpha = 2.0 / (period + 1.0)
    previous: float | None = None
    seed: list[float] = []
    for index, value in enumerate(values):
        if not np.isfinite(value):
            previous = None
            seed = []
            continue
        if previous is None:
            seed.append(float(value))
            if len(seed) < period:
                continue
            previous = float(np.mean(seed[-period:]))
        else:
            previous = alpha * float(value) + (1.0 - alpha) * previous
        output[index] = previous
    return output


def _rolling_mean(values: np.ndarray, window: int) -> np.ndarray:
    output = np.full(len(values), np.nan, dtype=float)
    for index in range(window - 1, len(values)):
        segment = values[index - window + 1 : index + 1]
        if np.all(np.isfinite(segment)):
            output[index] = float(np.mean(segment))
    return output


def _rolling_extreme(
    values: np.ndarray,
    window: int,
    *,
    maximum: bool,
) -> np.ndarray:
    output = np.full(len(values), np.nan, dtype=float)
    reducer = np.max if maximum else np.min
    for index in range(window - 1, len(values)):
        segment = values[index - window + 1 : index + 1]
        if np.all(np.isfinite(segment)):
            output[index] = float(reducer(segment))
    return output


def _object_array(values: Sequence[Any], *, name: str) -> np.ndarray:
    try:
        array = np.asarray(values, dtype=object)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be one-dimensional") from exc
    if array.ndim != 1 or any(
        isinstance(value, (list, tuple, np.ndarray)) for value in array
    ):
        raise ValueError(f"{name} must be one-dimensional")
    return array


def _require_same_length(**arrays: Sized) -> None:
    lengths = {name: len(array) for name, array in arrays.items()}
    if len(set(lengths.values())) != 1:
        raise ValueError(f"input lengths must match: {lengths}")


def _normalize_contract(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().upper()
    return normalized or None


def _finite_number(value: object) -> float | None:
    if value is None or isinstance(value, (bool, np.bool_)):
        return None
    try:
        number = float(cast(str | bytes | SupportsFloat | SupportsIndex, value))
    except (TypeError, ValueError, OverflowError):
        return None
    return number if np.isfinite(number) else None


def _valid_ohlcv(
    open_value: float | None,
    high_value: float | None,
    low_value: float | None,
    close_value: float | None,
    volume_value: float | None,
) -> bool:
    if any(
        value is None
        for value in (open_value, high_value, low_value, close_value, volume_value)
    ):
        return False
    assert open_value is not None
    assert high_value is not None
    assert low_value is not None
    assert close_value is not None
    assert volume_value is not None
    return (
        high_value >= max(open_value, close_value)
        and low_value <= min(open_value, close_value)
        and high_value >= low_value
        and volume_value >= 0
    )


def _parse_datetime(value: object) -> datetime | None:
    if isinstance(value, np.datetime64):
        if np.isnat(value):
            return None
        microseconds = int(value.astype("datetime64[us]").astype(np.int64))
        return datetime.fromtimestamp(microseconds / 1_000_000, tz=UTC)
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _parse_trading_day(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None
