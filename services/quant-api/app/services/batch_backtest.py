from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from statistics import median
from typing import Any
from uuid import uuid4

import duckdb
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtest.drawdown_curve_generator import generate_drawdown_curve
from app.backtest.engine import BacktestConfig, run_su_bing_backtest
from app.backtest.equity_curve_generator import generate_equity_curve
from app.backtest.report_metrics import METRIC_UNITS
from app.backtest.service import BacktestService, compute_consistency_hash
from app.backtest.specs import load_contract_spec
from app.db.session import PROJECT_ROOT
from app.models.backtest import BacktestReportModel, BacktestTask, BacktestTradeModel, Watchlist, WatchlistItem
from app.models.data_center import MarketDataFile
from app.queue import get_redis_connection
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
    asset: dict[str, Any]


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
    start = datetime.fromisoformat(str(request_payload["start"]))
    end = datetime.fromisoformat(str(request_payload["end"]))
    period = str(request_payload["period"])
    selected_symbols = set(request_payload.get("symbols") or [])
    service = BacktestService(session)
    assets: list[dict[str, Any]] = []
    profile_ids: set[str] = set()
    for item in _watchlist_items(session, str(request_payload["watchlist_code"])):
        if selected_symbols and item.symbol not in selected_symbols:
            continue
        if not item.default_contract:
            raise ValueError(f"formal batch target has no explicit contract: {item.symbol}")
        lineage, asset = service.resolve_formal_asset(
            instrument_symbol=item.symbol,
            contract_code=item.default_contract,
            period=period,
            profile_id=request_payload.get("profile_id"),
        )
        service._validate_requested_window(asset, start=start, end=end)
        if not lineage.profile_id:
            raise ValueError(f"formal batch target has no resolved profile: {item.symbol}")
        profile_ids.add(lineage.profile_id)
        assets.append(
            {
                **asset,
                "name": item.name,
                "exchange_code": item.exchange_code,
            }
        )
    if not assets:
        raise ValueError("formal batch request resolved no assets")
    if len(profile_ids) != 1:
        raise ValueError("formal batch assets must use one Profile")
    selected_profile_id = profile_ids.pop()
    item_count = len(assets)
    task = BacktestTask(
        task_no=f"BTB-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}",
        task_type="batch",
        engine_type="custom_v0",
        data_source="profile_binding",
        data_role="primary",
        profile_id=selected_profile_id,
        market_data_file_id=None,
        binding_snapshot={
            "schema_version": "backtest_batch_binding_snapshot_v1",
            "resolver_name": "ProfileLineageResolver",
            "resolver_contract_version": "backtest_profile_v1",
            "quality_policy": "passed_only",
            "profile_id": selected_profile_id,
            "assets": assets,
        },
        research_only=False,
        status="pending",
        progress=0.0,
        total_items=item_count * len(templates),
        request_payload={
            **request_payload,
            "profile_id": selected_profile_id,
            "parameter_templates": templates,
        },
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
        targets = self._targets(task)
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

    def _targets(self, task: BacktestTask) -> list[RunTarget]:
        snapshot = task.binding_snapshot
        if not isinstance(snapshot, dict) or snapshot.get("schema_version") != "backtest_batch_binding_snapshot_v1":
            raise ValueError("formal batch task requires immutable binding_snapshot")
        if not task.profile_id or snapshot.get("profile_id") != task.profile_id:
            raise ValueError("formal batch task profile_id does not match binding_snapshot")
        targets: list[RunTarget] = []
        for asset in snapshot.get("assets") or []:
            if not isinstance(asset, dict):
                raise ValueError("formal batch asset snapshot is invalid")
            targets.append(
                RunTarget(
                    symbol=str(asset["instrument_symbol"]),
                    name=asset.get("name"),
                    contract=str(asset["contract_code"]),
                    exchange_code=asset.get("exchange_code"),
                    asset=asset,
                )
            )
        if not targets:
            raise ValueError(f"formal batch task has no pinned assets: {task.task_no}")
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
            data_source=str(target.asset["provider"]),
            data_role="primary",
            data_version=target.asset.get("data_version"),
            profile_id=task.profile_id,
            market_data_file_id=int(target.asset["market_data_file_id"]),
            binding_snapshot=dict(target.asset),
            research_only=False,
            status="running",
            started_at=started_at,
        )
        self.session.add(report)
        self.session.flush()

        try:
            bars = self._load_pinned_bars(target.asset, start=start, end=end)
            quality = {"status": "passed", "market_data_file_id": target.asset["market_data_file_id"]}
            report.quality_status = quality
            if not bars:
                return self._skip_report(report, "no pinned formal bars found")

            config = _config_from_payload(task.request_payload, template)
            backtest_report = run_su_bing_backtest(
                bars=bars,
                config=config,
                contract_spec=load_contract_spec(self.session, target.symbol, target.contract),
            )
            payload = backtest_report.to_dict()
            score = suitability_score(payload["summary"], payload.get("warnings", []), quality)
            summary = dict(payload["summary"])
            summary["quality_status"] = quality
            consistency_hash = compute_consistency_hash(summary=summary, trades=list(payload.get("trades") or []))
            summary["consistency_hash"] = consistency_hash
            report.status = "completed"
            report.suitability_score = score["score"]
            report.suitability_label = score["label"]
            report.summary = summary
            report.consistency_hash = consistency_hash
            report.warnings = payload["warnings"]
            report.finished_at = utc_now()
            self.session.flush()
            for index, trade in enumerate(payload["trades"]):
                self.session.add(_trade_model(report, trade, index=index))
            return report
        except Exception as exc:
            report.status = "failed"
            report.error_message = str(exc)
            report.suitability_label = "数据不足"
            report.suitability_score = 0.0
            report.finished_at = utc_now()
            return report

    def _load_pinned_bars(self, asset: dict[str, Any], *, start: datetime, end: datetime) -> list[dict[str, Any]]:
        file_id = asset.get("market_data_file_id")
        if not isinstance(file_id, int):
            raise ValueError("formal batch asset has no market_data_file_id")
        market_file = self.session.get(MarketDataFile, file_id)
        if market_file is None:
            raise ValueError("formal batch pinned MarketDataFile is missing")
        for field_name, actual in {
            "instrument_symbol": market_file.instrument_symbol,
            "contract_code": market_file.contract_code,
            "period": market_file.period,
            "provider": market_file.provider,
            "data_version": market_file.data_version,
            "checksum": market_file.checksum,
        }.items():
            if asset.get(field_name) != actual:
                raise ValueError(f"formal batch pinned asset {field_name} mismatch")
        if market_file.data_role != "primary" or market_file.quality_status != "passed":
            raise ValueError("formal batch pinned asset is not primary/passed")
        path = Path(str(asset.get("file_path")))
        registered_path = Path(market_file.file_path)
        registered_path = registered_path if registered_path.is_absolute() else PROJECT_ROOT / registered_path
        if path.resolve(strict=False) != registered_path.resolve(strict=False) or not path.is_file():
            raise ValueError("formal batch pinned asset path is missing or changed")
        with duckdb.connect(database=":memory:") as connection:
            frame = connection.execute(
                "select * from read_parquet(?) where datetime >= ? and datetime <= ? order by datetime",
                [str(path), start.replace(tzinfo=None), end.replace(tzinfo=None)],
            ).fetchdf()
        required_lineage = {"data_role", "quality_status"}
        missing = required_lineage.difference(frame.columns)
        if missing:
            raise ValueError(f"formal batch bars missing lineage fields: {', '.join(sorted(missing))}")
        if not frame.empty and set(frame["data_role"].astype(str)) != {"primary"}:
            raise ValueError("formal batch bars require data_role=primary")
        if not frame.empty and set(frame["quality_status"].astype(str)) != {"passed"}:
            raise ValueError("formal batch bars require quality_status=passed")
        return list(frame.to_dict("records"))

    def _skip_report(self, report: BacktestReportModel, reason: str) -> BacktestReportModel:
        report.status = "skipped"
        report.error_message = reason
        report.suitability_label = "数据不足"
        report.suitability_score = 0.0
        summary = _empty_summary()
        summary["consistency_hash"] = compute_consistency_hash(summary=summary, trades=[])
        report.summary = summary
        report.consistency_hash = summary["consistency_hash"]
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
        "profile_id": task.profile_id,
        "market_data_file_id": task.market_data_file_id,
        "binding_snapshot": _public_lineage_snapshot(task.binding_snapshot),
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
        "profile_id": report.profile_id,
        "market_data_file_id": report.market_data_file_id,
        "binding_snapshot": _public_lineage_snapshot(report.binding_snapshot),
        "research_only": report.research_only,
        "status": report.status,
        "suitability_label": report.suitability_label,
        "suitability_score": report.suitability_score,
        "consistency_hash": report.consistency_hash,
        "initial_capital": report.initial_capital,
        "final_equity": report.final_equity,
        "total_return": report.total_return,
        "annual_return": report.annual_return,
        "max_drawdown": report.max_drawdown,
        "max_drawdown_amount": _report_max_drawdown_amount(report),
        "max_drawdown_pct": _report_max_drawdown_pct(report),
        "win_rate": report.win_rate,
        "profit_loss_ratio": report.profit_loss_ratio,
        "trade_count": report.trade_count,
        "max_consecutive_losses": report.max_consecutive_losses,
        "total_commission": report.total_commission,
        "total_slippage": report.total_slippage,
        "max_margin_required": report.max_margin_required,
        "max_margin_usage_pct": report.max_margin_usage_pct,
        "rollover_exit_count": report.rollover_exit_count,
        "delivery_risk_exit_count": report.delivery_risk_exit_count,
        "average_hold_bars": _report_average_hold_bars(report),
        "metric_units": _report_metric_units(report),
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
                "orders": [_order_payload(order) for order in report.order_rows],
                "fills": [],
                "equity_curve": _derived_equity_curve(report),
                "drawdown_curve": _derived_drawdown_curve(report),
            }
        )
    return payload


