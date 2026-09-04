"""Causal, bounded page-parity primitive for Newow's 4/7/11 cycle overlay."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from math import isfinite

from .models import NewowDailyBar


MAGIC11_FORMULA_VERSION = "newow_magic11_page_v1"
_HISTORY_LIMIT = 60
_INACTIVE_AGE = 12


class Magic11Anchor(StrEnum):
    LOW = "LOW"
    HIGH = "HIGH"


class Magic11Label(StrEnum):
    HIGH4 = "4高"
    LOW7 = "7低"
    TURN11 = "11变"
    LOW4 = "4低"
    HIGH7 = "7高"


@dataclass(frozen=True, slots=True)
class Magic11State:
    highs: tuple[float, ...] = ()
    lows: tuple[float, ...] = ()
    history_count: int = 0
    low_age: int | None = None
    high_age: int | None = None
    physical_contract: str | None = None
    segment_id: str | None = None


@dataclass(frozen=True, slots=True)
class Magic11Marker:
    label: Magic11Label
    price: Decimal
    position: str
    color_token: str
    anchor: Magic11Anchor
    age: int
    formula_version: str = MAGIC11_FORMULA_VERSION


@dataclass(frozen=True, slots=True)
class Magic11StepResult:
    state: Magic11State
    low_point: bool
    high_point: bool
    active_anchor: Magic11Anchor | None
    age: int | None
    marker: Magic11Marker | None
    count_line_color: str | None


def initial_magic11_state() -> Magic11State:
    return Magic11State()


def _unavailable() -> Magic11StepResult:
    return Magic11StepResult(
        initial_magic11_state(), False, False, None, None, None, None
    )


def _valid_state(state: object) -> bool:
    if not isinstance(state, Magic11State):
        return False
    if len(state.highs) != len(state.lows) or len(state.highs) != state.history_count:
        return False
    if not 0 <= state.history_count <= _HISTORY_LIMIT:
        return False
    if not all(
        isfinite(value) and value > 0.0
        for values in (state.highs, state.lows)
        for value in values
    ):
        return False
    if any(low > high for low, high in zip(state.lows, state.highs, strict=True)):
        return False
    for age in (state.low_age, state.high_age):
        if age is not None and (type(age) is not int or not 0 <= age <= _INACTIVE_AGE):
            return False
    if state.history_count == 0:
        return (
            state.low_age is None
            and state.high_age is None
            and state.physical_contract is None
            and state.segment_id is None
        )
    return (
        isinstance(state.physical_contract, str)
        and bool(state.physical_contract)
        and isinstance(state.segment_id, str)
        and bool(state.segment_id)
        and (state.low_age is not None or state.high_age is not None)
    )


def _advance_age(age: int | None) -> int | None:
    return None if age is None else min(age + 1, _INACTIVE_AGE)


def _is_low_point(lows: tuple[float, ...], prior_count: int) -> bool:
    current = lows[-1]
    if current != min(lows[-_HISTORY_LIMIT:]):
        return False
    ref3 = min(lows[-6:-3]) if prior_count >= 3 else float("inf")
    ref1 = min(lows[-4:-1]) if prior_count >= 1 else float("inf")
    return ref3 > current and ref1 > current


def _is_high_point(highs: tuple[float, ...], prior_count: int) -> bool:
    current = highs[-1]
    if current != max(highs[-_HISTORY_LIMIT:]):
        return False
    ref3 = max(highs[-6:-3]) if prior_count >= 3 else -float("inf")
    ref1 = max(highs[-4:-1]) if prior_count >= 1 else -float("inf")
    return ref3 < current and ref1 < current


def _marker(
    bar: NewowDailyBar, anchor: Magic11Anchor, age: int
) -> Magic11Marker | None:
    definitions = {
        (Magic11Anchor.LOW, 4): (
            Magic11Label.HIGH4,
            bar.high,
            "high",
            "newow-magic11-green",
        ),
        (Magic11Anchor.LOW, 7): (
            Magic11Label.LOW7,
            bar.low,
            "low",
            "newow-magic11-yellow",
        ),
        (Magic11Anchor.LOW, 11): (
            Magic11Label.TURN11,
            bar.high,
            "high",
            "newow-magic11-magenta",
        ),
        (Magic11Anchor.HIGH, 4): (
            Magic11Label.LOW4,
            bar.low,
            "low",
            "newow-magic11-red",
        ),
        (Magic11Anchor.HIGH, 7): (
            Magic11Label.HIGH7,
            bar.high,
            "high",
            "newow-magic11-green",
        ),
        (Magic11Anchor.HIGH, 11): (
            Magic11Label.TURN11,
            bar.high,
            "high",
            "newow-magic11-magenta",
        ),
    }
    definition = definitions.get((anchor, age))
    if definition is None:
        return None
    label, price, position, color = definition
    return Magic11Marker(label, price, position, color, anchor, age)


def step_magic11(state: Magic11State, bar: NewowDailyBar) -> Magic11StepResult:
    """Advance one completed D1 bar; a physical-contract change starts a fresh cycle."""

    if not _valid_state(state):
        return _unavailable()
    identity = (state.physical_contract, state.segment_id)
    incoming = (bar.physical_contract, bar.segment_id)
    if identity != (None, None) and identity != incoming:
        state = initial_magic11_state()
    high = float(bar.high)
    low = float(bar.low)
    if not isfinite(high) or not isfinite(low) or low <= 0.0 or high < low:
        return _unavailable()
    highs = (state.highs + (high,))[-_HISTORY_LIMIT:]
    lows = (state.lows + (low,))[-_HISTORY_LIMIT:]
    low_point = _is_low_point(lows, state.history_count)
    high_point = _is_high_point(highs, state.history_count)
    low_age = 0 if low_point else _advance_age(state.low_age)
    high_age = 0 if high_point else _advance_age(state.high_age)
    next_state = Magic11State(
        highs=highs,
        lows=lows,
        history_count=min(state.history_count + 1, _HISTORY_LIMIT),
        low_age=low_age,
        high_age=high_age,
        physical_contract=bar.physical_contract,
        segment_id=bar.segment_id,
    )
    if low_age is None and high_age is None:
        return Magic11StepResult(
            next_state, low_point, high_point, None, None, None, None
        )
    use_low = low_age is not None and (high_age is None or low_age <= high_age)
    active_anchor = Magic11Anchor.LOW if use_low else Magic11Anchor.HIGH
    age = low_age if use_low else high_age
    assert age is not None
    marker = _marker(bar, active_anchor, age) if bar.observation_eligible else None
    color = None
    if bar.observation_eligible and age <= 11:
        color = "newow-magic11-yellow" if use_low else "newow-magic11-red"
    return Magic11StepResult(
        next_state, low_point, high_point, active_anchor, age, marker, color
    )


def calculate_magic11_series(
    bars: tuple[NewowDailyBar, ...],
) -> tuple[Magic11StepResult, ...]:
    state = initial_magic11_state()
    results: list[Magic11StepResult] = []
    for bar in bars:
        result = step_magic11(state, bar)
        results.append(result)
        state = result.state
    return tuple(results)
