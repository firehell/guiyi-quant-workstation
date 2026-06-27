from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from statistics import median
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtest.engine import BacktestConfig, run_su_bing_backtest
from app.backtest.specs import load_contract_spec
from app.models.backtest import BacktestReportModel, BacktestTask, BacktestTradeModel, Watchlist, WatchlistItem
from app.queue import get_redis_connection
from app.services.market_data_reader import MarketDataReader
from app.strategy.su_bing_ema21 import SuBingParams

WATCHLIST_DEFINITIONS = {
    "black": {
        "name": "黑色池",
        "description": "黑色系趋势/波段研究品种",
        "items": [
            ("rb", "螺纹", "SHFE", "rb.MAIN"),
            ("hc", "热卷", "SHFE", "hc.MAIN"),
            ("i", "铁矿", "DCE", "i.MAIN"),
            ("jm", "焦煤", "DCE", "jm.MAIN"),
            ("j", "焦炭", "DCE", "j.MAIN"),
        ],
    },
    "chemical": {
        "name": "化工池",
        "description": "化工系趋势/波段研究品种",
        "items": [
            ("TA", "PTA", "CZCE", "TA.MAIN"),
            ("MA", "甲醇", "CZCE", "MA.MAIN"),
            ("l", "塑料", "DCE", "l.MAIN"),
            ("pp", "PP", "DCE", "pp.MAIN"),
            ("v", "PVC", "DCE", "v.MAIN"),
            ("SA", "纯碱", "CZCE", "SA.MAIN"),
            ("FG", "玻璃", "CZCE", "FG.MAIN"),
        ],
    },
    "energy": {
        "name": "能源池",
        "description": "能源系趋势/波段研究品种",
        "items": [
            ("sc", "原油", "INE", "sc.MAIN"),
            ("fu", "燃油", "SHFE", "fu.MAIN"),
            ("bu", "沥青", "SHFE", "bu.MAIN"),
            ("pg", "LPG", "DCE", "pg.MAIN"),
        ],
    },
}

DEFAULT_PARAMETER_TEMPLATES = [
    {"name": "default", "label": "默认", "strategy_params": {}, "overrides": {}},
    {
        "name": "strict",
        "label": "严格共振",
        "strategy_params": {"confluence_threshold": 4, "max_distance_from_ema_atr": 1.2},
        "overrides": {"risk_per_trade_pct": 0.008},
    },
    {
        "name": "loose",
        "label": "宽松试单",
        "strategy_params": {"confluence_threshold": 2, "max_distance_from_ema_atr": 2.0},
        "overrides": {"risk_per_trade_pct": 0.006},
    },
]


@dataclass(frozen=True)
class RunTarget:
    symbol: str
    name: str | None
    contract: str
    exchange_code: str | None


def ensure_default_watchlists(session: Session) -> None:
    existing_codes = set(session.scalars(select(Watchlist.code)))
    for code, definition in WATCHLIST_DEFINITIONS.items():
        if code not in existing_codes:
            session.add(
                Watchlist(
                    code=code,
                    name=definition["name"],
                    category="futures",
                    description=definition["description"],
                    is_active=True,
                )
            )
    session.flush()

    existing_items = {
        (item.watchlist_code, item.symbol)
        for item in session.scalars(select(WatchlistItem).where(WatchlistItem.watchlist_code.in_(WATCHLIST_DEFINITIONS)))
    }
    for code, definition in WATCHLIST_DEFINITIONS.items():
        for index, (symbol, name, exchange, contract) in enumerate(definition["items"], start=1):
            if (code, symbol) in existing_items:
                continue
            session.add(
                WatchlistItem(
                    watchlist_code=code,
                    symbol=symbol,
                    name=name,
                    exchange_code=exchange,
                    default_contract=contract,
                    sort_order=index * 10,
                    is_active=True,
                    extra={},
                )
            )