def _public_lineage_snapshot(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _public_lineage_snapshot(item)
            for key, item in value.items()
            if str(key).lower() != "file_path"
        }
    if isinstance(value, list):
        return [_public_lineage_snapshot(item) for item in value]
    return value


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


def _trade_model(report: BacktestReportModel, trade: dict[str, Any], *, index: int) -> BacktestTradeModel:
    metadata = _report_metadata(report)
    return BacktestTradeModel(
        report_id=report.id,
        trade_no=trade["trade_no"],
        sequence=int(float(trade.get("sequence", index + 1) or index + 1)),
        symbol=trade["instrument_symbol"],
        exchange=str(trade.get("exchange") or metadata.get("exchange") or ""),
        research_contract=str(trade.get("research_contract") or trade.get("research_symbol") or report.contract),
        contract=trade["contract_code"],
        timeframe=str(trade.get("timeframe") or trade.get("entry_interval") or report.period),
        direction=trade["direction"],
        entry_signal_time=_parse_optional_datetime(trade.get("entry_signal_time") or trade.get("signal_time")),
        open_time=datetime.fromisoformat(trade["open_time"]),
        open_price=float(trade["open_price"]),
        exit_signal_time=_parse_optional_datetime(trade.get("exit_signal_time")),
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
        stop_loss_price=_optional_float(trade.get("stop_loss_price")),
        entry_reason=trade["entry_reason"],
        exit_reason=trade["exit_reason"],
        entry_contract=trade.get("entry_contract"),
        exit_contract=trade.get("exit_contract"),
        entry_contract_month=trade.get("entry_contract_month"),
        exit_contract_month=trade.get("exit_contract_month"),
        contract_multiplier=trade.get("contract_multiplier"),
        price_tick=trade.get("price_tick"),
        margin_ratio=trade.get("margin_ratio"),
        margin_required=trade.get("margin_required"),
        parameter_source=trade.get("parameter_source"),
        fee_rule_source=trade.get("fee_rule_source"),
        main_contract_source=trade.get("main_contract_source"),
        rollover_forced_exit=bool(trade.get("rollover_forced_exit", False)),
        delivery_risk_exit=bool(trade.get("delivery_risk_exit", False)),
        rollover_reason=trade.get("rollover_reason"),
        raw_payload=_trade_raw_payload(trade),
    )


