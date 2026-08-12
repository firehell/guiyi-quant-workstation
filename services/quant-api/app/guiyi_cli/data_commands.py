"""``guiyi data`` 子命令请求构建与执行。

将 argparse Namespace 转为 HistoricalDataManager 的 Update/Audit/Refresh 请求对象，
并委托 manager 同名方法执行。active universe 固定 60 品种，与仓库 data/universe 对齐。
退役品种由 ``retired_products.txt`` 精确拦截；已完成的生产清退不再提供重复执行入口。
"""

from __future__ import annotations

import argparse
from datetime import date

from app.market_data.historical_data_manager import (
    AuditRequest,
    HistoricalDataManager,
    RefreshRequest,
    UpdateRequest,
)
from app.market_data.product_retirement import assert_not_retired
from app.market_data.operational_universe import load_active_products


def build_request(args: argparse.Namespace):
    """根据 data_command 分支构造对应的维护请求对象。"""
    if args.data_command == "after-market":
        return None
    if args.data_command == "update":
        return UpdateRequest(
            products=_products(args.symbol, args.universe),
            since=_day(args.since),
            through=_day(args.through),
            apply=bool(args.apply),
        )
    if args.data_command == "audit":
        return AuditRequest(
            _products(args.symbol, args.universe),
            through=_day(args.through),
        )
    if args.data_command == "refresh":
        since = _day(args.since)
        through = _day(args.through)
        assert since is not None and through is not None
        return RefreshRequest(
            symbol=_products(args.symbol, None)[0],
            since=since,
            through=through,
            apply=bool(args.apply),
        )
    raise ValueError("CLI_DATA_COMMAND_INVALID")


def run_data_command(args: argparse.Namespace, manager: HistoricalDataManager):
    """调用 manager 上与 data_command 同名的方法并返回结果对象。"""
    request = build_request(args)
    action = getattr(manager, args.data_command)
    return action(request)


def _products(symbol: str | None, universe: str | None) -> tuple[str, ...]:
    """解析品种列表：--universe active 或单个 --symbol。"""
    if universe == "active":
        return load_active_products()
    normalized = str(symbol or "").strip().lower()
    if not normalized:
        raise ValueError("CLI_SYMBOL_REQUIRED")
    assert_not_retired(normalized)
    return (normalized,)


def _day(value: str | None) -> date | None:
    """ISO 日期字符串转 date；无效时抛出 CLI_DATE_INVALID。"""
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("CLI_DATE_INVALID") from exc
