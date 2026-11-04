"""Position kernel 1.1.1 trueup; current product kernel, not an executable fill.

The frozen HHV kernel remains the source of historical research/experiments.
Source comparisons use binary64; original price facts remain Decimal.
"""
from collections.abc import Mapping
from dataclasses import dataclass, replace
from decimal import Decimal
from math import isfinite

from .models import NewowDailyBar
from .oscillation_channel import (
    ChannelPoint, OscillationAction, OscillationSignal, _channel_point, _signal,
    CHANNEL_FORMULA_VERSION as CHANNEL_FORMULA_VERSION,
)

OSCILLATION_FORMULA_VERSION = 'newow_oscillation_trueup_kernel111_v1'
STATE_VERSION = 'newow_oscillation_trueup_state_v1'
SOURCE_SHA256 = 'c6b5f1f634d87af29d7676b3f1a7ab6cdbc28c1ca1229ef753779fdb954f6036'


@dataclass(frozen=True, slots=True)
class TrueupSignal(OscillationSignal):
    reference_price: Decimal | None = None
    true_up: bool | None = None


@dataclass(frozen=True, slots=True)
class TrueupState:
    highs: tuple[Decimal, ...] = ()
    lows: tuple[Decimal, ...] = ()
    volumes: tuple[int, ...] = ()
    history_count: int = 0
    holding: bool = False
    physical_contract: str | None = None
    segment_id: str | None = None
    count: int = 0
    previous_close: Decimal | None = None
    ranges: tuple[float | None, ...] = ()
    pending_level: Decimal | None = None
    pos_true_up: bool = False
    version: str = STATE_VERSION


OscillationState = TrueupState


@dataclass(frozen=True, slots=True)
class OscillationStepResult:
    state: TrueupState
    channel: ChannelPoint | None
    signals: tuple[TrueupSignal, ...]
    diagnostics: tuple[str, ...] = ()


def _valid(state):
    if not isinstance(state, TrueupState) or state.version != STATE_VERSION:
        return False
    if type(state.count) is not int or state.count < 0 or type(state.history_count) is not int:
        return False
    if state.history_count != min(10, state.count) or any(not isinstance(v, tuple) or len(v) != state.history_count for v in (state.highs, state.lows, state.volumes)):
        return False
    if not isinstance(state.ranges, tuple) or len(state.ranges) != min(14, state.count):
        return False
    prices = (*state.highs, *state.lows, *(x for x in (state.previous_close, state.pending_level) if x is not None))
    if any(not isinstance(x, Decimal) or not x.is_finite() or x <= 0 for x in prices):
        return False
    if any(type(x) is not int or x < 0 for x in state.volumes):
        return False
    if any(x is not None and (not isinstance(x, float) or not isfinite(x) or x < 0) for x in state.ranges):
        return False
    if any(lo > hi for lo, hi in zip(state.lows, state.highs, strict=True)):
        return False
    if type(state.holding) is not bool or type(state.pos_true_up) is not bool or (not state.holding and (state.pending_level is not None or state.pos_true_up)):
        return False
    if not state.count:
        return state == TrueupState()
    return bool(state.physical_contract and state.segment_id and state.previous_close is not None)


def restore_oscillation_state(payload: Mapping[str, object]) -> TrueupState:
    if payload.get('version') != STATE_VERSION:
        return TrueupState()
    try:
        state = TrueupState(**dict(payload))
        return state if _valid(state) else TrueupState()
    except (TypeError, ValueError):
        return TrueupState()


def _event(bar, channel, volumes, action, reference, true_up=None):
    scored_channel = replace(channel, upper=reference) if action is OscillationAction.CLEAR else channel
    signal = _signal(bar, scored_channel, volumes, action)
    label = ('⚠真突破' if true_up else '⚠假突破') if true_up is not None else signal.break_label
    return TrueupSignal(signal.action, signal.price, signal.score, label, signal.facts,
                        OSCILLATION_FORMULA_VERSION, reference, true_up)


def step_oscillation(state: TrueupState, bar: NewowDailyBar) -> OscillationStepResult:
    if not _valid(state):
        return OscillationStepResult(TrueupState(), None, (), ('NEWOW_OSCILLATION_STATE_INVALID',))
    if state.count and (state.physical_contract, state.segment_id) != (bar.physical_contract, bar.segment_id):
        state = TrueupState()
    highs, lows, volumes = (state.highs + (bar.high,))[-10:], (state.lows + (bar.low,))[-10:], (state.volumes + (bar.volume,))[-10:]
    channel = _channel_point(bar, highs, lows, 10)
    h, lo, close = float(bar.high), float(bar.low), float(bar.close)
    pc = float(state.previous_close) if state.previous_close is not None else None
    tr = max(h - lo, abs(h - pc), abs(lo - pc)) if pc is not None else None
    ranges = (state.ranges + (tr,))[-14:]
    atr = None
    if state.count >= 14:
        valid = [v for v in ranges if v is not None]
        if len(valid) >= 5:
            total = 0.0
            for value in valid:
                total += value
            atr = total / len(valid)
    holding, pending, confirmed = state.holding, state.pending_level, state.pos_true_up
    signals = []
    sold = False
    if len(highs) == 10:
        if holding and pending is not None:
            level = float(pending)
            buffer = min(max(.3 * atr if atr is not None and atr > 0 else .02 * level, .0015 * level), .02 * level)
            reference, pending = pending, None
            if close >= level + buffer:
                confirmed = True
            else:
                signals.append(_event(bar, channel, volumes, OscillationAction.CLEAR, reference, False))
                holding, confirmed = False, False
            sold = True  # also suppress ordinary HHV branch after confirmation
        if holding and not sold and bar.high >= channel.upper:
            previous_high = max(state.highs) if state.history_count == 10 else None
            if previous_high is not None and h > float(previous_high) and close > float(previous_high):
                pending = previous_high
            else:
                signals.append(_event(bar, channel, volumes, OscillationAction.CLEAR, channel.upper, True if confirmed else None))
                holding, confirmed, sold = False, False, True
        if not holding and not sold and bar.low <= channel.lower:
            confirmed = False
            signals.append(_event(bar, channel, volumes, OscillationAction.BUILD, channel.lower))
            holding = True
    next_state = TrueupState(highs, lows, volumes, min(10, state.count + 1), holding,
                             bar.physical_contract, bar.segment_id, state.count + 1,
                             bar.close, ranges, pending, confirmed)
    return OscillationStepResult(next_state, channel, tuple(signals) if bar.observation_eligible else ())


def calculate_oscillation_series(bars):
    state, result = TrueupState(), []
    for bar in bars:
        step = step_oscillation(state, bar)
        result.append(step)
        state = step.state
    return tuple(result)
