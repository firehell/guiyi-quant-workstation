from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal

from .atr import initial_atr_state, step_atr
from .models import AtrState


RANGE_DETECTOR_LUX_CODE = "range_detector_lux_v1"
RANGE_DETECTOR_LUX_VERSION = "v1"
RANGE_DETECTOR_LUX_POLICY_ID = "range_detector_lux_v1"

RangeDetectorState = Literal["intact", "broken_up", "broken_down"]
RangeDetectorTransitionKind = Literal[
    "confirmed",
    "revised",
    "broken_up",
    "broken_down",
    "invalid_reset",
]


@dataclass(frozen=True, slots=True)
class RangeDetectorLuxParameters:
    minimum_range_length: int = 20
    range_width_atr_multiplier: float = 1.0
    range_atr_length: int = 500
    round_digits: int = 6


@dataclass(frozen=True, slots=True)
class RangeDetectorSnapshot:
    formula_version: str
    policy_id: str
    range_id: str
    revision: int
    visual_start_at: str
    confirmed_at: str
    detection_right_at: str
    levels_active_from: str
    initial_upper: float
    initial_lower: float
    current_upper: float
    current_lower: float
    current_mid: float
    state: RangeDetectorState
    broken_at: str | None
    merged_count: int
    candidate_valid: bool
    source_bar_end: str
    source_trading_day: str | None
    source_identity: str


@dataclass(frozen=True, slots=True)
class RangeDetectorVisualRange:
    range_id: str
    revision: int
    visual_start_at: str
    detection_right_at: str
    levels_active_from: str
    levels_active_until: str | None
    confirmed_at: str
    upper: float
    lower: float
    mid: float
    state: RangeDetectorState
    broken_at: str | None


@dataclass(frozen=True, slots=True)
class RangeDetectorTransition:
    kind: RangeDetectorTransitionKind
    range_id: str | None
    revision: int | None
    at: str


@dataclass(frozen=True, slots=True)
class RangeDetectorPoint:
    bar_end: str
    ready: bool
    valid: bool
    reason: str | None
    snapshot: RangeDetectorSnapshot | None
    transition: RangeDetectorTransition | None


@dataclass(frozen=True, slots=True)
class RangeDetectorLuxState:
    parameters: RangeDetectorLuxParameters
    source_identity: str
    atr: AtrState
    index: int
    close_window: tuple[tuple[str, str | None, float], ...]
    previous_candidate_valid: bool
    active_snapshot: RangeDetectorSnapshot | None
    active_detection_right_index: int | None
    last_bar_end: str | None


@dataclass(frozen=True, slots=True)
class RangeDetectorSeries:
    indicator_code: str
    indicator_version: str
    policy_id: str
    parameters: RangeDetectorLuxParameters
    source_identity: str
    points: tuple[RangeDetectorPoint, ...]
    ranges: tuple[RangeDetectorVisualRange, ...]


def initial_range_detector_lux_state(
    *,
    source_identity: str,
    minimum_range_length: int = 20,
    range_width_atr_multiplier: float = 1.0,
    range_atr_length: int = 500,
    round_digits: int = 6,
) -> RangeDetectorLuxState:
    parameters = RangeDetectorLuxParameters(
        minimum_range_length=minimum_range_length,
        range_width_atr_multiplier=range_width_atr_multiplier,
        range_atr_length=range_atr_length,
        round_digits=round_digits,
    )
    _validate_parameters(parameters, source_identity)
    return RangeDetectorLuxState(
        parameters=parameters,
        source_identity=source_identity,
        atr=initial_atr_state(
            range_atr_length,
            smoothing_policy="wilder_sma_seed",
            round_digits=round_digits,
        ),
        index=-1,
        close_window=(),
        previous_candidate_valid=False,
        active_snapshot=None,
        active_detection_right_index=None,
        last_bar_end=None,
    )


