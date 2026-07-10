from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.backtest.service import compute_consistency_hash  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.backtest import BacktestOrderModel, BacktestReportModel, BacktestTradeModel  # noqa: E402
from app.vnpy_integration.result_converter import apply_backtest_lineage_mapping  # noqa: E402


STAGE13G_REPORT_ID = 14
STAGE13G_EXPECTED_TRADE_COUNT = 155
STAGE13G_EXPECTED_ORDER_COUNT = 239
STAGE13G_EXPECTED_PARTIAL_TRADES = 155
STAGE13G_EXPECTED_UNMAPPED_ORDERS = 239


def repair_report_lineage(
    session: Session,
    *,
    report_id: int,
    apply: bool = False,
    confirm: bool = False,
    strict_report14_guard: bool = False,
) -> dict[str, Any]:
    if apply and not confirm:
        raise ValueError("apply requires confirmation flag")

    report = session.get(BacktestReportModel, report_id)
    if report is None:
        raise ValueError(f"report_id={report_id} not found")

    trades = list(
        session.scalars(
            select(BacktestTradeModel)
            .where(BacktestTradeModel.report_id == report_id)
            .order_by(BacktestTradeModel.sequence, BacktestTradeModel.id)
        )
    )
    orders = list(
        session.scalars(
            select(BacktestOrderModel)
            .where(BacktestOrderModel.report_id == report_id)
            .order_by(BacktestOrderModel.order_time, BacktestOrderModel.id)
        )
    )
    before_summary = _lineage_summary(report)
    if strict_report14_guard:
        _check_report14_guard(report=report, trades=trades, orders=orders, before_summary=before_summary)

    mapped = apply_backtest_lineage_mapping(
        trades=[_trade_payload(trade) for trade in trades],
        orders=[_order_payload(order) for order in orders],
        strategy_execution_events=_strategy_execution_events(report),
    )
    after_summary = dict(mapped["lineage_summary"])
    result: dict[str, Any] = {
        "mode": "apply" if apply else "dry-run",
        "report_id": report_id,
        "report_no": report.report_no,
        "task_no": report.task_no,
        "before": before_summary,
        "after": after_summary,
        "would_write_db": bool(apply),
        "updated_trades": 0,
        "updated_orders": 0,
    }

    if not apply:
        return result

    mapped_trades_by_no = {str(row.get("tradeid") or row.get("trade_id") or row.get("trade_no")): row for row in mapped["trades"]}
    mapped_orders_by_no = {str(row.get("orderid") or row.get("order_id") or row.get("order_no")): row for row in mapped["orders"]}
    for trade in trades:
        mapped_trade = mapped_trades_by_no.get(trade.trade_no)
        if mapped_trade is None:
            continue
        _apply_trade_mapping(trade, mapped_trade)
        result["updated_trades"] += 1
    for order in orders:
        mapped_order = mapped_orders_by_no.get(order.order_no)
        if mapped_order is None:
            continue
        _apply_order_mapping(order, mapped_order)
        result["updated_orders"] += 1

    summary = dict(report.summary or {})
    summary["lineage_summary"] = after_summary
    consistency_hash = compute_consistency_hash(summary=summary, trades=mapped["trades"])
    summary["consistency_hash"] = consistency_hash
    report.summary = summary
    report.consistency_hash = consistency_hash
    flag_modified(report, "summary")

    if report.task is not None:
        task_payload = dict(report.task.result_payload or {})
        task_payload["lineage_summary"] = after_summary
        normalized = dict(task_payload.get("normalized_result") or {})
        if normalized:
            normalized["lineage_summary"] = after_summary
            task_payload["normalized_result"] = normalized
        report.task.result_payload = task_payload
        flag_modified(report.task, "result_payload")

    session.flush()
    return result


def _check_report14_guard(
    *,
    report: BacktestReportModel,
    trades: list[BacktestTradeModel],
    orders: list[BacktestOrderModel],
    before_summary: dict[str, Any],
) -> None:
    if report.id != STAGE13G_REPORT_ID:
        raise ValueError(f"Stage 13-G repair is locked to report_id={STAGE13G_REPORT_ID}")
    if len(trades) != STAGE13G_EXPECTED_TRADE_COUNT:
        raise ValueError(f"unexpected trade count for report 14: {len(trades)}")
    if len(orders) != STAGE13G_EXPECTED_ORDER_COUNT:
        raise ValueError(f"unexpected order count for report 14: {len(orders)}")
    if before_summary.get("partial_trades") != STAGE13G_EXPECTED_PARTIAL_TRADES:
        raise ValueError(f"unexpected partial_trades before repair: {before_summary.get('partial_trades')}")
    if before_summary.get("unmapped_orders") != STAGE13G_EXPECTED_UNMAPPED_ORDERS:
        raise ValueError(f"unexpected unmapped_orders before repair: {before_summary.get('unmapped_orders')}")


def _lineage_summary(report: BacktestReportModel) -> dict[str, Any]:
    summary = (report.summary or {}).get("lineage_summary")
    return dict(summary) if isinstance(summary, dict) else {}


def _strategy_execution_events(report: BacktestReportModel) -> list[dict[str, Any]]:
    payload = report.task.result_payload if report.task is not None else {}
    normalized = payload.get("normalized_result") if isinstance(payload, dict) else None
    events = normalized.get("strategy_execution_events") if isinstance(normalized, dict) else None
    return [dict(item) for item in events] if isinstance(events, list) else []