def create_batch_task(session: Session, request_payload: dict[str, Any]) -> BacktestTask:
    ensure_default_watchlists(session)
    templates = _templates(request_payload)
    item_count = len(_watchlist_items(session, str(request_payload["watchlist_code"])))
    task = BacktestTask(
        task_no=f"BTB-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}",
        task_type="batch",
        status="pending",
        progress=0.0,
        total_items=item_count * len(templates),
        request_payload={**request_payload, "parameter_templates": templates},
        result_payload={},
    )
    session.add(task)
    session.flush()
    return task


def enqueue_batch_task(task_id: int) -> str:
    from app.tasks.backtests import run_batch_backtest_task

    job = get_redis_connection()
    job.ping()
    from app.queue import get_backtest_queue

    queued = get_backtest_queue().enqueue(run_batch_backtest_task, task_id, job_timeout="12h", result_ttl=86400)
    return queued.id


class BatchBacktestRunner:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.reader = MarketDataReader(session)

    def run(self, task_id: int) -> dict[str, Any]:
        task = self.session.get(BacktestTask, task_id)
        if task is None:
            raise ValueError(f"backtest task not found: {task_id}")

        task.status = "running"
        task.started_at = utc_now()
        self.session.commit()
        self._publish(task, "started")

        try:
            result = self._run_task(task)
            task.result_payload = result
            task.status = "partial_failed" if task.failed_items or task.skipped_items else "completed"
            task.progress = 100.0
            task.finished_at = utc_now()
            self.session.commit()
            self._publish(task, "completed")
            return result
        except Exception as exc:
            task.status = "failed"
            task.error_message = str(exc)
            task.finished_at = utc_now()
            self.session.commit()
            self._publish(task, "failed", {"error_message": str(exc)})
            raise

    def _run_task(self, task: BacktestTask) -> dict[str, Any]:
        payload = task.request_payload
        start = datetime.fromisoformat(str(payload["start"]))
        end = datetime.fromisoformat(str(payload["end"]))
        if start >= end:
            raise ValueError("start must be before end")

        templates = _templates(payload)
        targets = self._targets(str(payload["watchlist_code"]), str(payload["period"]), start, end, payload.get("symbols"))
        total = max(1, len(targets) * len(templates))
        task.total_items = total
        self.session.commit()

        for target in targets:
            for template in templates:
                report = self._run_one(task=task, target=target, template=template, start=start, end=end)
                if report.status == "completed":
                    task.completed_items += 1
                elif report.status == "skipped":
                    task.skipped_items += 1
                else:
                    task.failed_items += 1
                done = task.completed_items + task.failed_items + task.skipped_items
                task.progress = round(done / total * 100, 2)
                self.session.commit()
                self._publish(
                    task,
                    "item_completed" if report.status == "completed" else "item_failed",
                    {"report_id": report.id, "symbol": report.symbol, "template_name": report.template_name, "status": report.status},
                )

        return self._aggregate(task)

    def _targets(
        self,
        watchlist_code: str,
        period: str,
        start: datetime,
        end: datetime,
        selected_symbols: list[str] | None,
    ) -> list[RunTarget]:
        symbols = set(selected_symbols or [])
        targets: list[RunTarget] = []
        for item in _watchlist_items(self.session, watchlist_code):
            if symbols and item.symbol not in symbols:
                continue
            coverage = [row for row in self.reader.get_coverage(symbol=item.symbol, period=period) if row.start_time <= end and row.end_time >= start]
            if not coverage:
                contract = item.default_contract or f"{item.symbol}.MAIN"
                targets.append(RunTarget(symbol=item.symbol, name=item.name, contract=contract, exchange_code=item.exchange_code))
                continue
            preferred = next((row for row in coverage if row.contract_code == item.default_contract), coverage[0])
            targets.append(
                RunTarget(
                    symbol=item.symbol,
                    name=item.name,
                    contract=preferred.contract_code or item.default_contract or f"{item.symbol}.MAIN",
                    exchange_code=preferred.file_path.split("exchange=")[-1].split("/")[0] if "exchange=" in preferred.file_path else item.exchange_code,
                )
            )
        if not targets:
            raise ValueError(f"watchlist has no active items: {watchlist_code}")
        return targets

    def _run_one(
        self,
        task: BacktestTask,
        target: RunTarget,
        template: dict[str, Any],
        start: datetime,
        end: datetime,
    ) -> BacktestReportModel:
        started_at = utc_now()
        report = BacktestReportModel(
            task_id=task.id,
            task_no=task.task_no,
            report_no=f"{task.task_no}-{target.symbol}-{template['name']}",
            template_name=str(template["name"]),
            template_label=template.get("label"),
            symbol=target.symbol,
            contract=target.contract,
            period=str(task.request_payload["period"]),
            status="running",
            started_at=started_at,
        )
        self.session.add(report)
        self.session.flush()

        try:
            quality = self.reader.get_quality_status(
                symbol=target.symbol,
                contract=target.contract,
                period=str(task.request_payload["period"]),
                start=start,
                end=end,
                provider=task.request_payload.get("provider"),
            )
            report.quality_status = quality
            if quality["status"] == "failed":
                return self._skip_report(report, "data quality failed; skipped")
            if quality["status"] == "warning" and not task.request_payload.get("allow_warning_quality", False):
                return self._skip_report(report, "data quality warning requires allow_warning_quality=true")

            bars = self.reader.load_bars(
                symbol=target.symbol,
                contract=target.contract,
                period=str(task.request_payload["period"]),
                start=start,
                end=end,
                provider=task.request_payload.get("provider"),
            )
            if not bars:
                return self._skip_report(report, "no canonical bars found")

            config = _config_from_payload(task.request_payload, template)
            backtest_report = run_su_bing_backtest(
                bars=bars,
                config=config,
                contract_spec=load_contract_spec(self.session, target.symbol, target.contract),
            )
            payload = backtest_report.to_dict()
            score = suitability_score(payload["summary"], payload.get("warnings", []), quality)
            report.status = "completed"
            report.suitability_score = score["score"]
            report.suitability_label = score["label"]
            report.summary = payload["summary"]
            report.warnings = payload["warnings"]
            report.orders = payload["orders"]
            report.fills = payload["fills"]
            report.equity_curve = payload["equity_curve"]
            report.drawdown_curve = payload["drawdown_curve"]
            report.finished_at = utc_now()
            self.session.flush()
            for trade in payload["trades"]:
                self.session.add(_trade_model(report.id, trade))
            return report
        except Exception as exc:
            report.status = "failed"
            report.error_message = str(exc)
            report.suitability_label = "数据不足"
            report.suitability_score = 0.0
            report.finished_at = utc_now()
            return report

    def _skip_report(self, report: BacktestReportModel, reason: str) -> BacktestReportModel:
        report.status = "skipped"
        report.error_message = reason
        report.suitability_label = "数据不足"
        report.suitability_score = 0.0
        report.summary = _empty_summary()
        report.warnings = [reason]
        report.finished_at = utc_now()
        return report

    def _aggregate(self, task: BacktestTask) -> dict[str, Any]:
        reports = list(self.session.scalars(select(BacktestReportModel).where(BacktestReportModel.task_id == task.id)))
        completed = [report for report in reports if report.status == "completed"]
        by_template: dict[str, list[BacktestReportModel]] = {}
        for report in completed:
            by_template.setdefault(report.template_name, []).append(report)

        template_stats = []
        for template_name, rows in by_template.items():
            returns = [float(row.summary.get("total_return", 0.0)) for row in rows]
            drawdowns = [float(row.summary.get("max_drawdown", 0.0)) for row in rows]
            template_stats.append(
                {
                    "template_name": template_name,
                    "count": len(rows),
                    "average_return": sum(returns) / len(returns) if returns else 0.0,
                    "median_max_drawdown": median(drawdowns) if drawdowns else 0.0,
                    "average_score": sum(row.suitability_score for row in rows) / len(rows) if rows else 0.0,
                    "suitable_count": len([row for row in rows if row.suitability_label == "适合"]),
                }
            )

        return {
            "total_reports": len(reports),
            "completed_reports": len(completed),
            "failed_reports": len([report for report in reports if report.status == "failed"]),
            "skipped_reports": len([report for report in reports if report.status == "skipped"]),
            "template_stats": sorted(template_stats, key=lambda item: item["average_score"], reverse=True),
            "top_symbols": [
                {
                    "symbol": report.symbol,
                    "contract": report.contract,
                    "template_name": report.template_name,
                    "suitability_label": report.suitability_label,
                    "suitability_score": report.suitability_score,
                    "total_return": report.summary.get("total_return", 0.0),
                    "max_drawdown": report.summary.get("max_drawdown", 0.0),
                    "total_trades": report.summary.get("total_trades", 0),
                }
                for report in sorted(completed, key=lambda row: row.suitability_score, reverse=True)[:20]
            ],
        }

    def _publish(self, task: BacktestTask, event: str, extra: dict[str, Any] | None = None) -> None:
        payload = {"type": event, "data": task_snapshot(task)}
        if extra:
            payload["data"].update(extra)
        try:
            get_redis_connection().publish(_channel(task.task_no), json.dumps(payload, default=str, ensure_ascii=False))
        except Exception:
            return


