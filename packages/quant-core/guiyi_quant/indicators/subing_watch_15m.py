"""Frozen, dependency-free contracts for the SuBing Watch 15m kernel."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
import math
import re
from typing import Literal

from .atr import initial_atr_state
from .macd import initial_macd_state
from .models import AtrState, MacdState
from .range_detector_lux import (
    RangeDetectorLuxState,
    initial_range_detector_lux_state,
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
_SOURCE_FINGERPRINT_PREFIX = "subing-watch-bar:v1"


class SubingWatchKernelError(ValueError):
    code = "SUBING_WATCH_KERNEL_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


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


def _source_fingerprint(value: object) -> tuple[str, str, tuple[Decimal, ...]]:
    if not isinstance(value, str):
        raise SubingWatchKernelError()
    fields = value.split("|")
    if len(fields) != 8 or fields[0] != _SOURCE_FINGERPRINT_PREFIX:
        raise SubingWatchKernelError()
    bar_end = _rfc3339(fields[1])
    trading_day = _trading_day(fields[2])
    try:
        decimals = tuple(Decimal(item) for item in fields[3:])
    except (InvalidOperation, ValueError):
        raise SubingWatchKernelError() from None
    if (
        len(decimals) != 5
        or any(not item.is_finite() or str(item) != raw for item, raw in zip(decimals, fields[3:], strict=True))
    ):
        raise SubingWatchKernelError()
    return bar_end, trading_day, decimals


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
    bar_end: str
    trading_day: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    source_fingerprint: str

    def __post_init__(self) -> None:
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
        fingerprint_bar_end, fingerprint_day, fingerprint_values = _source_fingerprint(
            self.source_fingerprint
        )
        if (
            fingerprint_bar_end != bar_end
            or fingerprint_day != trading_day
            or any(
                float(source) != actual
                for source, actual in zip(
                    fingerprint_values,
                    (open_value, high, low, close, volume),
                    strict=True,
                )
            )
        ):
            raise SubingWatchKernelError()
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

    def __post_init__(self) -> None:
        if type(self.ready) is not bool or type(self.valid) is not bool:
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
            bar_end, trading_day, _ = _source_fingerprint(self.last_bar_fingerprint)
            if (
                self.last_evaluation.identity != self.identity
                or self.last_evaluation.bar_end != bar_end
                or self.last_evaluation.trading_day != trading_day
            ):
                raise SubingWatchKernelError()


def initial_subing_watch_kernel_state(
    identity: SubingWatchKernelIdentity,
) -> SubingWatchKernelState:
    """Create the one bounded, frozen state shape consumed by later kernel work."""

    if type(identity) is not SubingWatchKernelIdentity:
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
