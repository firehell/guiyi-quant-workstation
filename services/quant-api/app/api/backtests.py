from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtest.service import BacktestService
from app.backtest.engine import BacktestConfig, run_su_bing_backtest
from app.backtest.specs import load_contract_spec
from app.backtest.v1b_jm_tasks import available_jm_v1b_entry_intervals, build_jm_v1b_task_config
from app.db.session import get_db
from app.models.backtest import BacktestReportModel, BacktestTask, Watchlist
from app.queue import get_backtest_queue
from app.schemas.backtest import BacktestTaskConfig
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

router = APIRouter(prefix="/api/backtests", tags=["backtests"])
watchlists_router = APIRouter(prefix="/api/watchlists", tags=["watchlists"])

BACKTEST_DISCLAIMER = "回测结果不等于实盘结果；实盘前必须经过模拟验证、小资金验证和人工风控确认。"


class BacktestRunRequest(BaseModel):
    symbol: str
    contract: str
    period: str
    start: str
    end: str
    provider: str | None = None
    initial_capital: float = Field(default=100000.0, gt=0)
    risk_per_trade_pct: float = Field(default=0.01, gt=0, le=1)
    max_margin_usage_pct: float = Field(default=0.35, gt=0, le=1)
    slippage_ticks: int = Field(default=1, ge=0)
    take_profit_r: float = Field(default=2.0, gt=0)
    enable_take_profit: bool = True
    allow_warning_quality: bool = False
    strategy_params: dict[str, Any] = Field(default_factory=dict)


class BacktestParameterTemplate(BaseModel):
    name: str
    label: str | None = None
    strategy_params: dict[str, Any] = Field(default_factory=dict)
    overrides: dict[str, Any] = Field(default_factory=dict)


class BatchBacktestRunRequest(BaseModel):
    watchlist_code: str
    period: str
    start: str
    end: str
    provider: str | None = None
    symbols: list[str] | None = None
    initial_capital: float = Field(default=100000.0, gt=0)
    risk_per_trade_pct: float = Field(default=0.01, gt=0, le=1)
    max_margin_usage_pct: float = Field(default=0.35, gt=0, le=1)
    slippage_ticks: int = Field(default=1, ge=0)
    take_profit_r: float = Field(default=2.0, gt=0)
    enable_take_profit: bool = True
    allow_warning_quality: bool = False
    strategy_params: dict[str, Any] = Field(default_factory=dict)
    parameter_templates: list[BacktestParameterTemplate] = Field(default_factory=list)
    run_inline: bool = False


def enqueue_backtest_task(task_id: int) -> str:
    queued = get_backtest_queue().enqueue(run_backtest_task, task_id, job_timeout="12h", result_ttl=86400)
    return queued.id


@router.post("/tasks")
def create_backtest_task(request: BacktestTaskConfig, session: Session = Depends(get_db)) -> dict[str, Any]:
    service = BacktestService(session)
    task = service.create_task(request)
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


@router.post("/v1b/jm/{entry_interval}/tasks")
def create_jm_v1b_backtest_task(entry_interval: str, session: Session = Depends(get_db)) -> dict[str, Any]:
    if entry_interval not in {"15m", "5m"}:
        raise HTTPException(status_code=422, detail="entry_interval must be one of: 15m, 5m")

    service = BacktestService(session)
    try:
        spec = build_jm_v1b_task_config(session, cast(Literal["15m", "5m"], entry_interval))
        task = service.create_task(spec.config)
        session.commit()
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
        "strategy_code": spec.config.strategy_code,
        "strategy_version": spec.config.strategy_version,
        "data_availability": available_jm_v1b_entry_intervals(session),
    }
    return payload


@router.post("/run")
def run_backtest(request: BacktestRunRequest, session: Session = Depends(get_db)) -> dict[str, Any]:
    start = _parse_query_datetime(request.start, end_of_day=False)
    end = _parse_query_datetime(request.end, end_of_day=True)
    if start >= end:
        raise HTTPException(status_code=422, detail="start must be before end")

    reader = MarketDataReader(session)
    quality = reader.get_quality_status(
        symbol=request.symbol,
        contract=request.contract,
        period=request.period,
        start=start,
        end=end,
        provider=request.provider,
    )
    if quality["status"] == "failed":
        raise HTTPException(status_code=422, detail="data quality failed; backtest is rejected")
    if quality["status"] == "warning" and not request.allow_warning_quality:
        raise HTTPException(status_code=422, detail="data quality warning requires allow_warning_quality=true")

    bars = reader.load_bars(
        symbol=request.symbol,
        contract=request.contract,
        period=request.period,
        start=start,
        end=end,
        provider=request.provider,
    )
    if not bars:
        raise HTTPException(status_code=422, detail="no bars found for backtest")

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
    payload["quality_status"] = quality
    return payload


@router.post("/run-batch")
def run_batch_backtest(request: BatchBacktestRunRequest, session: Session = Depends(get_db)) -> dict[str, Any]:
    start = _parse_query_datetime(request.start, end_of_day=False)
    end = _parse_query_datetime(request.end, end_of_day=True)
    if start >= end:
        raise HTTPException(status_code=422, detail="start must be before end")

    payload = request.model_dump()
    payload["start"] = start.isoformat()
    payload["end"] = end.isoformat()
    task = create_batch_task(session, payload)
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
def list_backtest_tasks(session: Session = Depends(get_db)) -> list[dict[str, Any]]:
    tasks = session.scalars(select(BacktestTask).order_by(BacktestTask.created_at.desc()).limit(50))
    return [task_api_payload(task) for task in tasks]


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
def list_reports(session: Session = Depends(get_db)) -> list[dict[str, Any]]:
    reports = session.scalars(select(BacktestReportModel).order_by(BacktestReportModel.created_at.desc()).limit(50))
    return [report_api_payload(report) for report in reports]


@router.get("/reports/{report_id}")
def get_backtest_report(report_id: int, session: Session = Depends(get_db)) -> dict[str, Any]:
    report = session.get(BacktestReportModel, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="backtest report not found")
    return report_api_payload(report, include_detail=True)


@router.get("/reports/{report_id}/trades")
def list_report_trades(report_id: int, session: Session = Depends(get_db)) -> list[dict[str, Any]]:
    report = session.get(BacktestReportModel, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="backtest report not found")
    return report_api_payload(report, include_detail=True)["trades"]


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
    return payload


def report_api_payload(report: BacktestReportModel, include_detail: bool = False) -> dict[str, Any]:
    payload = report_payload(report, include_detail=include_detail)
    payload.update(
        {
            "engine_type": report.engine_type,
            "data_source": report.data_source,
            "data_role": report.data_role,
            "data_version": report.data_version,
            "research_only": report.research_only,
            "disclaimer": BACKTEST_DISCLAIMER,
        }
    )
    return _sanitize_api_payload(payload)


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
