from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.backtest import BacktestReportModel, BacktestTask
from app.models.data_center import LiveAggregationCheckpoint, LiveIngestCheckpoint, MarketDataFile
from app.models.review import ReviewNote
from app.models.signal import SignalEvent, SignalScanTask, StrategySignal
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

    latest_data_time = session.scalar(
        select(func.max(MarketDataFile.end_time)).where(
            MarketDataFile.data_role == "primary",
            MarketDataFile.quality_status != "failed",
            MarketDataFile.provider.in_(("rqdata", "local_parquet")),
        )
    )
    latest_ingest_bar = session.scalar(select(func.max(LiveIngestCheckpoint.last_confirmed_bar_at)))
    latest_aggregation_bar = session.scalar(select(func.max(LiveAggregationCheckpoint.last_aggregated_bar_at)))
    latest_confirmed_bar_time = max(
        (item for item in (latest_ingest_bar, latest_aggregation_bar) if item is not None),
        default=None,
    )

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

    latest_live_signal_event = session.scalar(
        select(SignalEvent)
        .where(SignalEvent.source_mode == "live_confirmed")
        .order_by(SignalEvent.signal_time.desc(), SignalEvent.id.desc())
        .limit(1)
    )
    latest_live_signal_event_payload: dict[str, Any] | None = None
    if latest_live_signal_event is not None:
        latest_live_signal_event_payload = {
            "event_id": latest_live_signal_event.id,
            "event_type": latest_live_signal_event.event_type,
            "source_mode": latest_live_signal_event.source_mode,
            "lifecycle_status": latest_live_signal_event.lifecycle_status,
            "symbol": latest_live_signal_event.symbol,
            "contract": latest_live_signal_event.contract,
            "period": latest_live_signal_event.period,
            "direction": latest_live_signal_event.direction,
            "signal_time": latest_live_signal_event.signal_time.isoformat()
            if latest_live_signal_event.signal_time
            else None,
        }

    latest_review = session.scalar(
        select(ReviewNote).order_by(ReviewNote.updated_at.desc(), ReviewNote.id.desc()).limit(1)
    )
    latest_review_payload: dict[str, Any] | None = None
    if latest_review is not None:
        latest_review_payload = {
            "review_id": latest_review.id,
            "source_type": latest_review.source_type,
            "source_id": latest_review.source_id,
            "symbol": latest_review.symbol,
            "contract": latest_review.contract,
            "period": latest_review.period,
            "review_score": latest_review.review_score,
            "updated_at": latest_review.updated_at.isoformat() if latest_review.updated_at else None,
        }
    unfinished_review_count = session.scalar(
        select(func.count())
        .select_from(ReviewNote)
        .where(or_(ReviewNote.lesson.is_(None), func.trim(ReviewNote.lesson) == ""))
    ) or 0

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
        "latest_data_time": latest_data_time.isoformat() if latest_data_time else None,
        "latest_confirmed_bar_time": latest_confirmed_bar_time.isoformat()
        if latest_confirmed_bar_time
        else None,
        "latest_live_signal_event": latest_live_signal_event_payload,
        "latest_review": latest_review_payload,
        "unfinished_review_count": unfinished_review_count,
        "generated_at": now.isoformat(),
    }