def task_snapshot(task: BacktestTask) -> dict[str, Any]:
    return {
        "id": task.id,
        "task_no": task.task_no,
        "status": task.status,
        "progress": task.progress,
        "total_items": task.total_items,
        "completed_items": task.completed_items,
        "failed_items": task.failed_items,
        "skipped_items": task.skipped_items,
        "error_message": task.error_message,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
        "result_payload": task.result_payload,
    }


def report_payload(report: BacktestReportModel, include_detail: bool = False) -> dict[str, Any]:
    payload = {
        "id": report.id,
        "task_no": report.task_no,
        "report_no": report.report_no,
        "template_name": report.template_name,
        "template_label": report.template_label,
        "engine_type": report.engine_type,
        "engine_version": report.engine_version,
        "strategy_code": report.strategy_code,
        "strategy_version": report.strategy_version,
        "symbol": report.symbol,
        "contract": report.contract,
        "period": report.period,
        "data_source": report.data_source,
        "data_role": report.data_role,
        "data_version": report.data_version,
        "research_only": report.research_only,
        "status": report.status,
        "suitability_label": report.suitability_label,
        "suitability_score": report.suitability_score,
        "initial_capital": report.initial_capital,
        "final_equity": report.final_equity,
        "total_return": report.total_return,
        "annual_return": report.annual_return,
        "max_drawdown": report.max_drawdown,
        "max_drawdown_pct": _report_max_drawdown_pct(report),
        "win_rate": report.win_rate,
        "profit_loss_ratio": report.profit_loss_ratio,
        "trade_count": report.trade_count,
        "max_consecutive_losses": report.max_consecutive_losses,
        "total_commission": report.total_commission,
        "total_slippage": report.total_slippage,
        "quality_status": report.quality_status,
        "summary": report.summary,
        "warnings": report.warnings,
        "error_message": report.error_message,
        "created_at": report.created_at.isoformat() if report.created_at else None,
        "started_at": report.started_at.isoformat() if report.started_at else None,
        "finished_at": report.finished_at.isoformat() if report.finished_at else None,
    }
    if include_detail:
        payload.update(
            {
                "trades": [_trade_payload(trade) for trade in report.trades],
                "orders": [_order_payload(order) for order in report.order_rows] or report.orders,
                "fills": report.fills,
                "equity_curve": [_equity_payload(point) for point in report.equity_points] or report.equity_curve,
                "drawdown_curve": [_drawdown_payload(point) for point in report.drawdown_points] or report.drawdown_curve,
            }
        )
    return payload


