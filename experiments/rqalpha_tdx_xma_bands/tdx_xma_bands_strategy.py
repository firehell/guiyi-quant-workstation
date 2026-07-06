"""
通达信 XMA 通道策略 — RQAlpha Plus 研究 PoC

警告：XMA 为通达信偏移均线（未来函数），本策略故意保留该设计。
预计算全序列指标后映射到 bar，结果不可作为无未来函数的可信回测结论。

入场：XG（回调买）或 XG2（黑马暴涨）任一触发 → 次日开盘做多 1 手
出场：收盘跌破 ZD2 → 次日开盘平多
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

from rqalpha.api import *

LOT_SIZE = 1
_STRATEGY_DIR = Path(os.environ.get("TDX_XMA_STRATEGY_DIR", Path(__file__).resolve().parent))


def _load_local_module(name: str):
    path = _STRATEGY_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def init(context):
    load_bundle_bars = _load_local_module("load_bundle_bars")
    xma_core = _load_local_module("xma_core")

    context.s1 = "JM88"
    subscribe(context.s1)
    context.pending_action = None
    context.pending_reason = ""

    start = context.run_info.start_date.strftime("%Y-%m-%d")
    end = context.run_info.end_date.strftime("%Y-%m-%d")
    start_int = int(context.run_info.start_date.strftime("%Y%m%d"))
    end_int = int(context.run_info.end_date.strftime("%Y%m%d"))

    bars = load_bundle_bars.load_jm88_bars(start, end, symbol=context.s1)
    signals = xma_core.precompute(
        bars.datetimes,
        bars.open,
        bars.high,
        bars.low,
        bars.close,
        bars.volume,
    )
    context.signal_by_date = xma_core.signals_for_range(signals, start_int, end_int)

    entry_count = sum(1 for v in context.signal_by_date.values() if v["entry_long"])
    logger.info(
        "strategy=tdx_xma_bands symbol={} range={}~{} entry_signals={}".format(
            context.s1,
            start,
            end,
            entry_count,
        )
    )


def handle_bar(context, bar_dict):
    if context.pending_action is not None:
        _execute_pending(context)
        return

    bar = bar_dict[context.s1]
    dt_int = _bar_date_int(bar)
    flags = context.signal_by_date.get(dt_int)
    if flags is None:
        return

    side = _position_side(context)

    if side == "long" and flags["exit_long"]:
        context.pending_action = "close"
        context.pending_reason = "close_below_zd2_exit_next_daily_open"
        logger.info("signal_pending action=close date={} reason={}".format(dt_int, context.pending_reason))
        return

    if side == "flat" and flags["entry_long"]:
        reason = "xg_callback" if flags["xg"] and not flags["xg2"] else (
            "xg2_heima" if flags["xg2"] and not flags["xg"] else "xg_or_xg2"
        )
        context.pending_action = "open_long"
        context.pending_reason = reason
        logger.info("signal_pending action=open_long date={} reason={}".format(dt_int, reason))


def after_trading(context):
    pass


def _bar_date_int(bar) -> int:
    dt = bar.datetime
    if hasattr(dt, "strftime"):
        return int(dt.strftime("%Y%m%d"))
    text = str(int(dt))
    return int(text[:8])


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