def _trade_payload(trade: BacktestTradeModel) -> dict[str, Any]:
    payload = dict(trade.raw_payload or {})
    payload.update(
        {
            "tradeid": trade.trade_no,
            "trade_id": trade.trade_no,
            "trade_no": trade.trade_no,
            "sequence": trade.sequence,
            "symbol": trade.contract or trade.symbol,
            "exchange": trade.exchange,
            "direction": trade.direction,
            "entry_signal_time": _iso(trade.entry_signal_time),
            "entry_signal_source": trade.entry_signal_source,
            "entry_order_no": trade.entry_order_no,
            "entry_datetime": _iso(trade.open_time),
            "entry_time": _iso(trade.open_time),
            "open_time": _iso(trade.open_time),
            "entry_price": trade.open_price,
            "open_price": trade.open_price,
            "exit_signal_time": _iso(trade.exit_signal_time),
            "exit_signal_source": trade.exit_signal_source,
            "exit_order_no": trade.exit_order_no,
            "exit_datetime": _iso(trade.close_time),
            "exit_time": _iso(trade.close_time),
            "close_time": _iso(trade.close_time),
            "exit_price": trade.close_price,
            "close_price": trade.close_price,
            "volume": trade.volume,
            "contract_multiplier": trade.contract_multiplier,
            "price_tick": trade.price_tick,
            "gross_pnl": trade.gross_pnl,
            "commission": trade.commission,
            "slippage": trade.slippage,
            "net_pnl": trade.net_pnl,
            "holding_bars": trade.holding_bars,
            "exit_reason": trade.exit_reason,
            "lineage_status": trade.lineage_status,
        }
    )
    return {key: value for key, value in payload.items() if value is not None}


def _order_payload(order: BacktestOrderModel) -> dict[str, Any]:
    payload = dict(order.raw_payload or {})
    payload.update(
        {
            "orderid": order.order_no,
            "order_id": order.order_no,
            "order_no": order.order_no,
            "trade_no": order.trade_no,
            "leg": order.leg,
            "symbol": order.contract or order.symbol,
            "direction": order.direction,
            "offset": order.offset,
            "datetime": _iso(order.order_time),
            "order_time": _iso(order.order_time),
            "price": order.price,
            "volume": order.volume,
            "traded": order.traded,
            "lineage_source": order.lineage_source,
            "mapping_status": order.mapping_status,
        }
    )
    return {key: value for key, value in payload.items() if value is not None}


def _apply_trade_mapping(trade: BacktestTradeModel, mapped: dict[str, Any]) -> None:
    trade.entry_signal_source = _optional_str(mapped.get("entry_signal_source"))
    trade.entry_order_no = _optional_str(mapped.get("entry_order_no"))
    trade.exit_signal_source = _optional_str(mapped.get("exit_signal_source"))
    trade.exit_order_no = _optional_str(mapped.get("exit_order_no"))
    trade.lineage_status = _optional_str(mapped.get("lineage_status"))
    payload = dict(trade.raw_payload or {})
    for key in ("entry_signal_source", "entry_order_no", "exit_signal_source", "lineage_status"):
        if mapped.get(key) is not None:
            payload[key] = mapped[key]
    if mapped.get("exit_order_no") is not None:
        payload["exit_order_no"] = mapped["exit_order_no"]
    else:
        payload.pop("exit_order_no", None)
    trade.raw_payload = payload
    flag_modified(trade, "raw_payload")


def _apply_order_mapping(order: BacktestOrderModel, mapped: dict[str, Any]) -> None:
    order.trade_no = _optional_str(mapped.get("trade_no"))
    order.leg = _optional_str(mapped.get("leg"))
    order.lineage_source = _optional_str(mapped.get("lineage_source"))
    order.mapping_status = _optional_str(mapped.get("mapping_status"))
    payload = dict(order.raw_payload or {})
    for key in ("trade_no", "leg", "lineage_source", "mapping_status"):
        if mapped.get(key) is not None:
            payload[key] = mapped[key]
    order.raw_payload = payload
    flag_modified(order, "raw_payload")


def _optional_str(value: Any) -> str | None:
    return None if value in (None, "") else str(value)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(tzinfo=None).isoformat()


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage 13-G controlled repair for report_id=14 lineage mapping")
    parser.add_argument("--report-id", type=int, default=STAGE13G_REPORT_ID)
    parser.add_argument("--dry-run", action="store_true", help="Preview the repair without writing DB; this is the default.")
    parser.add_argument("--apply", action="store_true", help="Write lineage fields after all report 14 guards pass.")
    parser.add_argument("--confirm-stage13g-report14-lineage-repair", action="store_true")
    args = parser.parse_args()
    if args.dry_run and args.apply:
        parser.error("--dry-run and --apply are mutually exclusive")

    with SessionLocal() as session:
        result = repair_report_lineage(
            session,
            report_id=args.report_id,
            apply=args.apply,
            confirm=args.confirm_stage13g_report14_lineage_repair,
            strict_report14_guard=True,
        )
        if args.apply:
            session.commit()
        else:
            session.rollback()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