def step_range_detector_lux(
    state: RangeDetectorLuxState,
    *,
    high: float | int | None,
    low: float | int | None,
    close: float | int | None,
    bar_end: str,
    trading_day: str | None = None,
) -> tuple[RangeDetectorLuxState, RangeDetectorPoint]:
    """Advance a causal Range Detector Lux V1 state by one completed bar."""

    timestamp = _parse_bar_end(bar_end)
    if state.last_bar_end is not None and timestamp <= _parse_bar_end(state.last_bar_end):
        raise ValueError("bar_end values must be strictly increasing")

    next_index = state.index + 1
    high_value = _finite_float(high)
    low_value = _finite_float(low)
    close_value = _finite_float(close)
    input_valid = (
        high_value is not None
        and low_value is not None
        and close_value is not None
        and low_value <= close_value <= high_value
    )
    atr, atr_point = step_atr(
        state.atr,
        high=high_value if input_valid else None,
        low=low_value if input_valid else None,
        close=close_value if input_valid else None,
        bar_end=bar_end,
    )
    if not input_valid:
        invalid_transition = RangeDetectorTransition(
            kind="invalid_reset",
            range_id=None,
            revision=None,
            at=bar_end,
        )
        return (
            replace(
                state,
                atr=atr,
                index=next_index,
                close_window=(),
                previous_candidate_valid=False,
                active_snapshot=None,
                active_detection_right_index=None,
                last_bar_end=bar_end,
            ),
            RangeDetectorPoint(
                bar_end=bar_end,
                ready=True,
                valid=False,
                reason="input_invalid",
                snapshot=None,
                transition=invalid_transition,
            ),
        )

    assert close_value is not None
    close_window = (
        *state.close_window,
        (bar_end, trading_day, close_value),
    )[-(state.parameters.minimum_range_length + 1) :]
    ready = atr_point.ready and len(close_window) == state.parameters.minimum_range_length + 1
    if not ready:
        return (
            replace(
                state,
                atr=atr,
                index=next_index,
                close_window=close_window,
                previous_candidate_valid=False,
                last_bar_end=bar_end,
            ),
            RangeDetectorPoint(
                bar_end=bar_end,
                ready=False,
                valid=True,
                reason="warming_up",
                snapshot=None,
                transition=None,
            ),
        )

    assert atr.previous_atr is not None
    candidate_window = close_window[-state.parameters.minimum_range_length :]
    center = sum(value for _, _, value in candidate_window) / len(candidate_window)
    width = atr.previous_atr * state.parameters.range_width_atr_multiplier
    candidate_valid = all(
        abs(value - center) <= width for _, _, value in candidate_window
    )
    snapshot = state.active_snapshot
    active_detection_right_index = state.active_detection_right_index
    transition: RangeDetectorTransition | None = None

    if candidate_valid and not state.previous_candidate_valid:
        candidate_upper = _round(center + width, state.parameters.round_digits)
        candidate_lower = _round(center - width, state.parameters.round_digits)
        visual_start_at = close_window[0][0]
        visual_start_index = next_index - state.parameters.minimum_range_length
        if (
            snapshot is not None
            and active_detection_right_index is not None
            and visual_start_index <= active_detection_right_index
        ):
            current_upper = max(snapshot.current_upper, candidate_upper)
            current_lower = min(snapshot.current_lower, candidate_lower)
            snapshot = RangeDetectorSnapshot(
                formula_version=RANGE_DETECTOR_LUX_CODE,
                policy_id=RANGE_DETECTOR_LUX_POLICY_ID,
                range_id=snapshot.range_id,
                revision=snapshot.revision + 1,
                visual_start_at=snapshot.visual_start_at,
                confirmed_at=bar_end,
                detection_right_at=bar_end,
                levels_active_from=bar_end,
                initial_upper=snapshot.initial_upper,
                initial_lower=snapshot.initial_lower,
                current_upper=current_upper,
                current_lower=current_lower,
                current_mid=_round(
                    (current_upper + current_lower) / 2,
                    state.parameters.round_digits,
                ),
                state="intact",
                broken_at=None,
                merged_count=snapshot.merged_count + 1,
                candidate_valid=True,
                source_bar_end=bar_end,
                source_trading_day=trading_day,
                source_identity=state.source_identity,
            )
            transition = RangeDetectorTransition(
                kind="revised",
                range_id=snapshot.range_id,
                revision=snapshot.revision,
                at=bar_end,
            )
        else:
            range_id = _range_id(state.source_identity, bar_end)
            snapshot = RangeDetectorSnapshot(
                formula_version=RANGE_DETECTOR_LUX_CODE,
                policy_id=RANGE_DETECTOR_LUX_POLICY_ID,
                range_id=range_id,
                revision=1,
                visual_start_at=visual_start_at,
                confirmed_at=bar_end,
                detection_right_at=bar_end,
                levels_active_from=bar_end,
                initial_upper=candidate_upper,
                initial_lower=candidate_lower,
                current_upper=candidate_upper,
                current_lower=candidate_lower,
                current_mid=_round(center, state.parameters.round_digits),
                state="intact",
                broken_at=None,
                merged_count=0,
                candidate_valid=True,
                source_bar_end=bar_end,
                source_trading_day=trading_day,
                source_identity=state.source_identity,
            )
            transition = RangeDetectorTransition(
                kind="confirmed",
                range_id=range_id,
                revision=1,
                at=bar_end,
            )
        active_detection_right_index = next_index
    elif candidate_valid and snapshot is not None:
        snapshot = replace(
            snapshot,
            detection_right_at=bar_end,
            candidate_valid=True,
            source_bar_end=bar_end,
            source_trading_day=trading_day,
        )
        active_detection_right_index = next_index
    elif snapshot is not None:
        snapshot = replace(
            snapshot,
            candidate_valid=False,
            source_bar_end=bar_end,
            source_trading_day=trading_day,
        )

    if snapshot is not None and snapshot.state == "intact":
        if close_value > snapshot.current_upper:
            snapshot = replace(snapshot, state="broken_up", broken_at=bar_end)
            transition = RangeDetectorTransition(
                kind="broken_up",
                range_id=snapshot.range_id,
                revision=snapshot.revision,
                at=bar_end,
            )
        elif close_value < snapshot.current_lower:
            snapshot = replace(snapshot, state="broken_down", broken_at=bar_end)
            transition = RangeDetectorTransition(
                kind="broken_down",
                range_id=snapshot.range_id,
                revision=snapshot.revision,
                at=bar_end,
            )

    return (
        replace(
            state,
            atr=atr,
            index=next_index,
            close_window=close_window,
            previous_candidate_valid=candidate_valid,
            active_snapshot=snapshot,
            active_detection_right_index=active_detection_right_index,
            last_bar_end=bar_end,
        ),
        RangeDetectorPoint(
            bar_end=bar_end,
            ready=True,
            valid=True,
            reason=None,
            snapshot=snapshot,
            transition=transition,
        ),
    )