def suitability_score(summary: dict[str, Any], warnings: list[str], quality: dict[str, Any]) -> dict[str, Any]:
    trades = int(summary.get("total_trades", 0) or 0)
    if trades < 3:
        return {"score": 0.0, "label": "数据不足"}

    total_return = float(summary.get("total_return", 0.0) or 0.0)
    max_drawdown = float(summary.get("max_drawdown", 0.0) or 0.0)
    win_rate = float(summary.get("win_rate", 0.0) or 0.0)
    pl_ratio = float(summary.get("profit_loss_ratio", 0.0) or 0.0)
    expectancy = float(summary.get("expectancy", 0.0) or 0.0)
    max_losses = int(summary.get("max_consecutive_losses", 0) or 0)
    costs = float(summary.get("total_commission", 0.0) or 0.0) + float(summary.get("total_slippage", 0.0) or 0.0)
    ending_equity = float(summary.get("ending_equity", 0.0) or 0.0)
    cost_ratio = costs / ending_equity if ending_equity > 0 else 0.0

    score = 50.0
    score += max(-25.0, min(30.0, total_return * 120))
    score -= min(25.0, max_drawdown * 120)
    score += min(15.0, win_rate * 20)
    score += min(12.0, pl_ratio * 4)
    score += 8.0 if expectancy > 0 else -10.0
    score += min(8.0, trades / 5)
    score -= min(10.0, max_losses * 1.2)
    score -= min(8.0, cost_ratio * 100)
    if quality.get("status") == "warning":
        score -= 8.0
    if warnings:
        score -= min(6.0, len(warnings) * 1.5)

    score = round(max(0.0, min(100.0, score)), 2)
    if score >= 70:
        label = "适合"
    elif score >= 50:
        label = "观察"
    else:
        label = "不适合"
    return {"score": score, "label": label}


