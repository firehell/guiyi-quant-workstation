"""Futures-only main-force mirror V1 observation contracts.

The indicator is a directional position-pressure proxy.  It is not measured
fund flow, participant identity, a trading signal, or an order instruction.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Literal

import numpy as np


INDICATOR_CODE = "main_force_mirror_futures_v1"
INDICATOR_VERSION = "futures-research-v1"
MainForceMirrorFuturesState = Literal[
    "long_build",
    "short_build",
    "short_cover",
    "long_liquidation",
    "turnover",
]
MainForceMirrorFuturesCaution = Literal[
    "long_chase_caution",
    "short_chase_caution",
]

DEFAULT_PARAMETERS = MappingProxyType(
    {
        "atr_period": 14,
        "volume_window": 20,
        "oi_impulse_ema_period": 20,
        "range_window": 20,
        "pressure_divergence_window": 10,
        "direction_price_weight": 0.7,
        "direction_clv_weight": 0.3,
        "direction_deadband": 0.15,
        "oi_deadband": 0.25,
        "volume_ratio_clip": 3.0,
        "price_impulse_clip": 3.0,
        "oi_impulse_clip": 3.0,
        "strength_scale": 25.0,
        "turnover_display_cap": 15.0,
        "upper_location_threshold": 0.85,
        "lower_location_threshold": 0.15,
        "liquidation_dominated_oi_threshold": 0.5,
        "pressure_confirmation_ratio": 0.7,
        "high_volume_threshold": 1.5,
        "clv_rejection_threshold": 0.25,
        "wick_rejection_threshold": 0.35,
        "caution_threshold": 70,
        "rearm_score_threshold": 40,
        "rearm_low_score_bars": 3,
        "rearm_build_bars": 2,
        "long_rearm_range_threshold": 0.65,
        "short_rearm_range_threshold": 0.35,
        "round_digits": 6,
        "rounding_policy": "half_away_from_zero_binary64",
    }
)

_PHYSICAL_CONTRACT_MISSING = "MFM_FUTURES_V1_PHYSICAL_CONTRACT_MISSING"
_TIMESTAMP_INVALID = "MFM_FUTURES_V1_TIMESTAMP_INVALID"
_OPEN_INTEREST_UNAVAILABLE = "MFM_FUTURES_V1_OPEN_INTEREST_UNAVAILABLE"
_INPUT_INVALID = "MFM_FUTURES_V1_INPUT_INVALID"
_WARMUP = "MFM_FUTURES_V1_WARMUP"
_CAUTION_WARMUP = "MFM_FUTURES_V1_CAUTION_WARMUP"
_ATR_INVALID = "MFM_FUTURES_V1_ATR_INVALID"
_VOLUME_BASELINE_INVALID = "MFM_FUTURES_V1_VOLUME_BASELINE_INVALID"
_RANGE_INVALID = "MFM_FUTURES_V1_RANGE_INVALID"


@dataclass(frozen=True)
class MainForceMirrorFuturesResult:
    """One-to-one aligned Futures V1 observation result."""

    datetimes: np.ndarray
    physical_contract: np.ndarray

    valid: np.ndarray
    state_ready: np.ndarray
    caution_ready: np.ndarray
    ready: np.ndarray

    reason: np.ndarray
    caution_availability_reason: np.ndarray

    state: np.ndarray
    signed_score: np.ndarray
    strength: np.ndarray

    price_impulse: np.ndarray
    clv: np.ndarray
    volume_ratio: np.ndarray
    delta_oi: np.ndarray
    oi_impulse: np.ndarray
    direction: np.ndarray
    range_position: np.ndarray

    long_open_pressure: np.ndarray
    short_open_pressure: np.ndarray

    long_caution_score: np.ndarray
    short_caution_score: np.ndarray
    caution: np.ndarray
    caution_reason_codes: tuple[tuple[str, ...], ...]

    metadata: dict[str, Any]


def round_half_away_from_zero_binary64(value: float, digits: int) -> float:
    """Round a binary64 value with the frozen cross-runtime V1 policy."""

    if not np.isfinite(value):
        return value
    if isinstance(digits, bool) or not isinstance(digits, int) or digits < 0:
        raise ValueError("digits must be a non-negative integer")
    scale = float(10**digits)
    if value == 0:
        return 0.0
    magnitude = np.floor(abs(value) * scale + 0.5) / scale
    result = float(np.copysign(magnitude, value))
    return 0.0 if result == 0 else result


def classify_main_force_mirror_futures_state(
    direction: float,
    oi_impulse: float,
) -> MainForceMirrorFuturesState:
    """Classify one raw direction/OI point using the frozen strict deadbands."""

    if (
        abs(direction) < DEFAULT_PARAMETERS["direction_deadband"]
        or abs(oi_impulse) < DEFAULT_PARAMETERS["oi_deadband"]
    ):
        return "turnover"
    if direction >= DEFAULT_PARAMETERS["direction_deadband"]:
        return (
            "long_build"
            if oi_impulse >= DEFAULT_PARAMETERS["oi_deadband"]
            else "short_cover"
        )
    return (
        "short_build"
        if oi_impulse >= DEFAULT_PARAMETERS["oi_deadband"]
        else "long_liquidation"
    )


def compute_main_force_mirror_futures(
    datetimes: Sequence[Any],
    physical_contract: Sequence[str | None],
    open_: Sequence[float],
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    volume: Sequence[float],
    open_interest: Sequence[float | None],
) -> MainForceMirrorFuturesResult:
    """Validate inputs and split them into exact physical-contract blocks."""

    raw_datetimes = _object_array(datetimes, name="datetimes")
    raw_contracts = _object_array(physical_contract, name="physical_contract")
    raw_open = _object_array(open_, name="open")
    raw_high = _object_array(high, name="high")
    raw_low = _object_array(low, name="low")
    raw_close = _object_array(close, name="close")
    raw_volume = _object_array(volume, name="volume")
    raw_open_interest = _object_array(open_interest, name="open_interest")
    _require_same_length(
        datetimes=raw_datetimes,
        physical_contract=raw_contracts,
        open=raw_open,
        high=raw_high,
        low=raw_low,
        close=raw_close,
        volume=raw_volume,
        open_interest=raw_open_interest,
    )

    count = len(raw_datetimes)
    normalized_contracts = np.full(count, None, dtype=object)
    valid = np.zeros(count, dtype=bool)
    state_ready = np.zeros(count, dtype=bool)
    caution_ready = np.zeros(count, dtype=bool)
    reason = np.full(count, None, dtype=object)
    caution_reason = np.full(count, None, dtype=object)
    high_values = np.full(count, np.nan, dtype=float)
    low_values = np.full(count, np.nan, dtype=float)
    close_values = np.full(count, np.nan, dtype=float)
    volume_values = np.full(count, np.nan, dtype=float)
    oi_values = np.full(count, np.nan, dtype=float)
    state = np.full(count, None, dtype=object)
    signed_score = np.full(count, np.nan, dtype=float)
    strength = np.full(count, np.nan, dtype=float)
    price_impulse = np.full(count, np.nan, dtype=float)
    clv = np.full(count, np.nan, dtype=float)
    volume_ratio = np.full(count, np.nan, dtype=float)
    delta_oi = np.full(count, np.nan, dtype=float)
    oi_impulse = np.full(count, np.nan, dtype=float)
    direction = np.full(count, np.nan, dtype=float)
    range_position = np.full(count, np.nan, dtype=float)
    long_open_pressure = np.full(count, np.nan, dtype=float)
    short_open_pressure = np.full(count, np.nan, dtype=float)

    max_seen_parseable_time: int | None = None

    for index in range(count):
        contract = _normalize_contract(raw_contracts[index])
        normalized_contracts[index] = contract

        parsed_time = _parse_timestamp(raw_datetimes[index])
        timestamp_invalid = parsed_time is None
        if parsed_time is not None:
            timestamp_invalid = (
                max_seen_parseable_time is not None
                and parsed_time <= max_seen_parseable_time
            )
            if max_seen_parseable_time is None or parsed_time > max_seen_parseable_time:
                max_seen_parseable_time = parsed_time

        open_value = _finite_number(raw_open[index])
        high_value = _finite_number(raw_high[index])
        low_value = _finite_number(raw_low[index])
        close_value = _finite_number(raw_close[index])
        volume_value = _finite_number(raw_volume[index])
        oi_value = _finite_number(raw_open_interest[index])
        if high_value is not None:
            high_values[index] = high_value
        if low_value is not None:
            low_values[index] = low_value
        if close_value is not None:
            close_values[index] = close_value
        if volume_value is not None:
            volume_values[index] = volume_value
        if oi_value is not None:
            oi_values[index] = oi_value

        oi_invalid = oi_value is None or oi_value < 0
        numeric_invalid = not _valid_ohlcv(
            open_value,
            high_value,
            low_value,
            close_value,
            volume_value,
        )

        invalid_reason: str | None = None
        if contract is None:
            invalid_reason = _PHYSICAL_CONTRACT_MISSING
        elif timestamp_invalid:
            invalid_reason = _TIMESTAMP_INVALID
        elif oi_invalid:
            invalid_reason = _OPEN_INTEREST_UNAVAILABLE
        elif numeric_invalid:
            invalid_reason = _INPUT_INVALID

        if invalid_reason is not None:
            reason[index] = invalid_reason
            continue

        valid[index] = True

    _apply_readiness(
        valid=valid,
        contracts=normalized_contracts,
        high=high_values,
        low=low_values,
        close=close_values,
        volume=volume_values,
        open_interest=oi_values,
        state_ready=state_ready,
        caution_ready=caution_ready,
        reason=reason,
        caution_reason=caution_reason,
        state=state,
        signed_score=signed_score,
        price_impulse=price_impulse,
        clv=clv,
        volume_ratio=volume_ratio,
        delta_oi=delta_oi,
        oi_impulse=oi_impulse,
        direction=direction,
        range_position=range_position,
        long_open_pressure=long_open_pressure,
        short_open_pressure=short_open_pressure,
        strength=strength,
    )

    long_caution_score = np.full(count, np.nan, dtype=float)
    short_caution_score = np.full(count, np.nan, dtype=float)
    caution = np.full(count, None, dtype=object)
    parameters = dict(DEFAULT_PARAMETERS)
    parameters_payload = json.dumps(
        parameters,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    parameters_hash = hashlib.sha256(parameters_payload.encode("utf-8")).hexdigest()[:16]
    return MainForceMirrorFuturesResult(
        datetimes=raw_datetimes,
        physical_contract=normalized_contracts,
        valid=valid,
        state_ready=state_ready,
        caution_ready=caution_ready,
        ready=caution_ready.copy(),
        reason=reason,
        caution_availability_reason=caution_reason,
        state=state,
        signed_score=signed_score,
        strength=strength,
        price_impulse=price_impulse,
        clv=clv,
        volume_ratio=volume_ratio,
        delta_oi=delta_oi,
        oi_impulse=oi_impulse,
        direction=direction,
        range_position=range_position,
        long_open_pressure=long_open_pressure,
        short_open_pressure=short_open_pressure,
        long_caution_score=long_caution_score,
        short_caution_score=short_caution_score,
        caution=caution,
        caution_reason_codes=tuple(() for _ in range(count)),
        metadata={
            "indicator_code": INDICATOR_CODE,
            "indicator_version": INDICATOR_VERSION,
            "status": "observation_only",
            "supported_frequencies": ("60m",),
            "supported_series_kinds": ("contract", "actual_dominant"),
            "future_looking": False,
            "repainting_risk": "none",
            "closed_bar_only": True,
            "confirmed_only": True,
            "web_capable": True,
            "backtest_capable": False,
            "live_capable": False,
            "alert_capable": False,
            "notification_capable": False,
            "auto_order": False,
            "parameters": parameters,
            "parameters_hash": parameters_hash,
            "rounding_policy": DEFAULT_PARAMETERS["rounding_policy"],
            "interpretation": "directional_position_pressure_proxy_not_measured_fund_flow",
        },
    )


def _apply_readiness(
    *,
    valid: np.ndarray,
    contracts: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
    open_interest: np.ndarray,
    state_ready: np.ndarray,
    caution_ready: np.ndarray,
    reason: np.ndarray,
    caution_reason: np.ndarray,
    state: np.ndarray,
    signed_score: np.ndarray,
    price_impulse: np.ndarray,
    clv: np.ndarray,
    volume_ratio: np.ndarray,
    delta_oi: np.ndarray,
    oi_impulse: np.ndarray,
    direction: np.ndarray,
    range_position: np.ndarray,
    long_open_pressure: np.ndarray,
    short_open_pressure: np.ndarray,
    strength: np.ndarray,
) -> None:
    count = len(valid)
    index = 0
    while index < count:
        if not valid[index]:
            index += 1
            continue
        start = index
        contract = contracts[start]
        while index + 1 < count and valid[index + 1] and contracts[index + 1] == contract:
            index += 1
        end = index + 1

        block_high = high[start:end]
        block_low = low[start:end]
        block_close = close[start:end]
        block_volume = volume[start:end]
        block_oi = open_interest[start:end]
        atr = _wilder_atr14(block_high, block_low, block_close)
        volume_mean = _rolling_mean(block_volume, 20)
        range_high = _rolling_extreme(block_high, 20, maximum=True)
        range_low = _rolling_extreme(block_low, 20, maximum=False)
        oi_delta = np.diff(block_oi)
        oi_baseline = _ema_sma_seed(np.abs(oi_delta), 20)

        for block_index in range(end - start):
            output_index = start + block_index
            caution_reason[output_index] = _CAUTION_WARMUP
            if block_index < 20:
                reason[output_index] = _WARMUP
                continue
            if not np.isfinite(atr[block_index]) or atr[block_index] <= 0:
                reason[output_index] = _ATR_INVALID
                continue
            if (
                not np.isfinite(volume_mean[block_index])
                or volume_mean[block_index] <= 0
            ):
                reason[output_index] = _VOLUME_BASELINE_INVALID
                continue
            if (
                not np.isfinite(range_high[block_index])
                or not np.isfinite(range_low[block_index])
                or range_high[block_index] == range_low[block_index]
            ):
                reason[output_index] = _RANGE_INVALID
                continue
            oi_baseline_index = block_index - 1
            if (
                oi_baseline_index < 0
                or not np.isfinite(oi_baseline[oi_baseline_index])
            ):
                reason[output_index] = _WARMUP
                continue
            state_ready[output_index] = True
            reason[output_index] = None

            raw_price_impulse = float(
                np.clip(
                    (block_close[block_index] - block_close[block_index - 1])
                    / atr[block_index],
                    -DEFAULT_PARAMETERS["price_impulse_clip"],
                    DEFAULT_PARAMETERS["price_impulse_clip"],
                )
            )
            if block_high[block_index] > block_low[block_index]:
                raw_clv = float(
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
            else:
                raw_clv = 0.0
            raw_direction = float(
                DEFAULT_PARAMETERS["direction_price_weight"] * raw_price_impulse
                + DEFAULT_PARAMETERS["direction_clv_weight"] * raw_clv
            )
            raw_volume_ratio = float(
                np.clip(
                    block_volume[block_index] / volume_mean[block_index],
                    0.0,
                    DEFAULT_PARAMETERS["volume_ratio_clip"],
                )
            )
            participation = float(np.sqrt(raw_volume_ratio))
            raw_delta_oi = float(block_oi[block_index] - block_oi[block_index - 1])
            baseline = float(oi_baseline[oi_baseline_index])
            raw_oi_impulse = (
                0.0
                if baseline == 0.0
                else float(
                    np.clip(
                        raw_delta_oi / baseline,
                        -DEFAULT_PARAMETERS["oi_impulse_clip"],
                        DEFAULT_PARAMETERS["oi_impulse_clip"],
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
            raw_long_open_pressure = (
                max(raw_direction, 0.0)
                * max(raw_oi_impulse, 0.0)
                * participation
            )
            raw_short_open_pressure = (
                max(-raw_direction, 0.0)
                * max(raw_oi_impulse, 0.0)
                * participation
            )
            raw_strength = float(
                np.clip(
                    abs(raw_direction)
                    * abs(raw_oi_impulse)
                    * participation
                    * DEFAULT_PARAMETERS["strength_scale"],
                    0.0,
                    100.0,
                )
            )
            raw_state = classify_main_force_mirror_futures_state(
                raw_direction,
                raw_oi_impulse,
            )
            if raw_state in ("long_build", "short_cover"):
                raw_signed_score = raw_strength
            elif raw_state in ("short_build", "long_liquidation"):
                raw_signed_score = -raw_strength
            elif raw_direction == 0.0:
                raw_signed_score = 0.0
            else:
                raw_signed_score = float(
                    np.copysign(
                        min(
                            raw_strength,
                            DEFAULT_PARAMETERS["turnover_display_cap"],
                        ),
                        raw_direction,
                    )
                )

            digits = DEFAULT_PARAMETERS["round_digits"]
            state[output_index] = raw_state
            signed_score[output_index] = round_half_away_from_zero_binary64(
                raw_signed_score, digits
            )
            price_impulse[output_index] = round_half_away_from_zero_binary64(
                raw_price_impulse, digits
            )
            clv[output_index] = round_half_away_from_zero_binary64(raw_clv, digits)
            volume_ratio[output_index] = round_half_away_from_zero_binary64(
                raw_volume_ratio, digits
            )
            delta_oi[output_index] = round_half_away_from_zero_binary64(
                raw_delta_oi, digits
            )
            oi_impulse[output_index] = round_half_away_from_zero_binary64(
                raw_oi_impulse, digits
            )
            direction[output_index] = round_half_away_from_zero_binary64(
                raw_direction, digits
            )
            range_position[output_index] = round_half_away_from_zero_binary64(
                raw_range_position, digits
            )
            long_open_pressure[output_index] = round_half_away_from_zero_binary64(
                raw_long_open_pressure, digits
            )
            short_open_pressure[output_index] = round_half_away_from_zero_binary64(
                raw_short_open_pressure, digits
            )
            strength[output_index] = round_half_away_from_zero_binary64(
                raw_strength, digits
            )

            prior_start = output_index - 10
            if block_index >= 30 and bool(np.all(state_ready[prior_start:output_index])):
                caution_ready[output_index] = True
                caution_reason[output_index] = None
        index = end


def _wilder_atr14(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
) -> np.ndarray:
    """Return exact Wilder ATR14 with an SMA seed and reset on invalid input."""

    if high.ndim != 1 or low.ndim != 1 or close.ndim != 1:
        raise ValueError("ATR inputs must be one-dimensional")
    if not (len(high) == len(low) == len(close)):
        raise ValueError("ATR input lengths must match")

    output = np.full(len(close), np.nan, dtype=float)
    previous_close: float | None = None
    previous_atr: float | None = None
    seed: list[float] = []
    for index, (high_value, low_value, close_value) in enumerate(
        zip(high, low, close, strict=True)
    ):
        if not all(np.isfinite(value) for value in (high_value, low_value, close_value)):
            previous_close = None
            previous_atr = None
            seed = []
            continue
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
            if len(seed) < 14:
                continue
            previous_atr = float(np.mean(seed[-14:]))
        else:
            previous_atr = (previous_atr * 13.0 + true_range) / 14.0
        output[index] = previous_atr
    return output


def _ema_sma_seed(values: np.ndarray, period: int) -> np.ndarray:
    """Return an EMA aligned to values, using the first finite window as seed."""

    if values.ndim != 1:
        raise ValueError("EMA input must be one-dimensional")
    if isinstance(period, bool) or not isinstance(period, int) or period <= 0:
        raise ValueError("period must be a positive integer")

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


def _require_same_length(**arrays: Sequence[Any]) -> None:
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
        number = float(value)
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


def _parse_timestamp(value: object) -> int | None:
    if isinstance(value, np.datetime64):
        if np.isnat(value):
            return None
        return int(value.astype("datetime64[us]").astype(np.int64))
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            parsed = datetime.fromisoformat(stripped.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    try:
        normalized = (
            parsed.replace(tzinfo=UTC)
            if parsed.tzinfo is None
            else parsed.astimezone(UTC)
        )
        return int(normalized.timestamp() * 1_000_000)
    except (OverflowError, OSError, ValueError):
        return None
