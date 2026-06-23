from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from math import isfinite
from typing import Any, Literal, Mapping


Direction = Literal["long", "short", "neutral"]
PositionState = Literal["flat", "trial_long", "long", "trial_short", "short"]

STATUS_FLAT = "空仓"
STATUS_WATCH_LONG = "观察多"
STATUS_TRIAL_LONG = "轻仓试多"
STATUS_CONFIRM_LONG = "开多确认"
STATUS_HOLD_LONG = "持多"
STATUS_ADD_LONG = "加多观察"
STATUS_REDUCE_LONG = "减多"
STATUS_EXIT_LONG = "平多"
STATUS_WATCH_SHORT = "观察空"
STATUS_TRIAL_SHORT = "轻仓试空"
STATUS_CONFIRM_SHORT = "开空确认"
STATUS_HOLD_SHORT = "持空"
STATUS_ADD_SHORT = "加空观察"
STATUS_REDUCE_SHORT = "减空"
STATUS_EXIT_SHORT = "平空"


@dataclass(frozen=True)
class SuBingParams:
    ema_period: int = 21
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    atr_period: int = 14
    chop_lookback: int = 12
    chop_cross_threshold: int = 4
    breakout_lookback: int = 20
    confirmation_bars: int = 3
    volume_ratio_intraday: float = 3.0
    volume_ratio_daily: float = 1.0
    zero_axis_atr_threshold: float = 0.3
    max_distance_from_ema_atr: float = 1.5
    time_stop_bars: int = 5
    confluence_threshold: int = 3
    volume_lookback: int = 20
    macd_cross_lookback: int = 3
    rapid_move_lookback: int = 3
    rapid_move_atr_threshold: float = 1.5


@dataclass(frozen=True)
class StrategyBar:
    symbol: str
    contract: str
    exchange: str
    datetime: datetime
    trading_day: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    open_interest: float | None = None
    period: str | None = None


@dataclass(frozen=True)
class SignalSnapshot:
    datetime: datetime
    status: str
    direction: Direction
    signal_level: int
    reasons: list[str]
    features: dict[str, Any]
    trade_intent: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class _RuntimeState:
    position: PositionState = "flat"
    entry_index: int | None = None
    entry_price: float | None = None
    breakout_level: float | None = None


@dataclass(frozen=True)
class _Indicators:
    ema: list[float]
    macd_diff: list[float]
    macd_dea: list[float]
    macd_hist: list[float]
    atr: list[float]


@dataclass(frozen=True)
class _BarContext:
    bar: StrategyBar
    index: int
    ema: float
    macd_diff: float
    macd_dea: float
    macd_hist: float
    atr: float
    volume_ratio: float | None
    prior_high: float | None
    prior_low: float | None
    chop_cross_count: int
    higher_resonance: bool | None

    @property
    def distance_from_ema_atr(self) -> float:
        if self.atr <= 0:
            return 0.0
        return abs(self.bar.close - self.ema) / self.atr


def generate_signals(
    primary_bars: list[Mapping[str, Any] | StrategyBar],
    higher_timeframe_bars: list[Mapping[str, Any] | StrategyBar] | None = None,
    params: SuBingParams | None = None,
    initial_state: str | None = None,
) -> list[SignalSnapshot]:
    """Generate Su Bing EMA21 rule signals from canonical bars.

    Signals are computed left-to-right. Every output for a bar uses only that
    bar and earlier bars. A signal is a next-bar research intent, not an order.
    """

    rule_params = params or SuBingParams()
    bars = [_coerce_bar(row) for row in primary_bars]
    _validate_bars(bars)
    if not bars:
        return []

    higher_bars = [_coerce_bar(row) for row in higher_timeframe_bars or []]
    _validate_bars(higher_bars)

    indicators = _calculate_indicators(bars, rule_params)
    higher_indicators = _calculate_indicators(higher_bars, rule_params) if higher_bars else None
    state = _RuntimeState(position=_initial_position(initial_state))
    snapshots: list[SignalSnapshot] = []

    for index, bar in enumerate(bars):
        context = _build_context(
            bars=bars,
            indicators=indicators,
            higher_bars=higher_bars,
            higher_indicators=higher_indicators,
            params=rule_params,
            index=index,
        )
        if not _is_warmed_up(index, rule_params):
            snapshots.append(_snapshot(context, STATUS_FLAT, "neutral", 0, ["指标预热中"], "none"))
            continue

        snapshot = _advance_state(bars, context, state, indicators, rule_params)
        snapshots.append(snapshot)

    return snapshots


