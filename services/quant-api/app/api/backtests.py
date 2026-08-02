from __future__ import annotations

import csv
from io import StringIO
import json
from datetime import UTC, date, datetime, time
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.orm import Session

from app.backtest.errors import BacktestContractError
from app.data_core.contracts import DataCoreError
from app.backtest.service import BacktestService
from app.backtest.engine import BacktestConfig, run_su_bing_backtest
from app.backtest.specs import load_contract_spec
from app.backtest.v1b_jm_tasks import (
    build_jm_daily_ema21_macd_volume_formal_request,
    build_jm_daily_score2of4_formal_request,
    build_jm_daily_trend_cross_score2_formal_request,
    build_jm_v1b_formal_request,
)
from app.db.session import PROJECT_ROOT, get_db
from app.models.backtest import BacktestReportModel, BacktestTask, BacktestTradeModel, Watchlist
from app.queue import get_backtest_queue
from app.schemas.backtest import (
    BacktestValidationContext,
    BacktestValidationContextObservation,
    FormalBacktestTaskRequest,
)
from app.services.backtest_validation_context import (
    BacktestValidationEvidenceError,
    build_backtest_validation_context,
)
from app.services.batch_backtest import (
    BatchBacktestRunner,
    create_batch_task,
    enqueue_batch_task,
    ensure_default_watchlists,
    report_payload,
    task_snapshot,
)
from app.services.market_data_reader import MarketDataReader
from app.strategy.su_bing_ema21 import SuBingParams
from app.tasks.backtests import run_backtest_task
from app.vnpy_integration.errors import BacktestConfigurationError

router = APIRouter(prefix="/api/backtests", tags=["backtests"])
watchlists_router = APIRouter(prefix="/api/watchlists", tags=["watchlists"])

BACKTEST_DISCLAIMER = "回测结果不等于实盘结果；实盘前必须经过模拟验证、小资金验证和人工风控确认。"
SUCCESS_REPORT_STATUSES = {"success", "completed"}
TRADE_SORT_COLUMNS = {
    "trade_no": BacktestTradeModel.trade_no,
    "open_time": BacktestTradeModel.open_time,
    "close_time": BacktestTradeModel.close_time,
    "net_pnl": BacktestTradeModel.net_pnl,
    "gross_pnl": BacktestTradeModel.gross_pnl,
    "volume": BacktestTradeModel.volume,
    "commission": BacktestTradeModel.commission,
    "slippage": BacktestTradeModel.slippage,
    "holding_bars": BacktestTradeModel.holding_bars,
}
TRADE_EXPORT_FIELDS = [
    "report_id",
    "trade_id",
    "order_id",
    "trade_no",
    "sequence",
    "task_id",
    "task_no",
    "strategy_code",
    "strategy_version",
    "symbol",
    "vt_symbol",
    "exchange",
    "research_contract",
    "contract",
    "entry_contract",
    "exit_contract",
    "interval",
    "timeframe",
    "datetime",
    "trading_day",
    "direction",
    "offset",
    "price",
    "volume",
    "turnover",
    "commission",
    "slippage",
    "pnl",
    "gross_pnl",
    "net_pnl",
    "balance",
    "equity_after_trade",
    "entry_price",
    "exit_price",
    "entry_signal_time",
    "entry_signal_source",
    "entry_order_no",
    "exit_signal_time",
    "exit_signal_source",
    "exit_order_no",
    "entry_datetime",
    "exit_datetime",
    "holding_bars",
    "holding_minutes",
    "stop_loss_price",
    "signal_reason",
    "entry_reason",
    "exit_reason",
    "remark",
    "note",
    "contract_multiplier",
    "price_tick",
    "margin_ratio",
    "margin_required",
    "parameter_source",
    "rollover_forced_exit",
    "delivery_risk_exit",
    "rollover_reason",
    "fee_rule_source",
    "main_contract_source",
    "lineage_status",
    "raw_payload",
]


def _contract_http_exception(exc: BacktestContractError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.payload())


class BacktestRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    contract: str
    period: str
    profile_id: str | None = None
    start: str
    end: str
    initial_capital: float = Field(default=100000.0, gt=0)
    risk_per_trade_pct: float = Field(default=0.01, gt=0, le=1)
    max_margin_usage_pct: float = Field(default=0.35, gt=0, le=1)
    slippage_ticks: int = Field(default=1, ge=0)
    take_profit_r: float = Field(default=2.0, gt=0)
    enable_take_profit: bool = True
    strategy_params: dict[str, Any] = Field(default_factory=dict)


class BacktestParameterTemplate(BaseModel):
    name: str
    label: str | None = None
    strategy_params: dict[str, Any] = Field(default_factory=dict)
    overrides: dict[str, Any] = Field(default_factory=dict)


class BatchBacktestRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    watchlist_code: str
    period: str
    start: str
    end: str
    profile_id: str | None = None
    symbols: list[str] | None = None
    initial_capital: float = Field(default=100000.0, gt=0)
    risk_per_trade_pct: float = Field(default=0.01, gt=0, le=1)
    max_margin_usage_pct: float = Field(default=0.35, gt=0, le=1)
    slippage_ticks: int = Field(default=1, ge=0)
    take_profit_r: float = Field(default=2.0, gt=0)
    enable_take_profit: bool = True
    strategy_params: dict[str, Any] = Field(default_factory=dict)
    parameter_templates: list[BacktestParameterTemplate] = Field(default_factory=list)
    run_inline: bool = False