def _watchlist_items(session: Session, watchlist_code: str) -> list[WatchlistItem]:
    return list(
        session.scalars(
            select(WatchlistItem)
            .where(WatchlistItem.watchlist_code == watchlist_code, WatchlistItem.is_active.is_(True))
            .order_by(WatchlistItem.sort_order, WatchlistItem.symbol)
        )
    )


def _templates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("parameter_templates") or DEFAULT_PARAMETER_TEMPLATES
    return [
        {
            "name": str(row.get("name") or "default"),
            "label": row.get("label") or row.get("name") or "默认",
            "strategy_params": row.get("strategy_params") or {},
            "overrides": row.get("overrides") or {},
        }
        for row in rows
    ]


def _config_from_payload(payload: dict[str, Any], template: dict[str, Any]) -> BacktestConfig:
    overrides = template.get("overrides") or {}
    strategy_params = {**(payload.get("strategy_params") or {}), **(template.get("strategy_params") or {})}
    return BacktestConfig(
        initial_capital=float(overrides.get("initial_capital", payload.get("initial_capital", 100000.0))),
        risk_per_trade_pct=float(overrides.get("risk_per_trade_pct", payload.get("risk_per_trade_pct", 0.01))),
        max_margin_usage_pct=float(overrides.get("max_margin_usage_pct", payload.get("max_margin_usage_pct", 0.35))),
        slippage_ticks=int(overrides.get("slippage_ticks", payload.get("slippage_ticks", 1))),
        take_profit_r=float(overrides.get("take_profit_r", payload.get("take_profit_r", 2.0))),
        enable_take_profit=bool(overrides.get("enable_take_profit", payload.get("enable_take_profit", True))),
        strategy_params=SuBingParams(**strategy_params),
    )


def _trade_model(report_id: int, trade: dict[str, Any]) -> BacktestTradeModel:
    return BacktestTradeModel(
        report_id=report_id,
        trade_no=trade["trade_no"],
        symbol=trade["instrument_symbol"],
        contract=trade["contract_code"],
        direction=trade["direction"],
        open_time=datetime.fromisoformat(trade["open_time"]),
        open_price=float(trade["open_price"]),
        close_time=datetime.fromisoformat(trade["close_time"]),
        close_price=float(trade["close_price"]),
        volume=int(trade["volume"]),
        turnover=float(trade["turnover"]),
        commission=float(trade["commission"]),
        slippage=float(trade["slippage"]),
        gross_pnl=float(trade["gross_pnl"]),
        net_pnl=float(trade["net_pnl"]),
        return_pct=float(trade["return_pct"]),
        holding_bars=int(trade["holding_bars"]),
        entry_reason=trade["entry_reason"],
        exit_reason=trade["exit_reason"],
    )


