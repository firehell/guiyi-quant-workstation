"""``guiyi data`` 子命令请求构建与执行。

将 argparse Namespace 转为 HistoricalDataManager 的 Update/Audit/Refresh 请求对象，
并委托 manager 同名方法执行。active universe 固定 60 品种，与仓库 data/universe 对齐。
退役品种由 ``retired_products.txt`` 精确拦截；已完成的生产清退不再提供重复执行入口。
"""

from __future__ import annotations

import argparse
from datetime import date
import json
from typing import TextIO

from app.market_data.historical_data_manager import (
    AuditProgressEvent,
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


def run_data_command(
    args: argparse.Namespace,
    manager: HistoricalDataManager,
    *,
    progress_stream: TextIO | None = None,
):
    """调用 manager 上与 data_command 同名的方法并返回结果对象。"""
    request = build_request(args)
    if args.data_command == "audit" and bool(getattr(args, "progress", False)):
        assert progress_stream is not None
        return manager.audit(request, observer=_audit_progress_writer(progress_stream))
    action = getattr(manager, args.data_command)
    return action(request)


def _audit_progress_writer(stream: TextIO):
    """将结构化 audit 进度编码为 NDJSON；首次输出失败后永久静默。"""
    disabled = False

    def write(event: AuditProgressEvent) -> None:
        nonlocal disabled
        if disabled:
            return
        payload = {
            "schema_version": 1,
            "event": "data.audit.progress",
            "state": event.state,
            "completed": event.completed,
            "total": event.total,
            "symbol": event.symbol,
            "finding_count": event.finding_count,
        }
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        try:
            if stream.write(line) != len(line):
                raise OSError("CLI_AUDIT_PROGRESS_SHORT_WRITE")
            stream.flush()
        except Exception:  # noqa: BLE001 - progress must not affect the audit result
            disabled = True

    return write


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


def _required_day(value: str | None) -> date:
    result = _day(value)
    if result is None:
        raise ValueError("CLI_DATE_INVALID")
    return result