def enqueue_backtest_task(task_id: int) -> str:
    queued = get_backtest_queue().enqueue(run_backtest_task, task_id, job_timeout="12h", result_ttl=86400)
    return queued.id


@router.post("/tasks")
def create_backtest_task(request: FormalBacktestTaskRequest, session: Session = Depends(get_db)) -> dict[str, Any]:
    service = BacktestService(session)
    try:
        task = service.create_formal_task(request)
    except BacktestContractError as exc:
        raise _contract_http_exception(exc) from exc
    except BacktestConfigurationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DataCoreError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code, "facts": dict(exc.facts)},
        ) from exc
    session.commit()

    try:
        job_id = enqueue_backtest_task(task.id)
    except Exception as exc:
        task.status = "failed"
        task.error_type = "RQUnavailable"
        task.error_message = f"Redis/RQ is unavailable; backtest task was not queued: {exc}"
        task.finished_at = datetime.now(UTC)
        session.commit()
        raise HTTPException(status_code=503, detail="Redis/RQ is unavailable; backtest task was not queued") from exc

    task.status = "queued"
    task.result_payload = {"rq_job_id": job_id}
    session.commit()
    session.refresh(task)
    return task_api_payload(task)


@router.post("/v1b/jm/daily-ema21-macd-volume/tasks")
def create_jm_daily_ema21_macd_volume_backtest_task(session: Session = Depends(get_db)) -> dict[str, Any]:
    service = BacktestService(session)
    try:
        spec = build_jm_daily_ema21_macd_volume_formal_request(session)
        task = service.create_formal_task(
            spec.request, server_context=spec.server_context
        )
        session.commit()
    except BacktestContractError as exc:
        session.rollback()
        raise _contract_http_exception(exc) from exc
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        job_id = enqueue_backtest_task(task.id)
    except Exception as exc:
        task.status = "failed"
        task.error_type = "RQUnavailable"
        task.error_message = f"Redis/RQ is unavailable; backtest task was not queued: {exc}"
        task.traceback = type(exc).__name__
        task.finished_at = datetime.now(UTC)
        session.commit()
        raise HTTPException(status_code=503, detail="Redis/RQ is unavailable; backtest task was not queued") from exc

    task.status = "queued"
    task.result_payload = {"rq_job_id": job_id, "fixed_task": "JM V1-B daily EMA21 MACD volume"}
    session.commit()
    session.refresh(task)
    payload = task_api_payload(task)
    payload["fixed_task"] = {
        "name": "JM V1-B daily EMA21 MACD volume",
        "interval": "1d",
        "strategy_code": spec.request.strategy_code,
        "strategy_version": spec.request.strategy_version,
        "result_report_id_path": "result_payload.report_id",
    }
    return _sanitize_api_payload(payload)


@router.post("/v1b/jm/daily-score2of4/tasks")
def create_jm_daily_score2of4_backtest_task(session: Session = Depends(get_db)) -> dict[str, Any]:
    service = BacktestService(session)
    try:
        spec = build_jm_daily_score2of4_formal_request(session)
        task = service.create_formal_task(
            spec.request, server_context=spec.server_context
        )
        session.commit()
    except BacktestContractError as exc:
        session.rollback()
        raise _contract_http_exception(exc) from exc
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        job_id = enqueue_backtest_task(task.id)
    except Exception as exc:
        task.status = "failed"
        task.error_type = "RQUnavailable"
        task.error_message = f"Redis/RQ is unavailable; backtest task was not queued: {exc}"
        task.traceback = type(exc).__name__
        task.finished_at = datetime.now(UTC)
        session.commit()
        raise HTTPException(status_code=503, detail="Redis/RQ is unavailable; backtest task was not queued") from exc

    task.status = "queued"
    task.result_payload = {"rq_job_id": job_id, "fixed_task": "JM V1-B daily score2of4"}
    session.commit()
    session.refresh(task)
    payload = task_api_payload(task)
    payload["fixed_task"] = {
        "name": "JM V1-B daily score2of4",
        "interval": "1d",
        "strategy_code": spec.request.strategy_code,
        "strategy_version": spec.request.strategy_version,
        "result_report_id_path": "result_payload.report_id",
    }
    return payload


@router.post("/v1b/jm/daily-trend-cross-score2/tasks")
def create_jm_daily_trend_cross_score2_backtest_task(session: Session = Depends(get_db)) -> dict[str, Any]:
    service = BacktestService(session)
    try:
        spec = build_jm_daily_trend_cross_score2_formal_request(session)
        task = service.create_formal_task(
            spec.request, server_context=spec.server_context
        )
        session.commit()
    except BacktestContractError as exc:
        session.rollback()
        raise _contract_http_exception(exc) from exc
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        job_id = enqueue_backtest_task(task.id)
    except Exception as exc:
        task.status = "failed"
        task.error_type = "RQUnavailable"
        task.error_message = f"Redis/RQ is unavailable; backtest task was not queued: {exc}"
        task.traceback = type(exc).__name__
        task.finished_at = datetime.now(UTC)
        session.commit()
        raise HTTPException(status_code=503, detail="Redis/RQ is unavailable; backtest task was not queued") from exc

    task.status = "queued"
    task.result_payload = {"rq_job_id": job_id, "fixed_task": "JM V1-B daily trend cross score2"}
    session.commit()
    session.refresh(task)
    payload = task_api_payload(task)
    payload["fixed_task"] = {
        "name": "JM V1-B daily trend cross score2",
        "interval": "1d",
        "strategy_code": spec.request.strategy_code,
        "strategy_version": spec.request.strategy_version,
        "result_report_id_path": "result_payload.report_id",
    }
    return payload