def _advance_state(
    bars: list[StrategyBar],
    context: _BarContext,
    state: _RuntimeState,
    indicators: _Indicators,
    params: SuBingParams,
) -> SignalSnapshot:
    if state.position in {"trial_long", "long"}:
        return _advance_long_state(bars, context, state, indicators, params)
    if state.position in {"trial_short", "short"}:
        return _advance_short_state(bars, context, state, indicators, params)
    return _advance_flat_state(bars, context, state, indicators, params)


def _advance_flat_state(
    bars: list[StrategyBar],
    context: _BarContext,
    state: _RuntimeState,
    indicators: _Indicators,
    params: SuBingParams,
) -> SignalSnapshot:
    bar = context.bar
    if context.chop_cross_count >= params.chop_cross_threshold:
        return _snapshot(
            context,
            STATUS_FLAT,
            "neutral",
            0,
            ["价格围绕EMA21反复穿越，判定为震荡，不开仓"],
            "none",
        )

    if bar.close > context.ema:
        filter_reasons = _entry_filter_reasons(bars, context, "long", params)
        score, score_reasons = _confluence_score(context, indicators, "long", params)
        if not filter_reasons and score >= params.confluence_threshold and _recent_macd_cross(indicators, context.index, "long", params):
            state.position = "trial_long"
            state.entry_index = context.index
            state.entry_price = bar.close
            state.breakout_level = context.prior_high
            return _snapshot(
                context,
                STATUS_TRIAL_LONG,
                "long",
                _level(STATUS_TRIAL_LONG, context.higher_resonance),
                ["EMA21上方只做多", *score_reasons, "带量突破，轻仓试多"],
                "trial_entry",
                confluence_count=score,
            )
        return _snapshot(
            context,
            STATUS_WATCH_LONG,
            "long",
            _level(STATUS_WATCH_LONG, context.higher_resonance),
            ["EMA21上方只观察多头机会", *filter_reasons, *score_reasons],
            "watch",
            confluence_count=score,
        )

    if bar.close < context.ema:
        filter_reasons = _entry_filter_reasons(bars, context, "short", params)
        score, score_reasons = _confluence_score(context, indicators, "short", params)
        if not filter_reasons and score >= params.confluence_threshold and _recent_macd_cross(indicators, context.index, "short", params):
            state.position = "trial_short"
            state.entry_index = context.index
            state.entry_price = bar.close
            state.breakout_level = context.prior_low
            return _snapshot(
                context,
                STATUS_TRIAL_SHORT,
                "short",
                _level(STATUS_TRIAL_SHORT, context.higher_resonance),
                ["EMA21下方只做空", *score_reasons, "带量跌破，轻仓试空"],
                "trial_entry",
                confluence_count=score,
            )
        return _snapshot(
            context,
            STATUS_WATCH_SHORT,
            "short",
            _level(STATUS_WATCH_SHORT, context.higher_resonance),
            ["EMA21下方只观察空头机会", *filter_reasons, *score_reasons],
            "watch",
            confluence_count=score,
        )

    return _snapshot(context, STATUS_FLAT, "neutral", 0, ["收盘价贴近EMA21，方向不明"], "none")


