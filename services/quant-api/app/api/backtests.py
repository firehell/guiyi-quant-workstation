from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtest.engine import BacktestConfig, run_su_bing_backtest
from app.backtest.specs import load_contract_spec
from app.db.session import get_db
from app.models.backtest import BacktestReportModel, BacktestTask, Watchlist
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

router = APIRouter(prefix="/api/backtests", tags=["backtests"])
watchlists_router = APIRouter(prefix="/api/watchlists", tags=["watchlists"])


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
    return [task_snapshot(task) for task in tasks]


@router.get("/tasks/{task_no}")
def get_backtest_task(task_no: str, session: Session = Depends(get_db)) -> dict[str, Any]:
    task = session.scalar(select(BacktestTask).where(BacktestTask.task_no == task_no))
    if task is None:
        raise HTTPException(status_code=404, detail="backtest task not found")
    return task_snapshot(task)


@router.get("/tasks/{task_no}/reports")
def list_backtest_reports(task_no: str, session: Session = Depends(get_db)) -> list[dict[str, Any]]:
    reports = session.scalars(
        select(BacktestReportModel).where(BacktestReportModel.task_no == task_no).order_by(BacktestReportModel.suitability_score.desc())
    )
    return [report_payload(report) for report in reports]


@router.get("/reports/{report_id}")
def get_backtest_report(report_id: int, session: Session = Depends(get_db)) -> dict[str, Any]:
    report = session.get(BacktestReportModel, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="backtest report not found")
    return report_payload(report, include_detail=True)


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