def _trade_payload(trade: BacktestTradeModel) -> dict[str, Any]:
    payload = {
        "id": trade.id,
        "report_id": trade.report_id,
        "trade_no": trade.trade_no,
        "sequence": trade.sequence,
        "instrument_symbol": trade.symbol,
        "exchange": trade.exchange,
        "research_contract": trade.research_contract,
        "contract_code": trade.contract,
        "timeframe": trade.timeframe,
        "entry_contract": trade.entry_contract,
        "exit_contract": trade.exit_contract,
        "entry_contract_month": trade.entry_contract_month,
        "exit_contract_month": trade.exit_contract_month,
        "direction": trade.direction,
        "entry_signal_time": trade.entry_signal_time.isoformat() if trade.entry_signal_time else None,
        "entry_signal_source": trade.entry_signal_source,
        "entry_order_no": trade.entry_order_no,
        "open_time": trade.open_time.isoformat(),
        "open_price": trade.open_price,
        "exit_signal_time": trade.exit_signal_time.isoformat() if trade.exit_signal_time else None,
        "exit_signal_source": trade.exit_signal_source,
        "exit_order_no": trade.exit_order_no,
        "close_time": trade.close_time.isoformat(),
        "close_price": trade.close_price,
        "volume": trade.volume,
        "turnover": trade.turnover,
        "contract_multiplier": trade.contract_multiplier,
        "price_tick": trade.price_tick,
        "commission": trade.commission,
        "slippage": trade.slippage,
        "margin_ratio": trade.margin_ratio,
        "margin_required": trade.margin_required,
        "parameter_source": trade.parameter_source,
        "fee_rule_source": trade.fee_rule_source,
        "main_contract_source": trade.main_contract_source,
        "rollover_forced_exit": trade.rollover_forced_exit,
        "delivery_risk_exit": trade.delivery_risk_exit,
        "rollover_reason": trade.rollover_reason,
        "gross_pnl": trade.gross_pnl,
        "net_pnl": trade.net_pnl,
        "return_pct": trade.return_pct,
        "holding_bars": trade.holding_bars,
        "stop_loss_price": trade.stop_loss_price,
        "entry_reason": trade.entry_reason,
        "exit_reason": trade.exit_reason,
        "lineage_status": trade.lineage_status,
    }
    if trade.raw_payload:
        payload["raw_payload"] = trade.raw_payload
    return payload