def _advance_long_state(
    bars: list[StrategyBar],
    context: _BarContext,
    state: _RuntimeState,
    indicators: _Indicators,
    params: SuBingParams,
) -> SignalSnapshot:
    previous = bars[context.index - 1] if context.index > 0 else None
    bar = context.bar
    entry_age = _entry_age(context, state)

    if (
        state.position == "trial_long"
        and state.breakout_level is not None
        and entry_age <= params.confirmation_bars
        and bar.close <= state.breakout_level
    ):
        state.position = "flat"
        return _snapshot(context, STATUS_EXIT_LONG, "neutral", _level(STATUS_EXIT_LONG), ["突破后回到原区间，假突破平多"], "exit")
    if bar.close < context.ema:
        state.position = "flat"
        return _snapshot(context, STATUS_EXIT_LONG, "neutral", _level(STATUS_EXIT_LONG), ["多单跌破EMA21，平多"], "exit")
    if previous and bar.close < previous.low:
        status = STATUS_EXIT_LONG if state.position == "trial_long" else STATUS_REDUCE_LONG
        if state.position == "trial_long":
            state.position = "flat"
        return _snapshot(context, status, "long", _level(status), ["多单跌破上一根K线低点，减仓或平多"], "exit" if status == STATUS_EXIT_LONG else "reduce")
    if _macd_cross_at(indicators, context.index, "short"):
        return _snapshot(context, STATUS_REDUCE_LONG, "long", _level(STATUS_REDUCE_LONG), ["MACD反向死叉，多单减仓"], "reduce")
    if _time_stop_triggered(context, state, "long", params):
        state.position = "flat"
        return _snapshot(context, STATUS_EXIT_LONG, "neutral", _level(STATUS_EXIT_LONG), ["持仓超过时间窗口仍未盈利，平多"], "exit")

    if state.position == "trial_long":
        if entry_age >= params.confirmation_bars:
            state.position = "long"
            return _snapshot(context, STATUS_CONFIRM_LONG, "long", _level(STATUS_CONFIRM_LONG, context.higher_resonance), ["突破后三根K线未回原区间，开多确认"], "confirm_entry")
        return _snapshot(context, STATUS_TRIAL_LONG, "long", _level(STATUS_TRIAL_LONG, context.higher_resonance), ["轻仓试多观察中"], "hold")

    score, score_reasons = _confluence_score(context, indicators, "long", params)
    if score >= params.confluence_threshold and _is_breakout(context, "long") and _is_volume_expanded(context, params):
        return _snapshot(context, STATUS_ADD_LONG, "long", _level(STATUS_ADD_LONG, context.higher_resonance), ["持多中再次带量突破，加多观察", *score_reasons], "add_watch", confluence_count=score)
    return _snapshot(context, STATUS_HOLD_LONG, "long", _level(STATUS_HOLD_LONG, context.higher_resonance), ["持多：未破EMA21和上一根K线低点"], "hold", confluence_count=score)


