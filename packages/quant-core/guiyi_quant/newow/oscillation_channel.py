"""HHV/LLV channel and scored oscillation state machine observed on the page."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any, cast

from .models import NewowDailyBar


CHANNEL_FORMULA_VERSION = "newow_hhv_llv_channel_page_v1"
OSCILLATION_FORMULA_VERSION = "newow_oscillation_hhv_llv10_page_v1"
_OSCILLATION_PERIOD = 10


class OscillationAction(StrEnum):
    BUILD = "BUILD"
    CLEAR = "CLEAR"


@dataclass(frozen=True, slots=True)
class ChannelPoint:
    upper: Decimal
    lower: Decimal
    width: Decimal
    close_position: Decimal | None
    period: int
    formula_version: str = CHANNEL_FORMULA_VERSION


@dataclass(frozen=True, slots=True)
class OscillationScore:
    volume_score: int
    body_score: int
    penetration_score: int
    confirm_score: int
    volume_ratio: float
    body_ratio: float
    penetration_ratio: float
    confirmed: bool = False


@dataclass(frozen=True, slots=True)
class OscillationSignal:
    action: OscillationAction
    price: Decimal
    score: int
    break_label: str
    facts: OscillationScore
    formula_version: str = OSCILLATION_FORMULA_VERSION


@dataclass(frozen=True, slots=True)
class OscillationState:
    highs: tuple[Decimal, ...] = ()
    lows: tuple[Decimal, ...] = ()
    volumes: tuple[int, ...] = ()
    history_count: int = 0
    holding: bool = False
    physical_contract: str | None = None
    segment_id: str | None = None


@dataclass(frozen=True, slots=True)
class OscillationStepResult:
    state: OscillationState
    channel: ChannelPoint | None
    signals: tuple[OscillationSignal, ...]
    diagnostics: tuple[str, ...] = ()


def _valid_period(period: object) -> bool:
    return type(period) is int and 5 <= period <= 120


def _channel_point(
    bar: NewowDailyBar,
    highs: tuple[Decimal, ...],
    lows: tuple[Decimal, ...],
    period: int,
) -> ChannelPoint:
    upper = max(highs[-period:])
    lower = min(lows[-period:])
    width = upper - lower
    position = None if width == 0 else (bar.close - lower) / width
    return ChannelPoint(upper, lower, width, position, period)


def calculate_channel_series(
    bars: tuple[NewowDailyBar, ...], *, period: int
) -> tuple[ChannelPoint, ...]:
    if not _valid_period(period):
        raise ValueError("NEWOW_CHANNEL_PERIOD_INVALID")
    identities = {(bar.physical_contract, bar.segment_id) for bar in bars}
    if len(identities) > 1:
        raise ValueError("NEWOW_CHANNEL_MIXED_SEGMENT")
    highs: tuple[Decimal, ...] = ()
    lows: tuple[Decimal, ...] = ()
    result: list[ChannelPoint] = []
    for bar in bars:
        highs = (highs + (bar.high,))[-period:]
        lows = (lows + (bar.low,))[-period:]
        result.append(_channel_point(bar, highs, lows, period))
    return tuple(result)


def _valid_state(state: object) -> bool:
    if not isinstance(state, OscillationState):
        return False
    if not isinstance(state.holding, bool):
        return False
    if any(
        len(window) != state.history_count
        for window in (state.highs, state.lows, state.volumes)
    ):
        return False
    if not 0 <= state.history_count <= _OSCILLATION_PERIOD:
        return False
    if not all(
        isinstance(value, Decimal) and value.is_finite() and value > 0
        for values in (state.highs, state.lows)
        for value in values
    ):
        return False
    if not all(type(value) is int and value >= 0 for value in state.volumes):
        return False
    if any(low > high for low, high in zip(state.lows, state.highs, strict=True)):
        return False
    if state.history_count == 0:
        return state == OscillationState()
    return (
        isinstance(state.physical_contract, str)
        and bool(state.physical_contract)
        and isinstance(state.segment_id, str)
        and bool(state.segment_id)
    )


def _score(value: float, upper: float, lower: float, *, strict: bool = False) -> int:
    upper_hit = value > upper if strict else value >= upper
    lower_hit = value > lower if strict else value >= lower
    return 2 if upper_hit else 1 if lower_hit else 0


def _signal(
    bar: NewowDailyBar,
    channel: ChannelPoint,
    volumes: tuple[int, ...],
    action: OscillationAction,
) -> OscillationSignal:
    average_volume = sum(reversed(volumes)) / len(volumes)
    volume_ratio = bar.volume / average_volume if average_volume > 0 else 1.0
    open_value, high_value, low_value, close_value = (
        float(value) for value in (bar.open, bar.high, bar.low, bar.close)
    )
    # The observed page scores IEEE-754 browser numbers. Prices remain Decimal
    # facts, while these non-price ratios intentionally preserve that boundary.
    body_ratio = abs(close_value - open_value) / max(high_value - low_value, 0.001)
    if action is OscillationAction.CLEAR:
        penetration_ratio = abs(close_value - float(channel.upper)) / float(
            channel.upper
        )
        price = bar.high
    else:
        penetration_ratio = abs(float(channel.lower) - close_value) / float(
            channel.lower
        )
        price = bar.low
    volume_score = _score(volume_ratio, 1.5, 1.0)
    body_score = _score(body_ratio, 0.6, 0.3, strict=True)
    penetration_score = _score(penetration_ratio, 0.03, 0.01, strict=True)
    score = volume_score + body_score + penetration_score
    facts = OscillationScore(
        volume_score,
        body_score,
        penetration_score,
        0,
        volume_ratio,
        body_ratio,
        penetration_ratio,
    )
    return OscillationSignal(
        action,
        price,
        score,
        "⚠真突破" if score >= 4 else "⚠假突破",
        facts,
    )


def step_oscillation(
    state: OscillationState, bar: NewowDailyBar
) -> OscillationStepResult:
    if not _valid_state(state):
        return OscillationStepResult(
            OscillationState(), None, (), ("NEWOW_OSCILLATION_STATE_INVALID",)
        )
    identity = (state.physical_contract, state.segment_id)
    incoming = (bar.physical_contract, bar.segment_id)
    if identity != (None, None) and identity != incoming:
        state = OscillationState()
    highs = (state.highs + (bar.high,))[-_OSCILLATION_PERIOD:]
    lows = (state.lows + (bar.low,))[-_OSCILLATION_PERIOD:]
    volumes = (state.volumes + (bar.volume,))[-_OSCILLATION_PERIOD:]
    history_count = min(state.history_count + 1, _OSCILLATION_PERIOD)
    channel = _channel_point(bar, highs, lows, _OSCILLATION_PERIOD)
    holding = state.holding
    signals: list[OscillationSignal] = []
    if history_count == _OSCILLATION_PERIOD:
        if holding and bar.high >= channel.upper:
            signals.append(_signal(bar, channel, volumes, OscillationAction.CLEAR))
            holding = False
        if not holding and bar.low <= channel.lower:
            signals.append(_signal(bar, channel, volumes, OscillationAction.BUILD))
            holding = True
    next_state = OscillationState(
        highs,
        lows,
        volumes,
        history_count,
        holding,
        bar.physical_contract,
        bar.segment_id,
    )
    if not bar.observation_eligible:
        signals = []
    return OscillationStepResult(next_state, channel, tuple(signals))


def calculate_oscillation_series(
    bars: tuple[NewowDailyBar, ...],
) -> tuple[OscillationStepResult, ...]:
    state = OscillationState()
    result: list[OscillationStepResult] = []
    for bar in bars:
        step = step_oscillation(state, bar)
        result.append(step)
        state = step.state
    return tuple(result)


def restore_oscillation_state(payload: Mapping[str, object]) -> OscillationState:
    try:
        state = OscillationState(**cast(dict[str, Any], dict(payload)))
    except (TypeError, ValueError):
        return OscillationState()
    return state if _valid_state(state) else OscillationState()
