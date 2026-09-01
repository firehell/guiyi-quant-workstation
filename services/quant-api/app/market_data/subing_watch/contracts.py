"""Strict application contracts for the frozen SuBing Watch 15m policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any, Literal

from guiyi_quant.indicators.subing_watch_15m import (
    SUBING_WATCH_FORMULA_VERSION,
    SubingWatchKernelBar,
    SubingWatchKernelEvaluation,
)

from app.core.env import PROJECT_ROOT
from app.core.exact_json_contract import load_exact_json

from ..domain import CanonicalBar, normalize_contract_for_symbol


_POLICY_PATH = PROJECT_ROOT / "data/research_policies/subing_watch_15m_v1.json"
_EXPECTED_PAYLOAD: dict[str, Any] = {
    "schema_version": 1,
    "formula_version": SUBING_WATCH_FORMULA_VERSION,
    "policy_id": SUBING_WATCH_FORMULA_VERSION,
    "series_kind": "actual_dominant",
    "frequency": "15m",
    "completed_bar_only": True,
    "ma": {"type": "simple_moving_average", "period": 21, "source": "close"},
    "macd": {
        "fast": 12,
        "slow": 26,
        "signal": 9,
        "ema_seed_policy": "sma_window",
        "histogram_scale": 2,
    },
    "context": {
        "atr_period": 14,
        "atr_smoothing_policy": "wilder_sma_seed",
        "ma_slope_points": 5,
        "volume_previous_bars": 20,
        "range_indicator_code": "range_detector_lux_v1",
        "higher_timeframe": "60m",
    },
    "round_digits": 6,
    "auto_order": False,
}
_OUTCOMES = frozenset(
    {"evaluated_no_signal", "evaluated_candidate", "source_unavailable", "processing_failed"}
)
_OBSERVATION_TYPES = frozenset({"buy", "sell"})
_RANGE_STATES = frozenset(
    {"range_unavailable", "no_active_range", "intact", "broken_up", "broken_down"}
)
_HIGHER_TIMEFRAME_ALIGNMENTS = frozenset(
    {"aligned", "opposed", "neutral", "unavailable"}
)
_ROUND_DIGITS = 6
_SOURCE_FINGERPRINT_PREFIX = "subing-watch-bar:v1"


class SubingWatchPolicyError(ValueError):
    code = "SUBING_WATCH_POLICY_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


class SubingWatchContractError(ValueError):
    code = "SUBING_WATCH_CONTRACT_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


def _aware(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise SubingWatchContractError()
    return value.astimezone(UTC)


def _decimal(value: object, *, optional: bool = False) -> Decimal | None:
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, Decimal) or not value.is_finite():
        raise SubingWatchContractError()
    return value


def _kernel_float_to_decimal(value: float | None) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, float) or not math.isfinite(value):
        raise SubingWatchContractError()
    try:
        result = Decimal(format(value, f".{_ROUND_DIGITS}f"))
    except (InvalidOperation, ValueError):
        raise SubingWatchContractError() from None
    if not result.is_finite():
        raise SubingWatchContractError()
    return result


def _decimal_to_kernel_float(value: Decimal) -> float:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise SubingWatchContractError()
    result = float(value)
    if not math.isfinite(result):
        raise SubingWatchContractError()
    return result


def _canonical_decimal_text(value: Decimal) -> str:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise SubingWatchContractError()
    return str(value)


def _canonical_bar_fingerprint(bar: CanonicalBar) -> str:
    return "|".join(
        (
            _SOURCE_FINGERPRINT_PREFIX,
            bar.bar_end.astimezone(UTC).isoformat(),
            bar.trading_day.isoformat(),
            _canonical_decimal_text(bar.open),
            _canonical_decimal_text(bar.high),
            _canonical_decimal_text(bar.low),
            _canonical_decimal_text(bar.close),
            _canonical_decimal_text(bar.volume),
        )
    )


def _kernel_instant(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        raise SubingWatchContractError() from None
    return _aware(parsed)


@dataclass(frozen=True, slots=True)
class SubingWatchPolicy:
    policy_id: str
    formula_version: str
    series_kind: Literal["actual_dominant"]
    frequency: Literal["15m"]
    completed_bar_only: Literal[True]
    ma_type: Literal["simple_moving_average"]
    ma_period: int
    ma_source: Literal["close"]
    macd: tuple[int, int, int]
    ema_seed_policy: Literal["sma_window"]
    histogram_scale: Literal[2]
    atr_period: int
    atr_smoothing_policy: Literal["wilder_sma_seed"]
    ma_slope_points: int
    volume_previous_bars: int
    range_indicator_code: Literal["range_detector_lux_v1"]
    higher_timeframe: Literal["60m"]
    round_digits: int
    auto_order: Literal[False]

    def __post_init__(self) -> None:
        if (
            self.policy_id != SUBING_WATCH_FORMULA_VERSION
            or self.formula_version != SUBING_WATCH_FORMULA_VERSION
            or self.series_kind != "actual_dominant"
            or self.frequency != "15m"
            or self.completed_bar_only is not True
            or self.ma_type != "simple_moving_average"
            or self.ma_period != 21
            or self.ma_source != "close"
            or self.macd != (12, 26, 9)
            or self.ema_seed_policy != "sma_window"
            or self.histogram_scale != 2
            or self.atr_period != 14
            or self.atr_smoothing_policy != "wilder_sma_seed"
            or self.ma_slope_points != 5
            or self.volume_previous_bars != 20
            or self.range_indicator_code != "range_detector_lux_v1"
            or self.higher_timeframe != "60m"
            or self.round_digits != 6
            or self.auto_order is not False
        ):
            raise SubingWatchPolicyError()


def load_subing_watch_policy(path: Path | None = None) -> SubingWatchPolicy:
    payload = load_exact_json(path or _POLICY_PATH, _EXPECTED_PAYLOAD, SubingWatchPolicyError)
    macd = payload["macd"]
    ma = payload["ma"]
    context = payload["context"]
    assert isinstance(macd, dict) and isinstance(ma, dict) and isinstance(context, dict)
    return SubingWatchPolicy(
        policy_id=payload["policy_id"],
        formula_version=payload["formula_version"],
        series_kind=payload["series_kind"],
        frequency=payload["frequency"],
        completed_bar_only=payload["completed_bar_only"],
        ma_type=ma["type"],
        ma_period=ma["period"],
        ma_source=ma["source"],
        macd=(macd["fast"], macd["slow"], macd["signal"]),
        ema_seed_policy=macd["ema_seed_policy"],
        histogram_scale=macd["histogram_scale"],
        atr_period=context["atr_period"],
        atr_smoothing_policy=context["atr_smoothing_policy"],
        ma_slope_points=context["ma_slope_points"],
        volume_previous_bars=context["volume_previous_bars"],
        range_indicator_code=context["range_indicator_code"],
        higher_timeframe=context["higher_timeframe"],
        round_digits=payload["round_digits"],
        auto_order=payload["auto_order"],
    )


@dataclass(frozen=True, slots=True)
class SubingWatchSourceIdentity:
    symbol: str
    contract: str
    segment_start_trading_day: date
    series_kind: Literal["actual_dominant"] = "actual_dominant"
    frequency: Literal["15m"] = "15m"

    def __post_init__(self) -> None:
        if (
            not isinstance(self.symbol, str)
            or self.symbol != self.symbol.strip().lower()
            or not self.symbol.isascii()
            or not self.symbol.isalpha()
            or normalize_contract_for_symbol(self.symbol, self.contract) != self.contract
            or type(self.segment_start_trading_day) is not date
            or self.series_kind != "actual_dominant"
            or self.frequency != "15m"
        ):
            raise SubingWatchContractError()


def _source_identity_digest(identity: SubingWatchSourceIdentity) -> str:
    payload = json.dumps(
        {
            "symbol": identity.symbol,
            "contract": identity.contract,
            "segment_start_trading_day": identity.segment_start_trading_day.isoformat(),
            "series_kind": identity.series_kind,
            "frequency": identity.frequency,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"subing-watch-source:{sha256(payload).hexdigest()}"


@dataclass(frozen=True, slots=True)
class SubingWatchContext:
    ma21_slope_5_bps_per_bar: Decimal | None
    distance_to_ma21_atr14: Decimal | None
    macd_zero_distance_atr14: Decimal | None
    volume_ratio_20: Decimal | None
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
            raise SubingWatchContractError()
        for field in (
            "ma21_slope_5_bps_per_bar",
            "distance_to_ma21_atr14",
            "macd_zero_distance_atr14",
            "volume_ratio_20",
        ):
            object.__setattr__(self, field, _decimal(getattr(self, field), optional=True))


@dataclass(frozen=True, slots=True)
class SubingWatchEvaluation:
    formula_version: str
    source_identity: SubingWatchSourceIdentity
    source_identity_digest: str
    trading_day: date
    bar_end: datetime
    source_mode: Literal["canonical", "canonical_live"]
    outcome: Literal[
        "evaluated_no_signal", "evaluated_candidate", "source_unavailable", "processing_failed"
    ]
    observation_types: tuple[Literal["buy", "sell"], ...]
    close: Decimal | None
    ma21: Decimal | None
    dif: Decimal | None
    dea: Decimal | None
    macd_histogram: Decimal | None
    context: SubingWatchContext
    candidate_id: str | None
    public_reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            self.formula_version != SUBING_WATCH_FORMULA_VERSION
            or type(self.source_identity) is not SubingWatchSourceIdentity
            or self.source_identity_digest != _source_identity_digest(self.source_identity)
            or type(self.trading_day) is not date
            or self.trading_day < self.source_identity.segment_start_trading_day
            or self.source_mode not in {"canonical", "canonical_live"}
            or self.outcome not in _OUTCOMES
            or type(self.observation_types) is not tuple
            or any(item not in _OBSERVATION_TYPES for item in self.observation_types)
            or len(set(self.observation_types)) != len(self.observation_types)
            or type(self.context) is not SubingWatchContext
            or (self.candidate_id is not None and (not isinstance(self.candidate_id, str) or not self.candidate_id))
            or type(self.public_reason_codes) is not tuple
            or any(not isinstance(code, str) or not code for code in self.public_reason_codes)
            or len(set(self.public_reason_codes)) != len(self.public_reason_codes)
        ):
            raise SubingWatchContractError()
        object.__setattr__(self, "bar_end", _aware(self.bar_end))
        for field in ("close", "ma21", "dif", "dea", "macd_histogram"):
            object.__setattr__(self, field, _decimal(getattr(self, field), optional=True))


def to_subing_watch_kernel_bar(bar: CanonicalBar) -> SubingWatchKernelBar:
    """Cross the only Decimal-to-float boundary for a completed canonical bar."""

    if type(bar) is not CanonicalBar:
        raise SubingWatchContractError()
    return SubingWatchKernelBar(
        bar_end=bar.bar_end.isoformat(),
        trading_day=bar.trading_day.isoformat(),
        open=_decimal_to_kernel_float(bar.open),
        high=_decimal_to_kernel_float(bar.high),
        low=_decimal_to_kernel_float(bar.low),
        close=_decimal_to_kernel_float(bar.close),
        volume=_decimal_to_kernel_float(bar.volume),
        source_fingerprint=_canonical_bar_fingerprint(bar),
    )


def from_kernel_evaluation(
    evaluation: SubingWatchKernelEvaluation,
    *,
    source_mode: Literal["canonical", "canonical_live"],
) -> SubingWatchEvaluation:
    """Cross the only float-to-Decimal boundary for a kernel evaluation."""

    if type(evaluation) is not SubingWatchKernelEvaluation:
        raise SubingWatchContractError()
    identity = SubingWatchSourceIdentity(
        symbol=evaluation.identity.symbol,
        contract=evaluation.identity.contract,
        segment_start_trading_day=date.fromisoformat(evaluation.identity.segment_start_trading_day),
        series_kind=evaluation.identity.series_kind,
        frequency=evaluation.identity.frequency,
    )
    context = SubingWatchContext(
        ma21_slope_5_bps_per_bar=_kernel_float_to_decimal(evaluation.context.ma21_slope_5_bps_per_bar),
        distance_to_ma21_atr14=_kernel_float_to_decimal(evaluation.context.distance_to_ma21_atr14),
        macd_zero_distance_atr14=_kernel_float_to_decimal(evaluation.context.macd_zero_distance_atr14),
        volume_ratio_20=_kernel_float_to_decimal(evaluation.context.volume_ratio_20),
        range_state=evaluation.context.range_state,
        higher_timeframe_alignment=evaluation.context.higher_timeframe_alignment,
    )
    return SubingWatchEvaluation(
        formula_version=evaluation.formula_version,
        source_identity=identity,
        source_identity_digest=_source_identity_digest(identity),
        trading_day=date.fromisoformat(evaluation.trading_day),
        bar_end=_kernel_instant(evaluation.bar_end),
        source_mode=source_mode,
        outcome=evaluation.outcome,
        observation_types=evaluation.observation_types,
        close=_kernel_float_to_decimal(evaluation.close),
        ma21=_kernel_float_to_decimal(evaluation.ma21),
        dif=_kernel_float_to_decimal(evaluation.dif),
        dea=_kernel_float_to_decimal(evaluation.dea),
        macd_histogram=_kernel_float_to_decimal(evaluation.macd_histogram),
        context=context,
        candidate_id=None,
        public_reason_codes=evaluation.public_reason_codes,
    )