def _advance_short_state(
    bars: list[StrategyBar],
    context: _BarContext,
    state: _RuntimeState,
    indicators: _Indicators,
    params: SuBingParams,
) -> SignalSnapshot:
    previous = bars[context.index - 1] if context.index > 0 else None
    bar = context.bar
    entry_age = _entry_age(context, state)

    if (
        state.position == "trial_short"
        and state.breakout_level is not None
        and entry_age <= params.confirmation_bars
        and bar.close >= state.breakout_level
    ):
        state.position = "flat"
        return _snapshot(context, STATUS_EXIT_SHORT, "neutral", _level(STATUS_EXIT_SHORT), ["跌破后回到原区间，假突破平空"], "exit")
    if bar.close > context.ema:
        state.position = "flat"
        return _snapshot(context, STATUS_EXIT_SHORT, "neutral", _level(STATUS_EXIT_SHORT), ["空单突破EMA21，平空"], "exit")
    if previous and bar.close > previous.high:
        status = STATUS_EXIT_SHORT if state.position == "trial_short" else STATUS_REDUCE_SHORT
        if state.position == "trial_short":
            state.position = "flat"
        return _snapshot(context, status, "short", _level(status), ["空单突破上一根K线高点，减仓或平空"], "exit" if status == STATUS_EXIT_SHORT else "reduce")
    if _macd_cross_at(indicators, context.index, "long"):
        return _snapshot(context, STATUS_REDUCE_SHORT, "short", _level(STATUS_REDUCE_SHORT), ["MACD反向金叉，空单减仓"], "reduce")
    if _time_stop_triggered(context, state, "short", params):
        state.position = "flat"
        return _snapshot(context, STATUS_EXIT_SHORT, "neutral", _level(STATUS_EXIT_SHORT), ["持仓超过时间窗口仍未盈利，平空"], "exit")

    if state.position == "trial_short":
        if entry_age >= params.confirmation_bars:
            state.position = "short"
            return _snapshot(context, STATUS_CONFIRM_SHORT, "short", _level(STATUS_CONFIRM_SHORT, context.higher_resonance), ["跌破后三根K线未回原区间，开空确认"], "confirm_entry")
        return _snapshot(context, STATUS_TRIAL_SHORT, "short", _level(STATUS_TRIAL_SHORT, context.higher_resonance), ["轻仓试空观察中"], "hold")

    score, score_reasons = _confluence_score(context, indicators, "short", params)
    if score >= params.confluence_threshold and _is_breakout(context, "short") and _is_volume_expanded(context, params):
        return _snapshot(context, STATUS_ADD_SHORT, "short", _level(STATUS_ADD_SHORT, context.higher_resonance), ["持空中再次带量跌破，加空观察", *score_reasons], "add_watch", confluence_count=score)
    return _snapshot(context, STATUS_HOLD_SHORT, "short", _level(STATUS_HOLD_SHORT, context.higher_resonance), ["持空：未突破EMA21和上一根K线高点"], "hold", confluence_count=score)


def _snapshot(
    context: _BarContext,
    status: str,
    direction: Direction,
    signal_level: int,
    reasons: list[str],
    action: str,
    confluence_count: int | None = None,
) -> SignalSnapshot:
    features = {
        "ema21": _round(context.ema),
        "macd_diff": _round(context.macd_diff),
        "macd_dea": _round(context.macd_dea),
        "macd_hist": _round(context.macd_hist),
        "atr": _round(context.atr),
        "volume_ratio": None if context.volume_ratio is None else _round(context.volume_ratio),
        "prior_high": None if context.prior_high is None else _round(context.prior_high),
        "prior_low": None if context.prior_low is None else _round(context.prior_low),
        "chop_cross_count": context.chop_cross_count,
        "distance_from_ema_atr": _round(context.distance_from_ema_atr),
        "higher_timeframe_resonance": context.higher_resonance,
    }
    if confluence_count is not None:
        features["confluence_count"] = confluence_count
    return SignalSnapshot(
        datetime=context.bar.datetime,
        status=status,
        direction=direction,
        signal_level=signal_level,
        reasons=[reason for reason in reasons if reason],
        features=features,
        trade_intent={
            "action": action,
            "execution_timing": "next_bar",
            "order_draft": False,
        },
    )