def _trade_payload(trade: BacktestTradeModel) -> dict[str, Any]:
    payload = {
        "id": trade.id,
        "report_id": trade.report_id,
        "trade_no": trade.trade_no,
        "instrument_symbol": trade.symbol,
        "contract_code": trade.contract,
        "direction": trade.direction,
        "open_time": trade.open_time.isoformat(),
        "open_price": trade.open_price,
        "close_time": trade.close_time.isoformat(),
        "close_price": trade.close_price,
        "volume": trade.volume,
        "turnover": trade.turnover,
        "commission": trade.commission,
        "slippage": trade.slippage,
        "gross_pnl": trade.gross_pnl,
        "net_pnl": trade.net_pnl,
        "return_pct": trade.return_pct,
        "holding_bars": trade.holding_bars,
        "entry_reason": trade.entry_reason,
        "exit_reason": trade.exit_reason,
    }
    if trade.raw_payload:
        payload["raw_payload"] = trade.raw_payload
    return payload


def _report_max_drawdown_pct(report: BacktestReportModel) -> float:
    values = [
        float(point.drawdown_pct)
        for point in report.drawdown_points
        if point.drawdown_pct is not None
    ]
    if values:
        return max(values, key=abs)
    raw_points = report.drawdown_curve or []
    raw_values = []
    for point in raw_points:
        if not isinstance(point, dict):
            continue
        value = point.get("drawdown_pct") if point.get("drawdown_pct") is not None else point.get("ddpercent")
        if value is None:
            continue
        try:
            raw_values.append(float(value))
        except (TypeError, ValueError):
            continue
    return max(raw_values, key=abs) if raw_values else 0.0


def _order_payload(order: Any) -> dict[str, Any]:
    return {
        "order_no": order.order_no,
        "instrument_symbol": order.symbol,
        "contract_code": order.contract,
        "direction": order.direction,
        "offset": order.offset,
        "type": order.order_type,
        "status": order.status,
        "datetime": order.order_time.isoformat() if order.order_time else None,
        "price": order.price,
        "volume": order.volume,
        "traded": order.traded,
        "raw_payload": order.raw_payload,
    }


def _equity_payload(point: Any) -> dict[str, Any]:
    payload = dict(point.raw_payload or {})
    payload.setdefault("datetime", point.point_time.isoformat() if point.point_time else None)
    payload.setdefault("equity", point.equity)
    payload["point_index"] = point.point_index
    return payload


def _drawdown_payload(point: Any) -> dict[str, Any]:
    payload = dict(point.raw_payload or {})
    payload.setdefault("datetime", point.point_time.isoformat() if point.point_time else None)
    payload.setdefault("drawdown", point.drawdown)
    payload.setdefault("drawdown_pct", point.drawdown_pct)
    payload["point_index"] = point.point_index
    return payload


def _empty_summary() -> dict[str, Any]:
    return {
        "initial_capital": 0.0,
        "ending_equity": 0.0,
        "total_return": 0.0,
        "annual_return": 0.0,
        "max_drawdown": 0.0,
        "max_drawdown_amount": 0.0,
        "win_rate": 0.0,
        "profit_loss_ratio": 0.0,
        "expectancy": 0.0,
        "max_consecutive_losses": 0,
        "total_commission": 0.0,
        "total_slippage": 0.0,
        "total_trades": 0,
        "total_orders": 0,
        "filled_orders": 0,
        "rejected_orders": 0,
    }


def _channel(task_no: str) -> str:
    return f"backtests:{task_no}"


def utc_now() -> datetime:
    return datetime.now(UTC)
