"""
苏冰 JM 日线 EMA21 + MACD 零轴附近金叉/死叉 + 量能放大

规格来源（研究 PoC，非正式 trusted 回测结论）：
- docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/CURRENT_CODE_RULES_v0.2.0.md
- packages/quant-core/.../su_bing_jm_daily_ema21_macd_volume/vnpy_strategy.py

与主项目 v0.2.0-daily 对齐的核心规则：
- 仅日线
- 收盘确认信号，下一交易日开盘成交（1 个不利 tick 简化为市价开仓/平仓）
- 多头：close > EMA21 + MACD 近零区金叉 + 成交量放大
- 空头：close < EMA21 + MACD 近零区死叉 + 成交量放大
- 多头退出：收盘跌破 EMA21；空头退出：收盘站上 EMA21
- 固定 1 手，不做固定止损/止盈/时间退出

RQAlpha PoC 限制：
- 标的使用 JM88 主力连续（bundle 数据），不等同于主项目 rollover-safe 具体合约映射。
- 结果仅供 RQAlpha 引擎验证，不与 vn.py report_id 直接对比。
"""

from rqalpha.api import *


EMA_PERIOD = 21
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
MACD_ZERO_BAND = 25
LOT_SIZE = 1


def init(context):
    context.s1 = "JM88"
    subscribe(context.s1)
    context.pending_action = None  # open_long | open_short | close
    context.pending_reason = ""
    logger.info("strategy=su_bing_jm_daily_ema21_macd_volume version=v0.2.0-daily-poc")


def handle_bar(context, bar_dict):
    # 昨日收盘信号 → 今日 bar 开盘成交（RQAlpha 日线不能在 before_trading 下单）
    if context.pending_action is not None:
        _execute_pending(context)
        return

    bars = history_bars(context.s1, _min_bars(), "1d", ["close", "volume"])
    if bars is None or len(bars) < _min_bars():
        return

    indicators = _calc_indicators(bars)
    position_side = _position_side(context)

    if position_side == "flat":
        decision = _entry_decision(indicators)
        if decision is not None:
            context.pending_action = decision
            context.pending_reason = _entry_reason(decision, indicators)
            logger.info("signal_pending action={} reason={}".format(decision, context.pending_reason))
        return

    if position_side == "long" and indicators["close"] < indicators["ema21"]:
        context.pending_action = "close"
        context.pending_reason = "long_close_below_ema21_exit_next_daily_open"
    elif position_side == "short" and indicators["close"] > indicators["ema21"]:
        context.pending_action = "close"
        context.pending_reason = "short_close_above_ema21_exit_next_daily_open"


def after_trading(context):
    pass


def _min_bars() -> int:
    return max(EMA_PERIOD, MACD_FAST, MACD_SLOW, MACD_SIGNAL) + 2


def _ema_series(values, period: int):
    if not values:
        return []
    alpha = 2 / (period + 1)
    ema_values = [float(values[0])]
    for value in values[1:]:
        ema_values.append(float(value) * alpha + ema_values[-1] * (1 - alpha))
    return ema_values


def _bar_field(bar, name: str):
    if hasattr(bar, name):
        return getattr(bar, name)
    if isinstance(bar, dict):
        return bar[name]
    try:
        return bar[name]
    except (TypeError, KeyError, IndexError):
        pass
    # history_bars 可能返回 numpy structured array
    import numpy as np
    if isinstance(bar, np.void):
        return float(bar[name])
    raise AttributeError(name)


def _calc_indicators(bars):
    closes = [_bar_field(bar, "close") for bar in bars]
    volumes = [_bar_field(bar, "volume") for bar in bars]
    ema21 = _ema_series(closes, EMA_PERIOD)[-1]
    fast_ema = _ema_series(closes, MACD_FAST)
    slow_ema = _ema_series(closes, MACD_SLOW)
    dif_series = [f - s for f, s in zip(fast_ema, slow_ema)]
    dea_series = _ema_series(dif_series, MACD_SIGNAL)
    dif = dif_series[-1]
    dea = dea_series[-1]
    prev_dif = dif_series[-2]
    prev_dea = dea_series[-2]
    close = closes[-1]
    current_volume = volumes[-1]
    previous_volume = volumes[-2]
    return {
        "ema21": ema21,
        "dif": dif,
        "dea": dea,
        "prev_dif": prev_dif,
        "prev_dea": prev_dea,
        "close": close,
        "current_volume": current_volume,
        "previous_volume": previous_volume,
        "near_zero": abs(dif) <= MACD_ZERO_BAND and abs(dea) <= MACD_ZERO_BAND,
        "golden_cross": prev_dif <= prev_dea and dif > dea,
        "dead_cross": prev_dif >= prev_dea and dif < dea,
        "volume_expanded": current_volume > previous_volume,
    }


def _entry_decision(indicators):
    if not indicators["near_zero"]:
        return None
    if not indicators["volume_expanded"]:
        return None
    if indicators["close"] < indicators["ema21"] and indicators["dead_cross"]:
        return "open_short"
    if indicators["close"] > indicators["ema21"] and indicators["golden_cross"]:
        return "open_long"
    return None


def _entry_reason(action: str, indicators) -> str:
    if action == "open_long":
        return "daily_close_above_ema21+macd_near_zero_golden_cross+volume_expansion"
    return "daily_close_below_ema21+macd_near_zero_dead_cross+volume_expansion"


def _position_side(context) -> str:
    pos = get_position(context.s1)
    if pos.quantity <= 0:
        return "flat"
    direction = str(getattr(pos.direction, "name", pos.direction)).upper()
    if "SHORT" in direction:
        return "short"
    return "long"


def _execute_pending(context):
    action = context.pending_action
    if not action:
        return

    context.pending_action = None
    reason = context.pending_reason
    context.pending_reason = ""

    if action == "open_long":
        order = buy_open(context.s1, LOT_SIZE)
        logger.info("filled_long reason={} order={}".format(reason, order))
        return

    if action == "open_short":
        order = sell_open(context.s1, LOT_SIZE)
        logger.info("filled_short reason={} order={}".format(reason, order))
        return

    if action == "close":
        pos = get_position(context.s1)
        if pos.quantity <= 0:
            return
        direction = str(getattr(pos.direction, "name", pos.direction)).upper()
        if "SHORT" in direction:
            order = buy_close(context.s1, pos.quantity)
            logger.info("closed_short reason={} order={}".format(reason, order))
        else:
            order = sell_close(context.s1, pos.quantity)
            logger.info("closed_long reason={} order={}".format(reason, order))