def range_detector_lux_series(
    highs: Sequence[float | int | None],
    lows: Sequence[float | int | None],
    closes: Sequence[float | int | None],
    *,
    bar_ends: Sequence[str],
    source_identity: str,
    trading_days: Sequence[str | None] | None = None,
    minimum_range_length: int = 20,
    range_width_atr_multiplier: float = 1.0,
    range_atr_length: int = 500,
    round_digits: int = 6,
) -> RangeDetectorSeries:
    if len(highs) != len(lows) or len(highs) != len(closes):
        raise ValueError("highs, lows, and closes length must match")
    if len(bar_ends) != len(highs):
        raise ValueError("bar_ends length must match highs length")
    if trading_days is not None and len(trading_days) != len(highs):
        raise ValueError("trading_days length must match highs length")

    state = initial_range_detector_lux_state(
        source_identity=source_identity,
        minimum_range_length=minimum_range_length,
        range_width_atr_multiplier=range_width_atr_multiplier,
        range_atr_length=range_atr_length,
        round_digits=round_digits,
    )
    points: list[RangeDetectorPoint] = []
    for index, (high, low, close, bar_end) in enumerate(
        zip(highs, lows, closes, bar_ends, strict=True)
    ):
        state, point = step_range_detector_lux(
            state,
            high=high,
            low=low,
            close=close,
            bar_end=bar_end,
            trading_day=None if trading_days is None else trading_days[index],
        )
        points.append(point)

    return RangeDetectorSeries(
        indicator_code=RANGE_DETECTOR_LUX_CODE,
        indicator_version=RANGE_DETECTOR_LUX_VERSION,
        policy_id=RANGE_DETECTOR_LUX_POLICY_ID,
        parameters=state.parameters,
        source_identity=source_identity,
        points=tuple(points),
        ranges=_visual_ranges(points),
    )


