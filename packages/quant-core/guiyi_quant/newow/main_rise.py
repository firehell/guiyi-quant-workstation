"""Versioned page-parity composition for Newow's main-rise overlay."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from math import isfinite
from typing import Any, cast

from .escape_d123 import EscapeState, step_escape_d123
from .magic11 import (
    MAGIC11_FORMULA_VERSION,
    Magic11State,
    Magic11StepResult,
    initial_magic11_state,
    step_magic11,
)
from .models import NewowDailyBar, NewowMainMarker, TrendBandState
from .profile import NEWOW_TREND_D1_PAGE_V2


@dataclass(frozen=True, slots=True)
class MainRiseFormulaSet:
    band_formula: str
    j_reduce_formula: str
    escape_formula: str
    buy_formula: str
    magic11_formula: str


MAIN_RISE_PAGE_V1 = MainRiseFormulaSet(
    band_formula="newow_main_rise_ma35_ma45_page_v1",
    j_reduce_formula="newow_main_rise_j_reduce_page_v1",
    escape_formula="newow_escape_d123_page_v2",
    buy_formula="newow_buy_d456_page_v1",
    magic11_formula=MAGIC11_FORMULA_VERSION,
)


class MainRiseAction(StrEnum):
    BUILD = "BUILD"
    CLEAR = "CLEAR"


class MainRiseBuyKind(StrEnum):
    D4 = "D4"
    D5 = "D5"
    D6 = "D6"


@dataclass(frozen=True, slots=True)
class MainRiseBandSignal:
    action: MainRiseAction
    price: Decimal
    profit_pct: Decimal | None
    hold_bars: int | None
    formula_version: str = MAIN_RISE_PAGE_V1.band_formula


@dataclass(frozen=True, slots=True)
class MainRiseReduceSignal:
    price: Decimal
    j_value: float
    formula_version: str = MAIN_RISE_PAGE_V1.j_reduce_formula


@dataclass(frozen=True, slots=True)
class MainRiseBuyMarker:
    kind: MainRiseBuyKind
    price: Decimal
    color_token: str
    label: str = "★B"
    position: str = "low"
    formula_version: str = MAIN_RISE_PAGE_V1.buy_formula


@dataclass(frozen=True, slots=True)
class MainRiseState:
    closes: tuple[float, ...] = ()
    highs: tuple[float, ...] = ()
    lows: tuple[float, ...] = ()
    jj_values: tuple[float, ...] = ()
    history_count: int = 0
    band_state: TrendBandState | None = None
    last_buy_price: Decimal | None = None
    bars_since_buy: int | None = None
    k_value: float | None = None
    d_value: float | None = None
    j_values: tuple[float, ...] = ()
    previous_bdgd: bool = False
    previous_was_sell: bool = False
    raw20_window: tuple[float, ...] = ()
    previous_var41: float | None = None
    prior_var41: float | None = None
    escape_state: EscapeState = EscapeState((), (), (), (), None, None)
    magic11_state: Magic11State = Magic11State()
    physical_contract: str | None = None
    segment_id: str | None = None


@dataclass(frozen=True, slots=True)
class MainRiseStepResult:
    state: MainRiseState
    ma35: float | None
    ma45: float | None
    band_state: TrendBandState | None
    band_signal: MainRiseBandSignal | None
    j_value: float | None
    reduce_signal: MainRiseReduceSignal | None
    escape_markers: tuple[NewowMainMarker, ...]
    buy_markers: tuple[MainRiseBuyMarker, ...]
    magic11: Magic11StepResult
    diagnostics: tuple[str, ...] = ()


def initial_main_rise_state() -> MainRiseState:
    return MainRiseState()


def main_rise_formula_gate(formulas: MainRiseFormulaSet) -> bool:
    return formulas == MAIN_RISE_PAGE_V1


def _empty_magic() -> Magic11StepResult:
    return Magic11StepResult(
        initial_magic11_state(), False, False, None, None, None, None
    )


def _unavailable(code: str) -> MainRiseStepResult:
    return MainRiseStepResult(
        initial_main_rise_state(),
        None,
        None,
        None,
        None,
        None,
        None,
        (),
        (),
        _empty_magic(),
        (code,),
    )


def _valid_state(state: object) -> bool:
    if not isinstance(state, MainRiseState):
        return False
    windows = (state.closes, state.highs, state.lows, state.jj_values)
    if any(len(window) != state.history_count for window in windows):
        return False
    if not 0 <= state.history_count <= 120:
        return False
    if len(state.j_values) > 8 or len(state.raw20_window) > 4:
        return False
    if not all(
        isfinite(value)
        for window in (*windows, state.j_values, state.raw20_window)
        for value in window
    ):
        return False
    if any(
        low <= 0.0 or low > high
        for low, high in zip(state.lows, state.highs, strict=True)
    ):
        return False
    scalars = (state.k_value, state.d_value, state.previous_var41, state.prior_var41)
    if not all(value is None or isfinite(value) for value in scalars):
        return False
    if not isinstance(state.previous_bdgd, bool) or not isinstance(
        state.previous_was_sell, bool
    ):
        return False
    if state.bars_since_buy is not None and (
        type(state.bars_since_buy) is not int or state.bars_since_buy < 0
    ):
        return False
    if (state.last_buy_price is None) != (state.bars_since_buy is None):
        return False
    if state.last_buy_price is not None and (
        not state.last_buy_price.is_finite() or state.last_buy_price <= 0
    ):
        return False
    if state.history_count == 0:
        return state == initial_main_rise_state()
    return (
        isinstance(state.band_state, TrendBandState)
        and state.band_state is not TrendBandState.UNAVAILABLE
        and isinstance(state.escape_state, EscapeState)
        and isinstance(state.magic11_state, Magic11State)
        and isinstance(state.physical_contract, str)
        and bool(state.physical_contract)
        and isinstance(state.segment_id, str)
        and bool(state.segment_id)
    )


def _average_latest(values: tuple[float, ...], period: int) -> float:
    total = 0.0
    count = 0
    for offset in range(min(period, len(values))):
        total += values[-1 - offset]
        count += 1
    return total / count


def _round4(value: float) -> float:
    return float(f"{value:.4f}")


def _rsi(
    closes: tuple[float, ...],
    highs: tuple[float, ...],
    lows: tuple[float, ...],
    period: int,
) -> float:
    low = min(lows[-period:])
    high = max(highs[-period:])
    return 50.0 if high == low else (closes[-1] - low) / (high - low) * 100.0


def _buy_markers(
    state: MainRiseState,
    bar: NewowDailyBar,
    *,
    close: float,
    z_value: float,
    var31: float,
    var41: float,
) -> tuple[MainRiseBuyMarker, ...]:
    previous = state.previous_var41
    prior = state.prior_var41
    if previous is None:
        return ()
    hits: list[MainRiseBuyMarker] = []
    price = bar.low * Decimal("0.99")
    if (
        prior is not None
        and close > z_value
        and previous < 30.0
        and var41 > previous
        and previous < prior
    ):
        hits.append(MainRiseBuyMarker(MainRiseBuyKind.D4, price, "newow-d4-red"))
    if (
        prior is not None
        and previous < 7.0
        and var41 > previous
        and previous < prior
        and var31 < -0.1
    ):
        hits.append(MainRiseBuyMarker(MainRiseBuyKind.D5, price, "newow-d5-green"))
    if previous <= 5.0 and var41 > 5.0 and var31 < -0.3:
        hits.append(MainRiseBuyMarker(MainRiseBuyKind.D6, price, "newow-d6-blue"))
    return tuple(hits) if bar.observation_eligible else ()


def step_main_rise(
    state: MainRiseState,
    bar: NewowDailyBar,
    *,
    formulas: MainRiseFormulaSet = MAIN_RISE_PAGE_V1,
) -> MainRiseStepResult:
    if not main_rise_formula_gate(formulas):
        return _unavailable("NEWOW_MAIN_RISE_FORMULA_GATE_FAILED")
    if not _valid_state(state):
        return _unavailable("NEWOW_MAIN_RISE_STATE_INVALID")
    identity = (state.physical_contract, state.segment_id)
    incoming = (bar.physical_contract, bar.segment_id)
    if identity != (None, None) and identity != incoming:
        state = initial_main_rise_state()
    close, high, low = (float(value) for value in (bar.close, bar.high, bar.low))
    if not all(isfinite(value) and value > 0.0 for value in (close, high, low)):
        return _unavailable("NEWOW_MAIN_RISE_BAR_INVALID")
    closes = (state.closes + (close,))[-120:]
    highs = (state.highs + (high,))[-120:]
    lows = (state.lows + (low,))[-120:]
    jj_values = (state.jj_values + ((close + high + low) / 3.0,))[-120:]
    ma35 = _average_latest(jj_values, 35)
    ma45 = _average_latest(jj_values, 45)
    band_state = TrendBandState.YELLOW if ma35 >= ma45 else TrendBandState.BLUE
    transition: MainRiseAction | None = None
    if state.band_state is not None and state.band_state is not band_state:
        transition = (
            MainRiseAction.BUILD
            if band_state is TrendBandState.YELLOW
            else MainRiseAction.CLEAR
        )
    price = Decimal(str(ma45))
    next_buy_price = state.last_buy_price
    next_bars_since_buy = (
        None if state.bars_since_buy is None else state.bars_since_buy + 1
    )
    band_signal: MainRiseBandSignal | None = None
    if transition is MainRiseAction.BUILD:
        next_buy_price = price
        next_bars_since_buy = 0
        band_signal = MainRiseBandSignal(transition, price, None, None)
    elif transition is MainRiseAction.CLEAR:
        valid_buy = next_buy_price is not None and next_bars_since_buy is not None
        profit = (
            (price - next_buy_price) / next_buy_price * Decimal("100")
            if valid_buy and next_buy_price is not None
            else None
        )
        band_signal = MainRiseBandSignal(
            transition,
            price,
            profit,
            next_bars_since_buy if valid_buy else None,
        )
        next_buy_price = None
        next_bars_since_buy = None
    if not bar.observation_eligible:
        band_signal = None

    j_value: float | None = None
    k_value = state.k_value
    d_value = state.d_value
    j_values = state.j_values
    current_bdgd = False
    reduce_signal: MainRiseReduceSignal | None = None
    if len(closes) >= 9:
        raw9 = _rsi(closes, highs, lows, 9)
        k_value = raw9 if k_value is None else raw9 * 0.5 + k_value * 0.5
        d_value = k_value if d_value is None else k_value * 0.5 + d_value * 0.5
        j_value = _round4(3.0 * k_value - 2.0 * d_value)
        current_bdgd = j_value > 80.0 and all(
            previous < j_value for previous in j_values[-7:]
        )
        if (
            j_values
            and j_values[-1] - 0.01 > j_value
            and j_value < j_values[-1]
            and state.previous_bdgd
            and not state.previous_was_sell
            and bar.observation_eligible
        ):
            reduce_signal = MainRiseReduceSignal(bar.high, j_value)
        j_values = (j_values + (j_value,))[-8:]

    escape = step_escape_d123(state.escape_state, bar, profile=NEWOW_TREND_D1_PAGE_V2)
    magic11 = step_magic11(state.magic11_state, bar)
    raw20 = _rsi(closes, highs, lows, 20)
    raw20_window = (state.raw20_window + (raw20,))[-4:]
    var41 = _round4(sum(raw20_window[-3:]) / min(len(raw20_window), 3))
    z_value = escape.ma120
    assert z_value is not None
    var31 = _round4((_average_latest(closes, 5) - z_value) / z_value)
    buy_markers = _buy_markers(
        state, bar, close=close, z_value=z_value, var31=var31, var41=var41
    )
    next_state = MainRiseState(
        closes=closes,
        highs=highs,
        lows=lows,
        jj_values=jj_values,
        history_count=min(state.history_count + 1, 120),
        band_state=band_state,
        last_buy_price=next_buy_price,
        bars_since_buy=next_bars_since_buy,
        k_value=k_value,
        d_value=d_value,
        j_values=j_values,
        previous_bdgd=current_bdgd,
        previous_was_sell=transition is MainRiseAction.CLEAR,
        raw20_window=raw20_window,
        previous_var41=var41,
        prior_var41=state.previous_var41,
        escape_state=escape.state,
        magic11_state=magic11.state,
        physical_contract=bar.physical_contract,
        segment_id=bar.segment_id,
    )
    return MainRiseStepResult(
        next_state,
        ma35,
        ma45,
        band_state,
        band_signal,
        j_value,
        reduce_signal,
        escape.markers,
        buy_markers,
        magic11,
    )


def calculate_main_rise_series(
    bars: tuple[NewowDailyBar, ...],
    *,
    formulas: MainRiseFormulaSet = MAIN_RISE_PAGE_V1,
) -> tuple[MainRiseStepResult, ...]:
    state = initial_main_rise_state()
    results: list[MainRiseStepResult] = []
    for bar in bars:
        result = step_main_rise(state, bar, formulas=formulas)
        results.append(result)
        state = result.state
    return tuple(results)


def restore_main_rise_state(payload: Mapping[str, object]) -> MainRiseState:
    try:
        values = dict(payload)
        escape = values.get("escape_state")
        magic = values.get("magic11_state")
        if isinstance(escape, Mapping):
            values["escape_state"] = EscapeState(**escape)
        if isinstance(magic, Mapping):
            values["magic11_state"] = Magic11State(**magic)
        state = MainRiseState(**cast(dict[str, Any], values))
    except (TypeError, ValueError):
        return initial_main_rise_state()
    return state if _valid_state(state) else initial_main_rise_state()
