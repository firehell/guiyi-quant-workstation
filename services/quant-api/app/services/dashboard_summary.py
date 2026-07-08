from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.backtest import BacktestReportModel, BacktestTask
from app.models.data_center import MarketDataFile
from app.models.signal import SignalScanTask, StrategySignal
from app.services.live_target_contracts import LiveTargetContractResolver
from app.services.strategy_registry import list_strategy_registry


def build_dashboard_summary(session: Session) -> dict[str, Any]:
    now = datetime.now(UTC)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=7)

    registry = list_strategy_registry()
    strategies_count = len(registry)
    v1b_strategies = sum(1 for item in registry if item["is_v1b"])

    signals_today = session.scalar(
        select(func.count()).select_from(StrategySignal).where(StrategySignal.created_at >= today_start)
    ) or 0
    signals_week = session.scalar(
        select(func.count()).select_from(StrategySignal).where(StrategySignal.created_at >= week_start)
    ) or 0

    backtest_tasks = session.scalar(select(func.count()).select_from(BacktestTask)) or 0
    backtest_reports = session.scalar(select(func.count()).select_from(BacktestReportModel)) or 0
    backtest_reports_success = session.scalar(
        select(func.count())
        .select_from(BacktestReportModel)
        .where(BacktestReportModel.status.in_(("success", "completed")))
    ) or 0

    jm_primary_passed = session.scalar(
        select(func.count())
        .select_from(MarketDataFile)
        .where(
            MarketDataFile.instrument_symbol == "jm",
            MarketDataFile.data_role == "primary",
            MarketDataFile.quality_status == "passed",
            MarketDataFile.provider.in_(("rqdata", "local_parquet")),
        )
    ) or 0

    data_contracts = session.scalar(
        select(func.count(func.distinct(MarketDataFile.contract_code))).select_from(MarketDataFile).where(
            MarketDataFile.data_role == "primary",
            MarketDataFile.quality_status != "failed",
        )
    ) or 0

    latest_scan = session.scalar(
        select(SignalScanTask).order_by(SignalScanTask.created_at.desc()).limit(1)
    )
    latest_scan_payload: dict[str, Any] | None = None
    if latest_scan is not None:
        latest_scan_payload = {
            "task_no": latest_scan.task_no,
            "status": latest_scan.status,
            "progress": latest_scan.progress,
            "watchlist_code": latest_scan.watchlist_code,
            "created_at": latest_scan.created_at.isoformat() if latest_scan.created_at else None,
        }

    live_targets = LiveTargetContractResolver(session).list_targets()

    latest_jm_report = session.scalar(
        select(BacktestReportModel)
        .where(BacktestReportModel.symbol.ilike("jm%"))
        .order_by(BacktestReportModel.created_at.desc())
        .limit(1)
    )
    latest_jm_report_payload: dict[str, Any] | None = None
    if latest_jm_report is not None:
        latest_jm_report_payload = {
            "report_id": latest_jm_report.id,
            "report_no": latest_jm_report.report_no,
            "strategy_code": latest_jm_report.strategy_code,
            "status": latest_jm_report.status,
            "created_at": latest_jm_report.created_at.isoformat() if latest_jm_report.created_at else None,
        }

    return {
        "data_status": "live",
        "risk_status": "research_only",
        "strategies": strategies_count,
        "v1b_strategies": v1b_strategies,
        "signals_today": signals_today,
        "signals_week": signals_week,
        "backtests": backtest_tasks,
        "backtest_reports": backtest_reports,
        "backtest_reports_success": backtest_reports_success,
        "data_contracts": data_contracts,
        "jm_primary_passed_assets": jm_primary_passed,
        "live_target_readiness": live_targets.get("readiness_status"),
        "live_targets_preview_only": live_targets.get("preview_only", True),
        "latest_scan_task": latest_scan_payload,
        "latest_jm_report": latest_jm_report_payload,
        "generated_at": now.isoformat(),
    }