def _visual_ranges(
    points: Sequence[RangeDetectorPoint],
) -> tuple[RangeDetectorVisualRange, ...]:
    snapshots: dict[tuple[str, int], RangeDetectorSnapshot] = {}
    order: list[tuple[str, int]] = []
    terminal_at: dict[tuple[str, int], str] = {}
    latest_key: tuple[str, int] | None = None

    for point in points:
        if point.transition is not None and point.transition.kind == "invalid_reset":
            if latest_key is not None:
                terminal_at.setdefault(latest_key, point.bar_end)
            latest_key = None
        snapshot = point.snapshot
        if snapshot is None:
            continue
        key = (snapshot.range_id, snapshot.revision)
        if key not in snapshots:
            if latest_key is not None and latest_key != key:
                terminal_at.setdefault(latest_key, snapshot.levels_active_from)
            order.append(key)
        snapshots[key] = snapshot
        latest_key = key

    visual_ranges: list[RangeDetectorVisualRange] = []
    for key in order:
        snapshot = snapshots[key]
        visual_ranges.append(
            RangeDetectorVisualRange(
                range_id=snapshot.range_id,
                revision=snapshot.revision,
                visual_start_at=snapshot.visual_start_at,
                detection_right_at=snapshot.detection_right_at,
                levels_active_from=snapshot.levels_active_from,
                levels_active_until=terminal_at.get(key),
                confirmed_at=snapshot.confirmed_at,
                upper=snapshot.current_upper,
                lower=snapshot.current_lower,
                mid=snapshot.current_mid,
                state=snapshot.state,
                broken_at=snapshot.broken_at,
            )
        )
    return tuple(visual_ranges)


def _validate_parameters(
    parameters: RangeDetectorLuxParameters,
    source_identity: str,
) -> None:
    if not isinstance(source_identity, str) or not source_identity.strip():
        raise ValueError("source_identity must be a non-empty string")
    if parameters.minimum_range_length < 2:
        raise ValueError("minimum_range_length must be at least 2")
    if parameters.range_atr_length <= 0:
        raise ValueError("range_atr_length must be positive")
    if (
        not math.isfinite(parameters.range_width_atr_multiplier)
        or parameters.range_width_atr_multiplier <= 0
    ):
        raise ValueError("range_width_atr_multiplier must be finite and positive")
    if parameters.round_digits < 0:
        raise ValueError("round_digits must be non-negative")


def _parse_bar_end(bar_end: str) -> datetime:
    if not isinstance(bar_end, str) or "T" not in bar_end:
        raise ValueError("bar_end must be ISO-8601")
    try:
        parsed = datetime.fromisoformat(
            f"{bar_end[:-1]}+00:00" if bar_end.endswith("Z") else bar_end
        )
    except ValueError as exc:
        raise ValueError("bar_end must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError("bar_end must be ISO-8601 with timezone")
    return parsed


def _finite_float(value: float | int | None) -> float | None:
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _round(value: float, round_digits: int) -> float:
    if not math.isfinite(value):
        raise ValueError("rounding value must be finite")
    coefficient, decimal_exponent = _canonical_decimal_components(abs(value))
    target_exponent = -round_digits
    if decimal_exponent >= target_exponent:
        rounded_coefficient = coefficient * 10 ** (
            decimal_exponent - target_exponent
        )
    else:
        divisor = 10 ** (target_exponent - decimal_exponent)
        rounded_coefficient, remainder = divmod(coefficient, divisor)
        halfway = divisor // 2
        if remainder > halfway or (
            remainder == halfway and rounded_coefficient % 2 == 1
        ):
            rounded_coefficient += 1
    if value < 0:
        rounded_coefficient = -rounded_coefficient
    rounded = float(f"{rounded_coefficient}e{-round_digits}")
    return 0.0 if rounded == 0 else rounded


def _canonical_decimal_components(value: float) -> tuple[int, int]:
    mantissa, separator, raw_exponent = str(value).lower().partition("e")
    exponent = int(raw_exponent) if separator else 0
    whole, dot, fraction = mantissa.partition(".")
    digits = f"{whole}{fraction}" if dot else whole
    return int(digits), exponent - len(fraction)


def _range_id(source_identity: str, first_confirmed_at: str) -> str:
    payload = "|".join(
        (RANGE_DETECTOR_LUX_CODE, source_identity, first_confirmed_at)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