@router.post("/v1b/jm/{entry_interval}/tasks")
def create_jm_v1b_backtest_task(entry_interval: str, session: Session = Depends(get_db)) -> dict[str, Any]:
    if entry_interval not in {"15m", "5m"}:
        raise HTTPException(status_code=422, detail="entry_interval must be one of: 15m, 5m")

    service = BacktestService(session)
    try:
        spec = build_jm_v1b_formal_request(entry_interval)  # type: ignore[arg-type]
        task = service.create_formal_task(
            spec.request, server_context=spec.server_context
        )
        session.commit()
    except BacktestContractError as exc:
        session.rollback()
        raise _contract_http_exception(exc) from exc
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        job_id = enqueue_backtest_task(task.id)
    except Exception as exc:
        task.status = "failed"
        task.error_type = "RQUnavailable"
        task.error_message = f"Redis/RQ is unavailable; backtest task was not queued: {exc}"
        task.traceback = type(exc).__name__
        task.finished_at = datetime.now(UTC)
        session.commit()
        raise HTTPException(status_code=503, detail="Redis/RQ is unavailable; backtest task was not queued") from exc

    task.status = "queued"
    task.result_payload = {"rq_job_id": job_id, "fixed_task": f"JM V1-B {entry_interval} entry"}
    session.commit()
    session.refresh(task)
    payload = task_api_payload(task)
    payload["fixed_task"] = {
        "name": f"JM V1-B {entry_interval} entry",
        "entry_interval": entry_interval,
        "strategy_code": spec.request.strategy_code,
        "strategy_version": spec.request.strategy_version,
    }
    return payload


@router.post("/run")
def run_backtest(request: BacktestRunRequest, session: Session = Depends(get_db)) -> dict[str, Any]:
    start = _parse_query_datetime(request.start, end_of_day=False)
    end = _parse_query_datetime(request.end, end_of_day=True)
    if start >= end:
        raise HTTPException(status_code=422, detail="start must be before end")

    reader = MarketDataReader(session)
    service = BacktestService(session)
    try:
        lineage, asset = service.resolve_formal_asset(
            instrument_symbol=request.symbol,
            contract_code=request.contract,
            period=request.period,
            profile_id=request.profile_id,
        )
        service._validate_requested_window(asset, start=start, end=end)
    except BacktestContractError as exc:
        raise _contract_http_exception(exc) from exc
    except BacktestConfigurationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    bars = reader.load_bars(
        symbol=request.symbol,
        contract=request.contract,
        period=request.period,
        start=start,
        end=end,
        provider=str(asset["provider"]),
        data_role="primary",
        passed_only=True,
        profile_id=lineage.profile_id,
    )
    if not bars:
        raise HTTPException(status_code=422, detail="no bars found for backtest")
    if {str(bar.get("provider")) for bar in bars} != {str(asset["provider"])} or {
        str(bar.get("data_version")) for bar in bars
    } != {str(asset["data_version"])}:
        raise _contract_http_exception(
            BacktestContractError(
                "BACKTEST_PROFILE_IDENTITY_MISMATCH",
                "resolved backtest bars do not match the pinned binding snapshot",
                context=service._lineage_context(
                    profile_id=lineage.profile_id,
                    instrument_symbol=request.symbol,
                    contract_code=request.contract,
                    period=request.period,
                ),
                status_code=409,
            )
        )
    try:
        confirmed_lineage, _ = service.resolve_formal_asset(
            instrument_symbol=request.symbol,
            contract_code=request.contract,
            period=request.period,
            profile_id=lineage.profile_id,
        )
    except BacktestConfigurationError as exc:
        raise _contract_http_exception(
            BacktestContractError(
                "BACKTEST_PROFILE_BINDING_CHANGED",
                "Profile binding changed while loading inline backtest bars",
                context=service._lineage_context(
                    profile_id=lineage.profile_id,
                    instrument_symbol=request.symbol,
                    contract_code=request.contract,
                    period=request.period,
                ),
                status_code=409,
            )
        ) from exc
    if confirmed_lineage.market_data_file_id != lineage.market_data_file_id:
        raise _contract_http_exception(
            BacktestContractError(
                "BACKTEST_PROFILE_BINDING_CHANGED",
                "Profile binding changed while loading inline backtest bars",
                context=service._lineage_context(
                    profile_id=lineage.profile_id,
                    instrument_symbol=request.symbol,
                    contract_code=request.contract,
                    period=request.period,
                ),
                status_code=409,
            )
        )

    try:
        config = BacktestConfig(
            initial_capital=request.initial_capital,
            risk_per_trade_pct=request.risk_per_trade_pct,
            max_margin_usage_pct=request.max_margin_usage_pct,
            slippage_ticks=request.slippage_ticks,
            take_profit_r=request.take_profit_r,
            enable_take_profit=request.enable_take_profit,
            strategy_params=SuBingParams(**request.strategy_params),
        )
        report = run_su_bing_backtest(
            bars=bars,
            config=config,
            contract_spec=load_contract_spec(session, request.symbol, request.contract),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    payload = report.to_dict()
    payload["quality_status"] = {"status": "passed", "market_data_file_id": lineage.market_data_file_id}
    payload["profile_id"] = lineage.profile_id
    payload["market_data_file_id"] = lineage.market_data_file_id
    payload["binding_snapshot"] = asset
    return _sanitize_api_payload(payload)


@router.post("/run-batch")
def run_batch_backtest(request: BatchBacktestRunRequest, session: Session = Depends(get_db)) -> dict[str, Any]:
    start = _parse_query_datetime(request.start, end_of_day=False)
    end = _parse_query_datetime(request.end, end_of_day=True)
    if start >= end:
        raise HTTPException(status_code=422, detail="start must be before end")

    payload = request.model_dump()
    payload["start"] = start.isoformat()
    payload["end"] = end.isoformat()
    try:
        task = create_batch_task(session, payload)
    except BacktestContractError as exc:
        session.rollback()
        raise _contract_http_exception(exc) from exc
    except (BacktestConfigurationError, ValueError) as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    session.commit()

    if request.run_inline:
        BatchBacktestRunner(session).run(task.id)
        session.refresh(task)
        return task_snapshot(task)

    try:
        job_id = enqueue_batch_task(task.id)
    except Exception as exc:
        task.status = "failed"
        task.error_message = f"failed to enqueue RQ task: {exc}"
        task.finished_at = datetime.now(UTC)
        session.commit()
        raise HTTPException(status_code=503, detail="Redis/RQ is unavailable; batch task was not queued") from exc

    task.result_payload = {"rq_job_id": job_id}
    session.commit()
    return task_snapshot(task)


@router.get("/tasks")
def list_backtest_tasks(
    paged: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_db),
) -> list[dict[str, Any]] | dict[str, Any]:
    stmt = select(BacktestTask).order_by(BacktestTask.created_at.desc()).limit(limit).offset(offset)
    items = [task_api_payload(task) for task in session.scalars(stmt)]
    if not paged:
        return items
    total = int(session.scalar(select(func.count()).select_from(BacktestTask)) or 0)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/tasks/{task_ref}")