def _confluence_score(
    context: _BarContext,
    indicators: _Indicators,
    direction: Direction,
    params: SuBingParams,
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    if direction == "long" and context.bar.close > context.ema:
        score += 1
        reasons.append("价格位于EMA21上方")
    if direction == "short" and context.bar.close < context.ema:
        score += 1
        reasons.append("价格位于EMA21下方")
    if _recent_macd_cross(indicators, context.index, direction, params) and _macd_near_zero(context, params):
        score += 1
        reasons.append("MACD零轴附近金叉" if direction == "long" else "MACD零轴附近死叉")
    if _is_volume_expanded(context, params):
        score += 1
        reasons.append("成交量放大")
    if _is_breakout(context, direction):
        score += 1
        reasons.append("突破前区间高点" if direction == "long" else "跌破前区间低点")
    if context.higher_resonance is True:
        score += 1
        reasons.append("高周期方向共振")
    elif context.higher_resonance is False:
        reasons.append("高周期方向未共振")
    return score, reasons


def _entry_filter_reasons(
    bars: list[StrategyBar],
    context: _BarContext,
    direction: Direction,
    params: SuBingParams,
) -> list[str]:
    reasons: list[str] = []
    if context.distance_from_ema_atr > params.max_distance_from_ema_atr:
        reasons.append("价格远离EMA21，不追单")
    if direction == "long" and _rapid_move(bars, context, params) == "down":
        reasons.append("快速下跌中不做多")
    if direction == "short" and _rapid_move(bars, context, params) == "up":
        reasons.append("快速上涨中不做空")
    if not _macd_near_zero(context, params):
        reasons.append("MACD未处于零轴附近，暂不确认开仓")
    return reasons


def _build_context(
    bars: list[StrategyBar],
    indicators: _Indicators,
    higher_bars: list[StrategyBar],
    higher_indicators: _Indicators | None,
    params: SuBingParams,
    index: int,
) -> _BarContext:
    start = max(0, index - params.breakout_lookback)
    history = bars[start:index]
    prior_high = max((bar.high for bar in history), default=None)
    prior_low = min((bar.low for bar in history), default=None)
    higher_resonance = _higher_timeframe_resonance(
        current_bar=bars[index],
        primary_close=bars[index].close,
        primary_ema=indicators.ema[index],
        higher_bars=higher_bars,
        higher_indicators=higher_indicators,
    )
    return _BarContext(
        bar=bars[index],
        index=index,
        ema=indicators.ema[index],
        macd_diff=indicators.macd_diff[index],
        macd_dea=indicators.macd_dea[index],
        macd_hist=indicators.macd_hist[index],
        atr=indicators.atr[index],
        volume_ratio=_volume_ratio(bars, index, params.volume_lookback),
        prior_high=prior_high,
        prior_low=prior_low,
        chop_cross_count=_chop_cross_count(bars, indicators.ema, index, params.chop_lookback),
        higher_resonance=higher_resonance,
    )


def _calculate_indicators(bars: list[StrategyBar], params: SuBingParams) -> _Indicators:
    closes = [bar.close for bar in bars]
    ema = _ema(closes, params.ema_period)
    macd_fast = _ema(closes, params.macd_fast)
    macd_slow = _ema(closes, params.macd_slow)
    macd_diff = [fast - slow for fast, slow in zip(macd_fast, macd_slow, strict=True)]
    macd_dea = _ema(macd_diff, params.macd_signal)
    macd_hist = [diff - dea for diff, dea in zip(macd_diff, macd_dea, strict=True)]
    atr = _atr(bars, params.atr_period)
    return _Indicators(ema=ema, macd_diff=macd_diff, macd_dea=macd_dea, macd_hist=macd_hist, atr=atr)


def _ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2 / (period + 1)
    result = [values[0]]
    for value in values[1:]:
        result.append(alpha * value + (1 - alpha) * result[-1])
    return result


def _atr(bars: list[StrategyBar], period: int) -> list[float]:
    if not bars:
        return []
    true_ranges: list[float] = []
    for index, bar in enumerate(bars):
        if index == 0:
            true_ranges.append(bar.high - bar.low)
            continue
        previous_close = bars[index - 1].close
        true_ranges.append(max(bar.high - bar.low, abs(bar.high - previous_close), abs(bar.low - previous_close)))
    result = [true_ranges[0]]
    for value in true_ranges[1:]:
        result.append((result[-1] * (period - 1) + value) / period)
    return result


def _recent_macd_cross(
    indicators: _Indicators,
    index: int,
    direction: Direction,
    params: SuBingParams,
) -> bool:
    start = max(1, index - params.macd_cross_lookback + 1)
    return any(_macd_cross_at(indicators, cross_index, direction) for cross_index in range(start, index + 1))


def _macd_cross_at(indicators: _Indicators, index: int, direction: Direction) -> bool:
    if index <= 0:
        return False
    previous_diff = indicators.macd_diff[index - 1]
    previous_dea = indicators.macd_dea[index - 1]
    current_diff = indicators.macd_diff[index]
    current_dea = indicators.macd_dea[index]
    if direction == "long":
        return previous_diff <= previous_dea and current_diff > current_dea
    if direction == "short":
        return previous_diff >= previous_dea and current_diff < current_dea
    return False


def _macd_near_zero(context: _BarContext, params: SuBingParams) -> bool:
    threshold = max(context.atr * params.zero_axis_atr_threshold, 1e-9)
    return abs(context.macd_diff) <= threshold and abs(context.macd_dea) <= threshold


def _is_volume_expanded(context: _BarContext, params: SuBingParams) -> bool:
    if context.volume_ratio is None:
        return False
    threshold = params.volume_ratio_daily if context.bar.period == "1d" else params.volume_ratio_intraday
    return context.volume_ratio >= threshold


def _is_breakout(context: _BarContext, direction: Direction) -> bool:
    if direction == "long":
        return context.prior_high is not None and context.bar.close > context.prior_high
    if direction == "short":
        return context.prior_low is not None and context.bar.close < context.prior_low
    return False


def _volume_ratio(bars: list[StrategyBar], index: int, lookback: int) -> float | None:
    start = max(0, index - lookback)
    previous = [bar.volume for bar in bars[start:index] if bar.volume > 0]
    if not previous:
        return None
    return bars[index].volume / (sum(previous) / len(previous))


def _chop_cross_count(bars: list[StrategyBar], ema: list[float], index: int, lookback: int) -> int:
    start = max(0, index - lookback + 1)
    crosses = 0
    previous_side = _side(bars[start].close, ema[start])
    for cursor in range(start + 1, index + 1):
        current_side = _side(bars[cursor].close, ema[cursor])
        if previous_side != 0 and current_side != 0 and current_side != previous_side:
            crosses += 1
        if current_side != 0:
            previous_side = current_side
    return crosses


def _side(close: float, ema: float) -> int:
    if close > ema:
        return 1
    if close < ema:
        return -1
    return 0


def _rapid_move(
    bars: list[StrategyBar],
    context: _BarContext,
    params: SuBingParams,
) -> Literal["up", "down", "none"]:
    start = context.index - params.rapid_move_lookback
    if start < 0 or context.atr <= 0:
        return "none"
    move = context.bar.close - bars[start].close
    threshold = context.atr * params.rapid_move_atr_threshold
    if move >= threshold:
        return "up"
    if move <= -threshold:
        return "down"
    return "none"


def _higher_timeframe_resonance(
    current_bar: StrategyBar,
    primary_close: float,
    primary_ema: float,
    higher_bars: list[StrategyBar],
    higher_indicators: _Indicators | None,
) -> bool | None:
    if not higher_bars or higher_indicators is None:
        return None
    higher_index = None
    for index, bar in enumerate(higher_bars):
        if bar.datetime <= current_bar.datetime:
            higher_index = index
        else:
            break
    if higher_index is None:
        return None
    primary_side = _side(primary_close, primary_ema)
    higher_side = _side(higher_bars[higher_index].close, higher_indicators.ema[higher_index])
    if primary_side == 0 or higher_side == 0:
        return False
    return primary_side == higher_side


def _time_stop_triggered(
    context: _BarContext,
    state: _RuntimeState,
    direction: Direction,
    params: SuBingParams,
) -> bool:
    if state.entry_index is None or state.entry_price is None:
        return False
    if context.index - state.entry_index < params.time_stop_bars:
        return False
    if direction == "long":
        return context.bar.close <= state.entry_price
    if direction == "short":
        return context.bar.close >= state.entry_price
    return False


def _entry_age(context: _BarContext, state: _RuntimeState) -> int:
    if state.entry_index is None:
        return 0
    return context.index - state.entry_index


def _is_warmed_up(index: int, params: SuBingParams) -> bool:
    return index >= max(params.ema_period, params.macd_slow + params.macd_signal, params.atr_period)


def _level(status: str, higher_resonance: bool | None = None) -> int:
    base = {
        STATUS_FLAT: 0,
        STATUS_WATCH_LONG: 51,
        STATUS_WATCH_SHORT: 51,
        STATUS_TRIAL_LONG: 60,
        STATUS_TRIAL_SHORT: 60,
        STATUS_CONFIRM_LONG: 70,
        STATUS_CONFIRM_SHORT: 70,
        STATUS_HOLD_LONG: 70,
        STATUS_HOLD_SHORT: 70,
        STATUS_ADD_LONG: 80,
        STATUS_ADD_SHORT: 80,
        STATUS_REDUCE_LONG: 60,
        STATUS_REDUCE_SHORT: 60,
        STATUS_EXIT_LONG: 60,
        STATUS_EXIT_SHORT: 60,
    }[status]
    if higher_resonance is True and base > 0:
        return min(80, base + 5)
    return base


def _coerce_bar(row: Mapping[str, Any] | StrategyBar) -> StrategyBar:
    if isinstance(row, StrategyBar):
        return row
    timestamp = row.get("datetime") or row.get("time")
    if isinstance(timestamp, str):
        parsed_datetime = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).replace(tzinfo=None)
    elif isinstance(timestamp, datetime):
        parsed_datetime = timestamp.replace(tzinfo=None)
    else:
        raise ValueError("bar datetime is required")

    trading_day = row.get("trading_day") or parsed_datetime.date()
    if isinstance(trading_day, str):
        parsed_trading_day = date.fromisoformat(trading_day)
    elif isinstance(trading_day, datetime):
        parsed_trading_day = trading_day.date()
    elif isinstance(trading_day, date):
        parsed_trading_day = trading_day
    else:
        raise ValueError("bar trading_day is invalid")

    open_interest = row.get("open_interest", row.get("openInterest"))
    return StrategyBar(
        symbol=str(row["symbol"]),
        contract=str(row["contract"]),
        exchange=str(row["exchange"]),
        datetime=parsed_datetime,
        trading_day=parsed_trading_day,
        open=_finite_float(row["open"], "open"),
        high=_finite_float(row["high"], "high"),
        low=_finite_float(row["low"], "low"),
        close=_finite_float(row["close"], "close"),
        volume=_finite_float(row["volume"], "volume"),
        open_interest=None if open_interest is None else _finite_float(open_interest, "open_interest"),
        period=None if row.get("period") is None else str(row["period"]),
    )


