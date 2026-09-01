"""Frozen, dependency-free contracts for the SuBing Watch 15m kernel."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
import math
import re
from typing import Literal, Protocol

from .atr import initial_atr_state, step_atr
from .macd import initial_macd_state, step_macd
from .models import AtrState, MacdState
from .range_detector_lux import (
    RangeDetectorLuxState,
    initial_range_detector_lux_state,
    step_range_detector_lux,
)


SUBING_WATCH_FORMULA_VERSION = "subing_watch_15m_v1"
_SYMBOL = re.compile(r"[a-z]+\Z")
_CONTRACT = re.compile(r"([A-Z]+)[0-9]{3,4}\Z")
_OUTCOMES = frozenset(
    {"evaluated_no_signal", "evaluated_candidate", "source_unavailable"}
)
_OBSERVATION_TYPES = frozenset({"buy", "sell"})
_RANGE_STATES = frozenset(
    {"range_unavailable", "no_active_range", "intact", "broken_up", "broken_down"}
)
_HIGHER_TIMEFRAME_ALIGNMENTS = frozenset(
    {"aligned", "opposed", "neutral", "unavailable"}
)
_SOURCE_FINGERPRINT = re.compile(r"[0-9a-f]{64}\Z")


class SubingWatchKernelError(ValueError):
    code = "SUBING_WATCH_KERNEL_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


class SubingWatchDuplicateConflictError(SubingWatchKernelError):
    code = "SUBING_WATCH_DUPLICATE_CONFLICT"


class SubingWatchHigherTimeframeFutureError(SubingWatchKernelError):
    code = "SUBING_WATCH_HIGHER_TIMEFRAME_FUTURE"


class SubingWatchPolicy(Protocol):
    policy_id: str
    formula_version: str
    series_kind: str
    frequency: str
    completed_bar_only: bool
    ma_type: str
    ma_period: int
    ma_source: str
    macd: tuple[int, int, int]
    ema_seed_policy: str
    histogram_scale: int
    atr_period: int
    atr_smoothing_policy: str
    ma_slope_points: int
    volume_previous_bars: int
    range_indicator_code: str
    higher_timeframe: str
    round_digits: int
    auto_order: bool


def _rfc3339(value: object) -> str:
    if not isinstance(value, str):
        raise SubingWatchKernelError()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise SubingWatchKernelError() from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SubingWatchKernelError()
    return parsed.astimezone(UTC).isoformat()


def _trading_day(value: object) -> str:
    if not isinstance(value, str):
        raise SubingWatchKernelError()
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise SubingWatchKernelError() from None


def _finite_float(value: object, *, optional: bool = False) -> float | None:
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SubingWatchKernelError()
    result = float(value)
    if not math.isfinite(result):
        raise SubingWatchKernelError()
    return result


def _optional_finite_float(value: object) -> float | None:
    return _finite_float(value, optional=True)


def _source_fingerprint(value: object) -> str:
    if not isinstance(value, str) or _SOURCE_FINGERPRINT.fullmatch(value) is None:
        raise SubingWatchKernelError()
    return value


@dataclass(frozen=True, slots=True)
class SubingWatchKernelIdentity:
    symbol: str
    contract: str
    segment_start_trading_day: str
    series_kind: Literal["actual_dominant"] = "actual_dominant"
    frequency: Literal["15m"] = "15m"

    def __post_init__(self) -> None:
        match = _CONTRACT.fullmatch(self.contract) if isinstance(self.contract, str) else None
        if (
            not isinstance(self.symbol, str)
            or _SYMBOL.fullmatch(self.symbol) is None
            or match is None
            or match.group(1).lower() != self.symbol
            or self.contract != self.contract.upper()
            or self.series_kind != "actual_dominant"
            or self.frequency != "15m"
        ):
            raise SubingWatchKernelError()
        object.__setattr__(self, "segment_start_trading_day", _trading_day(self.segment_start_trading_day))


@dataclass(frozen=True, slots=True)
class SubingWatchKernelBar:
    identity: SubingWatchKernelIdentity
    bar_end: str
    trading_day: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    source_fingerprint: str

    def __post_init__(self) -> None:
        if type(self.identity) is not SubingWatchKernelIdentity:
            raise SubingWatchKernelError()
        bar_end = _rfc3339(self.bar_end)
        trading_day = _trading_day(self.trading_day)
        open_value = _finite_float(self.open)
        high = _finite_float(self.high)
        low = _finite_float(self.low)
        close = _finite_float(self.close)
        volume = _finite_float(self.volume)
        assert open_value is not None and high is not None and low is not None
        assert close is not None and volume is not None
        if low > high or not low <= open_value <= high or not low <= close <= high or volume < 0:
            raise SubingWatchKernelError()
        _source_fingerprint(self.source_fingerprint)
        object.__setattr__(self, "bar_end", bar_end)
        object.__setattr__(self, "trading_day", trading_day)
        object.__setattr__(self, "open", open_value)
        object.__setattr__(self, "high", high)
        object.__setattr__(self, "low", low)
        object.__setattr__(self, "close", close)
        object.__setattr__(self, "volume", volume)


@dataclass(frozen=True, slots=True)
class SubingWatchKernelHigherTimeframe:
    bar_end: str
    close: float | None
    ma21: float | None
    ma21_slope_5_bps_per_bar: float | None
    ready: bool
    valid: bool
    identity: SubingWatchKernelIdentity | None = None

    def __post_init__(self) -> None:
        if (
            type(self.ready) is not bool
            or type(self.valid) is not bool
            or (
                self.identity is not None
                and type(self.identity) is not SubingWatchKernelIdentity
            )
        ):
            raise SubingWatchKernelError()
        object.__setattr__(self, "bar_end", _rfc3339(self.bar_end))
        for field in ("close", "ma21", "ma21_slope_5_bps_per_bar"):
            object.__setattr__(self, field, _optional_finite_float(getattr(self, field)))


@dataclass(frozen=True, slots=True)
class SubingWatchKernelContext:
    ma21_slope_5_bps_per_bar: float | None
    distance_to_ma21_atr14: float | None
    macd_zero_distance_atr14: float | None
    volume_ratio_20: float | None
    range_state: Literal[
        "range_unavailable", "no_active_range", "intact", "broken_up", "broken_down"
    ]
    higher_timeframe_alignment: Literal[
        "aligned", "opposed", "neutral", "unavailable"
    ]

    def __post_init__(self) -> None:
        if (
            self.range_state not in _RANGE_STATES
            or self.higher_timeframe_alignment not in _HIGHER_TIMEFRAME_ALIGNMENTS
        ):
            raise SubingWatchKernelError()
        for field in (
            "ma21_slope_5_bps_per_bar",
            "distance_to_ma21_atr14",
            "macd_zero_distance_atr14",
            "volume_ratio_20",
        ):
            object.__setattr__(self, field, _optional_finite_float(getattr(self, field)))


@dataclass(frozen=True, slots=True)
class SubingWatchKernelEvaluation:
    formula_version: str
    identity: SubingWatchKernelIdentity
    trading_day: str
    bar_end: str
    outcome: Literal[
        "evaluated_no_signal", "evaluated_candidate", "source_unavailable"
    ]
    observation_types: tuple[Literal["buy", "sell"], ...]
    close: float | None
    ma21: float | None
    dif: float | None
    dea: float | None
    macd_histogram: float | None
    context: SubingWatchKernelContext
    public_reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            self.formula_version != SUBING_WATCH_FORMULA_VERSION
            or type(self.identity) is not SubingWatchKernelIdentity
            or self.outcome not in _OUTCOMES
            or type(self.observation_types) is not tuple
            or any(item not in _OBSERVATION_TYPES for item in self.observation_types)
            or len(set(self.observation_types)) != len(self.observation_types)
            or type(self.context) is not SubingWatchKernelContext
            or type(self.public_reason_codes) is not tuple
            or any(not isinstance(code, str) or not code for code in self.public_reason_codes)
            or len(set(self.public_reason_codes)) != len(self.public_reason_codes)
        ):
            raise SubingWatchKernelError()
        trading_day = _trading_day(self.trading_day)
        if trading_day < self.identity.segment_start_trading_day:
            raise SubingWatchKernelError()
        object.__setattr__(self, "trading_day", trading_day)
        object.__setattr__(self, "bar_end", _rfc3339(self.bar_end))
        for field in ("close", "ma21", "dif", "dea", "macd_histogram"):
            object.__setattr__(self, field, _optional_finite_float(getattr(self, field)))


@dataclass(frozen=True, slots=True)
class SubingWatchKernelState:
    """Only the bounded streaming state permitted for the formula kernel."""

    policy_id: str
    identity: SubingWatchKernelIdentity
    sma21_window: tuple[float, ...]
    latest_five_valid_sma21: tuple[float, ...]
    macd_state: MacdState
    atr_state: AtrState
    range_state: RangeDetectorLuxState
    previous_ready_dif: float | None
    previous_ready_dea: float | None
    previous_twenty_volumes: tuple[float, ...]
    last_bar_fingerprint: str | None
    last_evaluation: SubingWatchKernelEvaluation | None
    blocked_reason: str | None

    def __post_init__(self) -> None:
        if (
            self.policy_id != SUBING_WATCH_FORMULA_VERSION
            or type(self.identity) is not SubingWatchKernelIdentity
            or type(self.sma21_window) is not tuple
            or type(self.latest_five_valid_sma21) is not tuple
            or type(self.previous_twenty_volumes) is not tuple
            or not 0 <= len(self.sma21_window) <= 21
            or not 0 <= len(self.latest_five_valid_sma21) <= 5
            or not 0 <= len(self.previous_twenty_volumes) <= 20
            or type(self.macd_state) is not MacdState
            or type(self.atr_state) is not AtrState
            or type(self.range_state) is not RangeDetectorLuxState
            or (
                self.last_evaluation is not None
                and type(self.last_evaluation) is not SubingWatchKernelEvaluation
            )
            or (
                self.blocked_reason is not None
                and (
                    not isinstance(self.blocked_reason, str)
                    or not self.blocked_reason
                    or self.blocked_reason != self.blocked_reason.strip()
                )
            )
            or ((self.last_bar_fingerprint is None) != (self.last_evaluation is None))
        ):
            raise SubingWatchKernelError()
        for values in (
            self.sma21_window,
            self.latest_five_valid_sma21,
            self.previous_twenty_volumes,
        ):
            if any(_finite_float(value) is None for value in values):
                raise SubingWatchKernelError()
        object.__setattr__(self, "previous_ready_dif", _optional_finite_float(self.previous_ready_dif))
        object.__setattr__(self, "previous_ready_dea", _optional_finite_float(self.previous_ready_dea))
        if self.last_bar_fingerprint is not None:
            assert self.last_evaluation is not None
            _source_fingerprint(self.last_bar_fingerprint)
            if self.last_evaluation.identity != self.identity:
                raise SubingWatchKernelError()


def initial_subing_watch_kernel_state(
    identity: SubingWatchKernelIdentity,
    policy: SubingWatchPolicy,
) -> SubingWatchKernelState:
    """Create the one bounded, frozen state for the exact accepted policy."""

    if type(identity) is not SubingWatchKernelIdentity or not _policy_is_exact(policy):
        raise SubingWatchKernelError()
    source_identity = "|".join(
        (
            identity.symbol,
            identity.contract,
            identity.segment_start_trading_day,
            identity.series_kind,
            identity.frequency,
        )
    )
    return SubingWatchKernelState(
        policy_id=SUBING_WATCH_FORMULA_VERSION,
        identity=identity,
        sma21_window=(),
        latest_five_valid_sma21=(),
        macd_state=initial_macd_state(
            12,
            26,
            9,
            ema_seed_policy="sma_window",
            histogram_scale=2,
            round_digits=6,
        ),
        atr_state=initial_atr_state(
            14,
            smoothing_policy="wilder_sma_seed",
            round_digits=6,
        ),
        range_state=initial_range_detector_lux_state(source_identity=source_identity),
        previous_ready_dif=None,
        previous_ready_dea=None,
        previous_twenty_volumes=(),
        last_bar_fingerprint=None,
        last_evaluation=None,
        blocked_reason=None,
    )


def step_subing_watch_15m(
    state: SubingWatchKernelState,
    bar: SubingWatchKernelBar,
    *,
    higher_timeframe: SubingWatchKernelHigherTimeframe | None = None,
) -> tuple[SubingWatchKernelState, SubingWatchKernelEvaluation]:
    """Advance the only completed-15m SuBing Watch formula state."""

    _validate_step_state(state)
    bar_valid = _bar_is_valid(bar)
    if not bar_valid:
        return _block_state(state, bar, "SUBING_WATCH_SOURCE_INVALID")
    if bar.identity != state.identity:
        return _block_state(state, bar, "SUBING_WATCH_IDENTITY_MISMATCH")
    if state.last_evaluation is not None:
        if bar.bar_end == state.last_evaluation.bar_end:
            if bar.source_fingerprint == state.last_bar_fingerprint:
                return state, state.last_evaluation
            raise SubingWatchDuplicateConflictError()

    if state.blocked_reason is not None:
        return state, _unavailable_evaluation(state, bar, state.blocked_reason)

    if bar.trading_day < state.identity.segment_start_trading_day:
        return _block_state(state, bar, "SUBING_WATCH_SEGMENT_MISMATCH")
    if (
        state.last_evaluation is not None
        and _parse_instant(bar.bar_end) < _parse_instant(state.last_evaluation.bar_end)
    ):
        return _block_state(state, bar, "SUBING_WATCH_SOURCE_INVALID", retain_last=True)

    sma21_window = (*state.sma21_window, bar.close)[-21:]
    raw_ma21 = sum(sma21_window) / 21 if len(sma21_window) == 21 else None
    macd_state, (dif_point, dea_point, histogram_point) = step_macd(
        state.macd_state,
        bar.close,
        bar_end=bar.bar_end,
    )
    current_dif = (
        dif_point.value
        if dif_point.ready and dif_point.valid and dif_point.value is not None
        else None
    )
    current_dea = (
        dea_point.value
        if dea_point.ready and dea_point.valid and dea_point.value is not None
        else None
    )
    current_ready = current_dif is not None and current_dea is not None
    if (
        current_dif is not None
        and current_dea is not None
        and state.previous_ready_dif is not None
        and state.previous_ready_dea is not None
    ):
        golden = (
            state.previous_ready_dif <= state.previous_ready_dea
            and current_dif > current_dea
        )
        dead = (
            state.previous_ready_dif >= state.previous_ready_dea
            and current_dif < current_dea
        )
    else:
        golden = False
        dead = False
    observations: tuple[Literal["buy", "sell"], ...] = ()
    if golden and raw_ma21 is not None and bar.close > raw_ma21:
        observations = ("buy",)
    elif dead and raw_ma21 is not None and bar.close < raw_ma21:
        observations = ("sell",)

    outcome: Literal["evaluated_no_signal", "evaluated_candidate"] = (
        "evaluated_candidate" if observations else "evaluated_no_signal"
    )
    (
        latest_five_valid_sma21,
        atr_state,
        range_state,
        previous_twenty_volumes,
        context,
    ) = _project_context(
        state,
        bar,
        raw_ma21=raw_ma21,
        current_dif=current_dif,
        current_dea=current_dea,
        observations=observations,
        higher_timeframe=higher_timeframe,
    )

    evaluation = SubingWatchKernelEvaluation(
        formula_version=SUBING_WATCH_FORMULA_VERSION,
        identity=state.identity,
        trading_day=bar.trading_day,
        bar_end=bar.bar_end,
        outcome=outcome,
        observation_types=observations,
        close=round(bar.close, 6),
        ma21=round(raw_ma21, 6) if raw_ma21 is not None else None,
        dif=current_dif,
        dea=current_dea,
        macd_histogram=(
            histogram_point.value
            if histogram_point.ready and histogram_point.valid
            else None
        ),
        context=context,
        public_reason_codes=(),
    )
    return (
        replace(
            state,
            sma21_window=sma21_window,
            latest_five_valid_sma21=latest_five_valid_sma21,
            macd_state=macd_state,
            atr_state=atr_state,
            range_state=range_state,
            previous_ready_dif=(
                current_dif if current_ready else state.previous_ready_dif
            ),
            previous_ready_dea=(
                current_dea if current_ready else state.previous_ready_dea
            ),
            previous_twenty_volumes=previous_twenty_volumes,
            last_bar_fingerprint=bar.source_fingerprint,
            last_evaluation=evaluation,
        ),
        evaluation,
    )


def _policy_is_exact(policy: object) -> bool:
    expected = {
        "policy_id": SUBING_WATCH_FORMULA_VERSION,
        "formula_version": SUBING_WATCH_FORMULA_VERSION,
        "series_kind": "actual_dominant",
        "frequency": "15m",
        "completed_bar_only": True,
        "ma_type": "simple_moving_average",
        "ma_period": 21,
        "ma_source": "close",
        "macd": (12, 26, 9),
        "ema_seed_policy": "sma_window",
        "histogram_scale": 2,
        "atr_period": 14,
        "atr_smoothing_policy": "wilder_sma_seed",
        "ma_slope_points": 5,
        "volume_previous_bars": 20,
        "range_indicator_code": "range_detector_lux_v1",
        "higher_timeframe": "60m",
        "round_digits": 6,
        "auto_order": False,
    }
    return all(
        type(getattr(policy, key, None)) is type(value)
        and getattr(policy, key, None) == value
        for key, value in expected.items()
    )


def _validate_step_state(state: object) -> None:
    if type(state) is not SubingWatchKernelState:
        raise SubingWatchKernelError()
    if (state.previous_ready_dif is None) != (state.previous_ready_dea is None):
        raise SubingWatchKernelError()
    if state.last_evaluation is not None and state.last_evaluation.identity != state.identity:
        raise SubingWatchKernelError()


def _bar_is_valid(bar: object) -> bool:
    if type(bar) is not SubingWatchKernelBar:
        return False
    try:
        if type(bar.identity) is not SubingWatchKernelIdentity:
            return False
        _rfc3339(bar.bar_end)
        _trading_day(bar.trading_day)
        open_value = _finite_float(bar.open)
        high = _finite_float(bar.high)
        low = _finite_float(bar.low)
        close = _finite_float(bar.close)
        volume = _finite_float(bar.volume)
        _source_fingerprint(bar.source_fingerprint)
    except SubingWatchKernelError:
        return False
    assert open_value is not None and high is not None and low is not None
    assert close is not None and volume is not None
    return low <= high and low <= open_value <= high and low <= close <= high and volume >= 0


def _parse_instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _unavailable_context() -> SubingWatchKernelContext:
    return SubingWatchKernelContext(
        ma21_slope_5_bps_per_bar=None,
        distance_to_ma21_atr14=None,
        macd_zero_distance_atr14=None,
        volume_ratio_20=None,
        range_state="range_unavailable",
        higher_timeframe_alignment="unavailable",
    )


def _project_context(
    state: SubingWatchKernelState,
    bar: SubingWatchKernelBar,
    *,
    raw_ma21: float | None,
    current_dif: float | None,
    current_dea: float | None,
    observations: tuple[Literal["buy", "sell"], ...],
    higher_timeframe: SubingWatchKernelHigherTimeframe | None,
) -> tuple[
    tuple[float, ...],
    AtrState,
    RangeDetectorLuxState,
    tuple[float, ...],
    SubingWatchKernelContext,
]:
    latest_five_valid_sma21 = state.latest_five_valid_sma21
    if raw_ma21 is not None:
        latest_five_valid_sma21 = (*latest_five_valid_sma21, raw_ma21)[-5:]

    ma21_slope = _ma21_regression_slope(latest_five_valid_sma21, raw_ma21)

    atr_state = state.atr_state
    atr14: float | None = None
    try:
        advanced_atr_state, atr_point = step_atr(
            state.atr_state,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            bar_end=bar.bar_end,
        )
        atr_state = advanced_atr_state
        if atr_point.ready and atr_point.valid:
            atr14 = _finite_context_value(advanced_atr_state.previous_atr)
    except Exception:
        atr_state = state.atr_state

    distance_to_ma21 = (
        _context_ratio(bar.close - raw_ma21, atr14)
        if raw_ma21 is not None
        else None
    )
    macd_zero_distance = (
        _context_ratio(max(abs(current_dif), abs(current_dea)), atr14)
        if current_dif is not None and current_dea is not None
        else None
    )

    volume_ratio = None
    if len(state.previous_twenty_volumes) == 20:
        previous_mean = _finite_context_value(
            sum(state.previous_twenty_volumes) / 20
        )
        volume_ratio = _context_ratio(bar.volume, previous_mean)
    previous_twenty_volumes = (*state.previous_twenty_volumes, bar.volume)[-20:]

    range_state = state.range_state
    projected_range_state: Literal[
        "range_unavailable", "no_active_range", "intact", "broken_up", "broken_down"
    ] = "range_unavailable"
    try:
        advanced_range_state, range_point = step_range_detector_lux(
            state.range_state,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            bar_end=bar.bar_end,
            trading_day=bar.trading_day,
        )
        range_state = advanced_range_state
        if range_point.ready and range_point.valid:
            projected_range_state = (
                "no_active_range"
                if range_point.snapshot is None
                else range_point.snapshot.state
            )
    except Exception:
        range_state = state.range_state

    higher_alignment = _higher_timeframe_alignment(
        state.identity,
        cutoff=bar.bar_end,
        observations=observations,
        higher_timeframe=higher_timeframe,
    )
    return (
        latest_five_valid_sma21,
        atr_state,
        range_state,
        previous_twenty_volumes,
        SubingWatchKernelContext(
            ma21_slope_5_bps_per_bar=ma21_slope,
            distance_to_ma21_atr14=distance_to_ma21,
            macd_zero_distance_atr14=macd_zero_distance,
            volume_ratio_20=volume_ratio,
            range_state=projected_range_state,
            higher_timeframe_alignment=higher_alignment,
        ),
    )


def _ma21_regression_slope(
    latest_five_valid_sma21: tuple[float, ...],
    current_ma21: float | None,
) -> float | None:
    if len(latest_five_valid_sma21) != 5 or current_ma21 is None:
        return None
    try:
        slope = sum(
            (index - 2) * value
            for index, value in enumerate(latest_five_valid_sma21)
        ) / 10
        return _context_ratio(slope * 10_000, current_ma21)
    except Exception:
        return None


def _context_ratio(numerator: float, denominator: float | None) -> float | None:
    if denominator is None or denominator == 0:
        return None
    try:
        return _rounded_context_value(numerator / denominator)
    except (ArithmeticError, TypeError, ValueError):
        return None


def _finite_context_value(value: object) -> float | None:
    try:
        return _optional_finite_float(value)
    except SubingWatchKernelError:
        return None


def _rounded_context_value(value: object) -> float | None:
    finite = _finite_context_value(value)
    return round(finite, 6) if finite is not None else None


def _higher_timeframe_alignment(
    identity: SubingWatchKernelIdentity,
    *,
    cutoff: str,
    observations: tuple[Literal["buy", "sell"], ...],
    higher_timeframe: SubingWatchKernelHigherTimeframe | None,
) -> Literal["aligned", "opposed", "neutral", "unavailable"]:
    if type(higher_timeframe) is not SubingWatchKernelHigherTimeframe:
        return "unavailable"
    try:
        higher_bar_end = _rfc3339(higher_timeframe.bar_end)
    except SubingWatchKernelError:
        return "unavailable"
    if _parse_instant(higher_bar_end) > _parse_instant(cutoff):
        raise SubingWatchHigherTimeframeFutureError()
    if (
        higher_timeframe.identity != identity
        or higher_timeframe.ready is not True
        or higher_timeframe.valid is not True
    ):
        return "unavailable"
    close = _finite_context_value(higher_timeframe.close)
    ma21 = _finite_context_value(higher_timeframe.ma21)
    slope = _finite_context_value(higher_timeframe.ma21_slope_5_bps_per_bar)
    if close is None or ma21 is None or slope is None:
        return "unavailable"
    if len(observations) != 1:
        return "neutral"
    direction = observations[0]
    opposite = "sell" if direction == "buy" else "buy"
    price_side: Literal["buy", "sell"] | None = (
        "buy" if close > ma21 else "sell" if close < ma21 else None
    )
    slope_side: Literal["buy", "sell"] | None = (
        "buy" if slope > 0 else "sell" if slope < 0 else None
    )
    if price_side == direction and slope_side == direction:
        return "aligned"
    if price_side == opposite and slope_side == opposite:
        return "opposed"
    return "neutral"


def _unavailable_evaluation(
    state: SubingWatchKernelState,
    bar: object,
    reason: str,
) -> SubingWatchKernelEvaluation:
    if type(bar) is SubingWatchKernelBar:
        try:
            bar_end = _rfc3339(bar.bar_end)
            trading_day = _trading_day(bar.trading_day)
        except SubingWatchKernelError:
            bar_end, trading_day = _fallback_source_coordinates(state)
    else:
        bar_end, trading_day = _fallback_source_coordinates(state)
    if trading_day < state.identity.segment_start_trading_day:
        trading_day = state.identity.segment_start_trading_day
    return SubingWatchKernelEvaluation(
        formula_version=SUBING_WATCH_FORMULA_VERSION,
        identity=state.identity,
        trading_day=trading_day,
        bar_end=bar_end,
        outcome="source_unavailable",
        observation_types=(),
        close=None,
        ma21=None,
        dif=None,
        dea=None,
        macd_histogram=None,
        context=_unavailable_context(),
        public_reason_codes=(reason,),
    )


def _fallback_source_coordinates(state: SubingWatchKernelState) -> tuple[str, str]:
    if state.last_evaluation is not None:
        return state.last_evaluation.bar_end, state.last_evaluation.trading_day
    return (
        f"{state.identity.segment_start_trading_day}T00:00:00+00:00",
        state.identity.segment_start_trading_day,
    )


def _block_state(
    state: SubingWatchKernelState,
    bar: object,
    reason: str,
    *,
    retain_last: bool = False,
) -> tuple[SubingWatchKernelState, SubingWatchKernelEvaluation]:
    evaluation = _unavailable_evaluation(state, bar, reason)
    if retain_last or type(bar) is not SubingWatchKernelBar:
        return replace(state, blocked_reason=reason), evaluation
    try:
        _source_fingerprint(bar.source_fingerprint)
    except SubingWatchKernelError:
        return replace(state, blocked_reason=reason), evaluation
    return (
        replace(
            state,
            last_bar_fingerprint=bar.source_fingerprint,
            last_evaluation=evaluation,
            blocked_reason=reason,
        ),
        evaluation,
    )