def get_backtest_task(task_ref: str, session: Session = Depends(get_db)) -> dict[str, Any]:
    task = _get_task_by_ref(session, task_ref)
    if task is None:
        raise HTTPException(status_code=404, detail="backtest task not found")
    return task_api_payload(task)


@router.get("/tasks/{task_no}/reports")
def list_backtest_reports(task_no: str, session: Session = Depends(get_db)) -> list[dict[str, Any]]:
    reports = session.scalars(
        select(BacktestReportModel).where(BacktestReportModel.task_no == task_no).order_by(BacktestReportModel.suitability_score.desc())
    )
    return [report_api_payload(report) for report in reports]


@router.get("/reports")
def list_reports(
    status: str = Query("success", description="Report status filter; use all to include failed/skipped reports."),
    paged: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_db),
) -> list[dict[str, Any]] | dict[str, Any]:
    stmt = select(BacktestReportModel)
    if status != "all":
        statuses = SUCCESS_REPORT_STATUSES if status == "success" else {status}
        stmt = stmt.where(BacktestReportModel.status.in_(statuses))
    total = int(session.scalar(select(func.count()).select_from(stmt.subquery())) or 0) if paged else 0
    reports = session.scalars(stmt.order_by(BacktestReportModel.created_at.desc()).limit(limit).offset(offset))
    items = [report_api_payload(report) for report in reports]
    if not paged:
        return items
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/reports/{report_id}")
def get_backtest_report(report_id: int, session: Session = Depends(get_db)) -> dict[str, Any]:
    report = session.get(BacktestReportModel, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="backtest report not found")
    return report_api_payload(report, include_detail=True)


@router.get(
    "/reports/{report_id}/validation-context",
    response_model=BacktestValidationContext,
)
def get_backtest_validation_context(
    report_id: int,
    request: Request,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    if request.query_params:
        raise HTTPException(status_code=422, detail="validation-context does not accept file paths or query overrides")
    report = session.get(BacktestReportModel, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="backtest report not found")
    try:
        return build_backtest_validation_context(
            PROJECT_ROOT,
            report_identity={
                "id": report.id,
                "report_no": report.report_no,
                "task_id": report.task_id,
                "task_no": report.task_no,
                "profile_id": report.profile_id,
                "market_data_file_id": report.market_data_file_id,
            },
        )
    except BacktestValidationEvidenceError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "BACKTEST_VALIDATION_EVIDENCE_INVALID", "message": str(exc)},
        ) from exc