def _report_max_drawdown_pct(report: BacktestReportModel) -> float:
    return float(report.max_drawdown_pct or 0.0)


def _report_max_drawdown_amount(report: BacktestReportModel) -> float:
    return float(report.max_drawdown_amount or 0.0)


def _report_average_hold_bars(report: BacktestReportModel) -> float | None:
    summary = report.summary or {}
    value = summary.get("average_hold_bars")
    if value is not None:
        try:
            return float(value)
        except (TypeError, ValueError):
            pass
    values: list[float] = []
    for trade in report.trades:
        if trade.holding_bars is not None:
            values.append(float(trade.holding_bars))
            continue
        raw_payload = trade.raw_payload or {}
        for key in ("holding_bars", "hold_bars"):
            if raw_payload.get(key) is not None:
                try:
                    values.append(float(raw_payload[key]))
                except (TypeError, ValueError):
                    pass
                break
    return sum(values) / len(values) if values else None


def _report_metric_units(report: BacktestReportModel) -> dict[str, str]:
    summary = report.summary or {}
    value = summary.get("metric_units")
    if isinstance(value, dict):
        return {str(key): str(item) for key, item in value.items()}
    return dict(METRIC_UNITS)


def _order_payload(order: Any) -> dict[str, Any]:
    return {
        "order_no": order.order_no,
        "trade_no": order.trade_no,
        "leg": order.leg,
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
        "lineage_source": order.lineage_source,
        "mapping_status": order.mapping_status,
        "raw_payload": order.raw_payload,
    }


def _derived_equity_curve(report: BacktestReportModel) -> list[dict[str, Any]]:
    return generate_equity_curve([_trade_curve_mapping(trade) for trade in report.trades], initial_capital=report.initial_capital)


def _derived_drawdown_curve(report: BacktestReportModel) -> list[dict[str, Any]]:
    return generate_drawdown_curve(_derived_equity_curve(report))["drawdown_curve"]


def _trade_curve_mapping(trade: BacktestTradeModel) -> dict[str, Any]:
    return {
        "trade_id": trade.trade_no,
        "trade_no": trade.trade_no,
        "sequence": trade.sequence,
        "exit_time": trade.close_time,
        "gross_pnl": trade.gross_pnl,
        "commission": trade.commission,
        "slippage": trade.slippage,
        "net_pnl": trade.net_pnl,
    }


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


def _report_metadata(report: BacktestReportModel) -> dict[str, Any]:
    summary = report.summary or {}
    metadata = summary.get("report_metadata")
    return metadata if isinstance(metadata, dict) else {}


def _parse_optional_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _trade_raw_payload(trade: dict[str, Any]) -> dict[str, Any]:
    curve_keys = {
        "balance",
        "balance_curve",
        "daily_results",
        "drawdown",
        "drawdown_curve",
        "drawdown_pct",
        "equity",
        "equity_after_trade",
        "equity_curve",
        "peak_equity",
    }
    return {str(key): value for key, value in dict(trade).items() if str(key) not in curve_keys}


def _channel(task_no: str) -> str:
    return f"backtests:{task_no}"


def utc_now() -> datetime:
    return datetime.now(UTC)