def _validate_bars(bars: list[StrategyBar]) -> None:
    for index, bar in enumerate(bars):
        if bar.high < max(bar.open, bar.close, bar.low):
            raise ValueError(f"bar {index} has invalid OHLC high")
        if bar.low > min(bar.open, bar.close, bar.high):
            raise ValueError(f"bar {index} has invalid OHLC low")
        if bar.volume < 0:
            raise ValueError(f"bar {index} has negative volume")
        if bar.open_interest is not None and bar.open_interest < 0:
            raise ValueError(f"bar {index} has negative open_interest")
        if index > 0 and bar.datetime <= bars[index - 1].datetime:
            raise ValueError("bars must be strictly sorted by datetime")


def _initial_position(initial_state: str | None) -> PositionState:
    if initial_state is None:
        return "flat"
    mapping: dict[str, PositionState] = {
        STATUS_TRIAL_LONG: "trial_long",
        STATUS_CONFIRM_LONG: "long",
        STATUS_HOLD_LONG: "long",
        STATUS_TRIAL_SHORT: "trial_short",
        STATUS_CONFIRM_SHORT: "short",
        STATUS_HOLD_SHORT: "short",
        STATUS_FLAT: "flat",
        "flat": "flat",
        "trial_long": "trial_long",
        "long": "long",
        "trial_short": "trial_short",
        "short": "short",
    }
    if initial_state not in mapping:
        raise ValueError(f"unsupported initial_state: {initial_state}")
    return mapping[initial_state]


def _finite_float(value: Any, field_name: str) -> float:
    numeric = float(value)
    if not isfinite(numeric):
        raise ValueError(f"bar {field_name} must be finite")
    return numeric


def _round(value: float) -> float:
    return round(value, 6)