@router.get(
    "/reports/{report_id}/validation-context/observation",
    response_model=BacktestValidationContextObservation,
)
def get_backtest_validation_context_observation(
    report_id: int,
    request: Request,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Return a Web-safe availability snapshot without weakening the strict 409 Gate."""
    if request.query_params:
        raise HTTPException(status_code=422, detail="validation observation does not accept query overrides")
    report = session.get(BacktestReportModel, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="backtest report not found")
    try:
        context = build_backtest_validation_context(
            PROJECT_ROOT,
            report_identity={
                "id": report.id,
                "report_no": report.report_no,
                "task_id": report.task_id,
                "task_no": report.task_no,
                "profile_id": report.profile_id,
                "market_data_file_id": report.market_data_file_id,
            },
        )
    except BacktestValidationEvidenceError:
        return {
            "available": False,
            "context": None,
            "error_type": "BACKTEST_VALIDATION_EVIDENCE_INVALID",
            "error_message": "validation evidence is unavailable or invalid",
        }
    return {
        "available": True,
        "context": context,
        "error_type": None,
        "error_message": None,
    }


@router.get("/reports/{report_id}/trades")
def list_report_trades(
    report_id: int,
    trade_id: int | None = Query(None, ge=1),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    sort_by: str = Query("close_time"),
    sort_order: Literal["asc", "desc"] = Query("asc"),
    direction: str | None = Query(None),
    symbol: str | None = Query(None),
    contract: str | None = Query(None),
    start: str | None = Query(None, description="Filter by open_time >= start."),
    end: str | None = Query(None, description="Filter by close_time <= end."),
    min_net_pnl: float | None = Query(None),
    max_net_pnl: float | None = Query(None),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    report = session.get(BacktestReportModel, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="backtest report not found")
    filters = _trade_filters(
        report_id=report_id,
        trade_id=trade_id,
        direction=direction,
        symbol=symbol,
        contract=contract,
        start=start,
        end=end,
        min_net_pnl=min_net_pnl,
        max_net_pnl=max_net_pnl,
    )
    total = session.scalar(select(func.count(BacktestTradeModel.id)).where(*filters)) or 0
    _ensure_report_trades_available(report, total)
    sort_column = _trade_sort_column(sort_by)
    order_clause = asc(sort_column) if sort_order == "asc" else desc(sort_column)
    rows = session.scalars(
        select(BacktestTradeModel).where(*filters).order_by(order_clause, BacktestTradeModel.id.asc()).limit(limit).offset(offset)
    )
    return {
        "report_id": report.id,
        "total": total,
        "limit": limit,
        "offset": offset,
        "sort_by": sort_by,
        "sort_order": sort_order,
        "filters": _active_trade_filter_payload(
            trade_id=trade_id,
            direction=direction,
            symbol=symbol,
            contract=contract,
            start=start,
            end=end,
            min_net_pnl=min_net_pnl,
            max_net_pnl=max_net_pnl,
        ),
        "items": _sanitize_api_payload([_trade_payload_for_api(trade) for trade in rows]),
    }


@router.get("/reports/{report_id}/trades/export")
def export_report_trades(
    report_id: int,
    format: Literal["csv", "json"] = Query("csv"),
    sort_by: str = Query("close_time"),
    sort_order: Literal["asc", "desc"] = Query("asc"),
    direction: str | None = Query(None),
    symbol: str | None = Query(None),
    contract: str | None = Query(None),
    start: str | None = Query(None),
    end: str | None = Query(None),
    min_net_pnl: float | None = Query(None),
    max_net_pnl: float | None = Query(None),
    session: Session = Depends(get_db),
) -> Response:
    report = session.get(BacktestReportModel, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="backtest report not found")
    filters = _trade_filters(
        report_id=report_id,
        trade_id=None,
        direction=direction,
        symbol=symbol,
        contract=contract,
        start=start,
        end=end,
        min_net_pnl=min_net_pnl,
        max_net_pnl=max_net_pnl,
    )
    total = session.scalar(select(func.count(BacktestTradeModel.id)).where(*filters)) or 0
    _ensure_report_trades_available(report, total)
    sort_column = _trade_sort_column(sort_by)
    order_clause = asc(sort_column) if sort_order == "asc" else desc(sort_column)
    trades = list(session.scalars(select(BacktestTradeModel).where(*filters).order_by(order_clause, BacktestTradeModel.id.asc())))
    export_rows = _sanitize_api_payload([_trade_export_row(report, trade) for trade in trades])
    filename = f"backtest_report_{report.id}_trades.{format}"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    if format == "json":
        payload = {
            "report_summary": _report_export_summary(report),
            "trade_count": len(export_rows),
            "filters": _active_trade_filter_payload(
                trade_id=None,
                direction=direction,
                symbol=symbol,
                contract=contract,
                start=start,
                end=end,
                min_net_pnl=min_net_pnl,
                max_net_pnl=max_net_pnl,
            ),
            "sort_by": sort_by,
            "sort_order": sort_order,
            "trades": export_rows,
            "disclaimer": BACKTEST_DISCLAIMER,
        }
        return Response(
            content=json.dumps(payload, ensure_ascii=False, default=str, indent=2),
            media_type="application/json; charset=utf-8",
            headers=headers,
        )
    return Response(content=_csv_export(export_rows), media_type="text/csv; charset=utf-8", headers=headers)


@router.get("/reports/{report_id}/orders")
def list_report_orders(report_id: int, session: Session = Depends(get_db)) -> list[dict[str, Any]]:
    report = session.get(BacktestReportModel, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="backtest report not found")
    return report_api_payload(report, include_detail=True)["orders"]


@router.get("/reports/{report_id}/equity-curve")
def get_report_equity_curve(report_id: int, session: Session = Depends(get_db)) -> list[dict[str, Any]]:
    report = session.get(BacktestReportModel, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="backtest report not found")
    return report_api_payload(report, include_detail=True)["equity_curve"]


@router.get("/reports/{report_id}/drawdown-curve")
def get_report_drawdown_curve(report_id: int, session: Session = Depends(get_db)) -> list[dict[str, Any]]:
    report = session.get(BacktestReportModel, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="backtest report not found")
    return report_api_payload(report, include_detail=True)["drawdown_curve"]


@watchlists_router.get("")
def list_watchlists(session: Session = Depends(get_db)) -> list[dict[str, Any]]:
    ensure_default_watchlists(session)
    session.commit()
    rows = session.scalars(select(Watchlist).where(Watchlist.is_active.is_(True)).order_by(Watchlist.code))
    return [
        {
            "code": row.code,
            "name": row.name,
            "category": row.category,
            "description": row.description,
            "item_count": len([item for item in row.items if item.is_active]),
        }
        for row in rows
    ]


@watchlists_router.get("/{code}/items")
def list_watchlist_items(code: str, session: Session = Depends(get_db)) -> list[dict[str, Any]]:
    ensure_default_watchlists(session)
    session.commit()
    watchlist = session.scalar(select(Watchlist).where(Watchlist.code == code, Watchlist.is_active.is_(True)))
    if watchlist is None:
        raise HTTPException(status_code=404, detail="watchlist not found")
    reader = MarketDataReader(session)
    return [
        {
            "symbol": item.symbol,
            "name": item.name,
            "exchange_code": item.exchange_code,
            "default_contract": item.default_contract,
            "available_periods": sorted({row.period for row in reader.get_coverage(symbol=item.symbol) if row.period}),
        }
        for item in sorted([item for item in watchlist.items if item.is_active], key=lambda row: (row.sort_order, row.symbol))
    ]


def _parse_query_datetime(value: str, end_of_day: bool) -> datetime:
    try:
        if len(value) == 10:
            parsed_date = date.fromisoformat(value)
            parsed = datetime.combine(parsed_date, time.max if end_of_day else time.min)
        else:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"invalid datetime: {value}") from exc
    return parsed.replace(tzinfo=None)


def _get_task_by_ref(session: Session, task_ref: str) -> BacktestTask | None:
    if task_ref.isdigit():
        task = session.get(BacktestTask, int(task_ref))
        if task is not None:
            return task
    return session.scalar(select(BacktestTask).where(BacktestTask.task_no == task_ref))


def task_api_payload(task: BacktestTask) -> dict[str, Any]:
    payload = task_snapshot(task)
    input_identity = _canonical_input_identity(task.binding_snapshot)
    if input_identity is not None and not task.research_only:
        payload.pop("profile_id", None)
        payload.pop("market_data_file_id", None)
        payload.pop("binding_snapshot", None)
        payload["input_identity"] = input_identity
    payload.update(
        {
            "engine_type": task.engine_type,
            "task_type": task.task_type,
            "data_source": task.data_source,
            "data_role": task.data_role,
            "data_version": task.data_version,
            "research_only": task.research_only,
            "error_type": task.error_type,
            "rq_job_id": (task.result_payload or {}).get("rq_job_id"),
            "disclaimer": BACKTEST_DISCLAIMER,
        }
    )
    if input_identity is not None and not task.research_only:
        payload = _without_legacy_input_identity(payload)
    return _sanitize_api_payload(payload)


def report_api_payload(report: BacktestReportModel, include_detail: bool = False) -> dict[str, Any]:
    payload = report_payload(report, include_detail=include_detail)
    input_identity = _canonical_input_identity(report.binding_snapshot)
    if input_identity is not None and not report.research_only:
        payload.pop("profile_id", None)
        payload.pop("market_data_file_id", None)
        payload.pop("binding_snapshot", None)
        payload["input_identity"] = input_identity
    from guiyi_quant.strategies.indicator_policy import resolve_report_indicator_policy

    policy = resolve_report_indicator_policy(report.summary or {})
    foundation = _review_foundation_passthrough(report.summary or {})
    payload.update(
        {
            "engine_type": report.engine_type,
            "data_source": report.data_source,
            "data_role": report.data_role,
            "data_version": report.data_version,
            "research_only": report.research_only,
            "disclaimer": BACKTEST_DISCLAIMER,
            "indicator_policy_status": policy["status"],
            "indicator_policy_snapshot": policy["snapshot"],
            "indicator_policy_reason": policy["reason"],
            **foundation,
        }
    )
    if input_identity is not None and not report.research_only:
        payload = _without_legacy_input_identity(payload)
    return _sanitize_api_payload(payload)


def _canonical_input_identity(
    snapshot: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(snapshot, dict):
        return None
    if snapshot.get("schema_version") != "backtest_canonical_inputs_v1":
        return None
    identity = snapshot.get("input_identity")
    return dict(identity) if isinstance(identity, dict) else None


def _without_legacy_input_identity(value: Any) -> Any:
    forbidden = {
        "profile_id",
        "market_data_file_id",
        "binding_snapshot",
        "resolver_name",
        "resolver_contract_version",
    }
    if isinstance(value, dict):
        return {
            key: _without_legacy_input_identity(item)
            for key, item in value.items()
            if key not in forbidden
        }
    if isinstance(value, list):
        return [_without_legacy_input_identity(item) for item in value]
    return value


def _review_foundation_passthrough(summary: dict[str, Any]) -> dict[str, Any | None]:
    """Optional C5-06A read-only fields. Pass through only; never invent."""
    metadata = summary.get("report_metadata") if isinstance(summary.get("report_metadata"), dict) else {}
    keys = (
        "oos_window_id",
        "walk_forward_fold_id",
        "candidate_status",
        "hard_reject_reason",
        "review_skip_status",
    )
    out: dict[str, Any | None] = {}
    for key in keys:
        value = summary.get(key)
        if value is None and isinstance(metadata, dict):
            value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = value.strip()
        else:
            out[key] = None
    return out


def _trade_filters(
    *,
    report_id: int,
    trade_id: int | None,
    direction: str | None,
    symbol: str | None,
    contract: str | None,
    start: str | None,
    end: str | None,
    min_net_pnl: float | None,
    max_net_pnl: float | None,
) -> list[Any]:
    filters: list[Any] = [BacktestTradeModel.report_id == report_id]
    if trade_id is not None:
        filters.append(BacktestTradeModel.id == trade_id)
    if direction:
        filters.append(func.lower(BacktestTradeModel.direction) == direction.strip().lower())
    if symbol:
        filters.append(func.lower(BacktestTradeModel.symbol) == symbol.strip().lower())
    if contract:
        normalized_contract = contract.strip()
        filters.append(
            or_(
                BacktestTradeModel.contract == normalized_contract,
                BacktestTradeModel.entry_contract == normalized_contract,
                BacktestTradeModel.exit_contract == normalized_contract,
            )
        )
    if start:
        filters.append(BacktestTradeModel.open_time >= _parse_query_datetime(start, end_of_day=False))
    if end:
        filters.append(BacktestTradeModel.close_time <= _parse_query_datetime(end, end_of_day=True))
    if min_net_pnl is not None:
        filters.append(BacktestTradeModel.net_pnl >= min_net_pnl)
    if max_net_pnl is not None:
        filters.append(BacktestTradeModel.net_pnl <= max_net_pnl)
    return filters


def _trade_sort_column(sort_by: str) -> Any:
    try:
        return TRADE_SORT_COLUMNS[sort_by]
    except KeyError as exc:
        allowed = ", ".join(sorted(TRADE_SORT_COLUMNS))
        raise HTTPException(status_code=422, detail=f"unsupported sort_by={sort_by}; allowed: {allowed}") from exc


def _ensure_report_trades_available(report: BacktestReportModel, trade_count: int) -> None:
    if report.status not in SUCCESS_REPORT_STATUSES and trade_count == 0:
        raise HTTPException(
            status_code=409,
            detail=f"backtest report status is {report.status}; trades are only available after successful report generation",
        )


def _active_trade_filter_payload(
    *,
    trade_id: int | None,
    direction: str | None,
    symbol: str | None,
    contract: str | None,
    start: str | None,
    end: str | None,
    min_net_pnl: float | None,
    max_net_pnl: float | None,
) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "trade_id": trade_id,
            "direction": direction,
            "symbol": symbol,
            "contract": contract,
            "start": start,
            "end": end,
            "min_net_pnl": min_net_pnl,
            "max_net_pnl": max_net_pnl,
        }.items()
        if value is not None
    }


def _trade_payload_for_api(trade: BacktestTradeModel) -> dict[str, Any]:
    return {
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
        "raw_payload": trade.raw_payload,
    }


def _report_export_summary(report: BacktestReportModel) -> dict[str, Any]:
    return _sanitize_api_payload(
        {
            "report_id": report.id,
            "report_no": report.report_no,
            "task_id": report.task_id,
            "task_no": report.task_no,
            "status": report.status,
            "consistency_hash": report.consistency_hash,
            "strategy_code": report.strategy_code,
            "strategy_version": report.strategy_version,
            "symbol": report.symbol,
            "contract": report.contract,
            "interval": report.period,
            "engine_type": report.engine_type,
            "data_source": report.data_source,
            "data_role": report.data_role,
            "data_version": report.data_version,
            "research_only": report.research_only,
            "initial_capital": report.initial_capital,
            "final_equity": report.final_equity,
            "total_return": report.total_return,
            "annual_return": report.annual_return,
            "max_drawdown": report.max_drawdown,
            "max_drawdown_amount": report.max_drawdown_amount,
            "max_drawdown_pct": report.max_drawdown_pct,
            "win_rate": report.win_rate,
            "profit_loss_ratio": report.profit_loss_ratio,
            "trade_count": report.trade_count,
            "total_commission": report.total_commission,
            "total_slippage": report.total_slippage,
            "summary": report.summary,
            "warnings": report.warnings,
            "created_at": report.created_at.isoformat() if report.created_at else None,
            "started_at": report.started_at.isoformat() if report.started_at else None,
            "finished_at": report.finished_at.isoformat() if report.finished_at else None,
        }
    )


def _trade_export_row(report: BacktestReportModel, trade: BacktestTradeModel) -> dict[str, Any]:
    metadata = _report_metadata(report)
    raw_payload = trade.raw_payload or {}
    return {
        "report_id": report.id,
        "trade_id": trade.id,
        "order_id": _first_raw_value(raw_payload, "order_id", "orderid", "order_no"),
        "trade_no": trade.trade_no,
        "sequence": trade.sequence,
        "task_id": report.task_id,
        "task_no": report.task_no,
        "strategy_code": report.strategy_code or metadata.get("strategy_code"),
        "strategy_version": report.strategy_version or metadata.get("strategy_version"),
        "symbol": trade.symbol,
        "vt_symbol": metadata.get("vt_symbol"),
        "exchange": trade.exchange or metadata.get("exchange"),
        "research_contract": trade.research_contract,
        "contract": trade.contract,
        "entry_contract": trade.entry_contract,
        "exit_contract": trade.exit_contract,
        "interval": report.period,
        "timeframe": trade.timeframe or report.period,
        "datetime": trade.close_time.isoformat(),
        "trading_day": _first_raw_value(raw_payload, "trading_day", "date"),
        "direction": trade.direction,
        "offset": _first_raw_value(raw_payload, "offset"),
        "price": trade.close_price,
        "volume": trade.volume,
        "turnover": trade.turnover,
        "commission": trade.commission,
        "slippage": trade.slippage,
        "pnl": trade.gross_pnl,
        "gross_pnl": trade.gross_pnl,
        "net_pnl": trade.net_pnl,
        "balance": _first_raw_value(raw_payload, "balance"),
        "equity_after_trade": _first_raw_value(raw_payload, "equity_after_trade", "equity"),
        "entry_price": trade.open_price,
        "exit_price": trade.close_price,
        "entry_signal_time": trade.entry_signal_time.isoformat() if trade.entry_signal_time else None,
        "entry_signal_source": trade.entry_signal_source,
        "entry_order_no": trade.entry_order_no,
        "exit_signal_time": trade.exit_signal_time.isoformat() if trade.exit_signal_time else None,
        "exit_signal_source": trade.exit_signal_source,
        "exit_order_no": trade.exit_order_no,
        "entry_datetime": trade.open_time.isoformat(),
        "exit_datetime": trade.close_time.isoformat(),
        "holding_bars": trade.holding_bars,
        "holding_minutes": _first_raw_value(raw_payload, "holding_minutes"),
        "stop_loss_price": trade.stop_loss_price,
        "signal_reason": _first_raw_value(raw_payload, "signal_reason", "entry_reason") or trade.entry_reason,
        "entry_reason": trade.entry_reason,
        "exit_reason": trade.exit_reason,
        "remark": _first_raw_value(raw_payload, "remark"),
        "note": _first_raw_value(raw_payload, "note"),
        "contract_multiplier": trade.contract_multiplier,
        "price_tick": trade.price_tick,
        "margin_ratio": trade.margin_ratio,
        "margin_required": trade.margin_required,
        "parameter_source": trade.parameter_source,
        "rollover_forced_exit": trade.rollover_forced_exit,
        "delivery_risk_exit": trade.delivery_risk_exit,
        "rollover_reason": trade.rollover_reason,
        "fee_rule_source": trade.fee_rule_source,
        "main_contract_source": trade.main_contract_source,
        "lineage_status": trade.lineage_status,
        "raw_payload": raw_payload,
    }


def _report_metadata(report: BacktestReportModel) -> dict[str, Any]:
    summary = report.summary or {}
    metadata = summary.get("report_metadata")
    return metadata if isinstance(metadata, dict) else {}


def _first_raw_value(raw_payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = raw_payload.get(key)
        if value is not None:
            return value
    return None


def _csv_export(rows: list[dict[str, Any]]) -> str:
    buffer = StringIO()
    buffer.write("\ufeff")
    writer = csv.DictWriter(buffer, fieldnames=TRADE_EXPORT_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: _csv_value(row.get(field)) for field in TRADE_EXPORT_FIELDS})
    return buffer.getvalue()


def _csv_value(value: Any) -> Any:
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False, default=str)
    return value


SENSITIVE_OUTPUT_KEY_PARTS = (
    "account",
    "api_key",
    "bar_data_path",
    "file_path",
    "license",
    "normalized_result_path",
    "password",
    "passwd",
    "raw_result_path",
    "secret",
    "token",
    "traceback",
)
LOCAL_PATH_MARKERS = ("/Volumes/", "/Users/", "/private/", "\\Users\\")


def _sanitize_api_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _sanitize_api_payload(item)
            for key, item in value.items()
            if not _is_sensitive_output_key(str(key))
        }
    if isinstance(value, list):
        return [_sanitize_api_payload(item) for item in value]
    if isinstance(value, str) and any(marker in value for marker in LOCAL_PATH_MARKERS):
        return "<redacted>"
    return value


def _is_sensitive_output_key(key: str) -> bool:
    normalized = key.lower()
    return any(part in normalized for part in SENSITIVE_OUTPUT_KEY_PARTS)
