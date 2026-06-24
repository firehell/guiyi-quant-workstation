from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.signal import SignalScanTask, StrategySignal
from app.services.signal_scanner import (
    DEFAULT_PERIODS,
    SignalScanner,
    create_signal_scan_task,
    enqueue_signal_scan_task,
    signal_payload,
    task_snapshot,
)

router = APIRouter(prefix="/api/signals", tags=["signals"])


class SignalScanRequest(BaseModel):
    watchlist_code: str = "black"
    periods: list[str] = Field(default_factory=lambda: DEFAULT_PERIODS.copy())
    symbols: list[str] | None = None
    provider: str | None = None
    account_equity: float = Field(default=100000.0, gt=0)
    risk_per_trade_pct: float = Field(default=0.01, gt=0, le=1)
    max_margin_usage_pct: float = Field(default=0.35, gt=0, le=1)
    min_score_bucket: int = Field(default=51, ge=0, le=80)
    allow_warning_quality: bool = False
    strategy_params: dict[str, Any] = Field(default_factory=dict)
    run_inline: bool = False


@router.post("/scan")
def scan_signals(request: SignalScanRequest, session: Session = Depends(get_db)) -> dict[str, Any]:
    payload = request.model_dump()
    task = create_signal_scan_task(session, payload)
    session.commit()

    if request.run_inline:
        SignalScanner(session).run(task.id)
        session.refresh(task)
        return task_snapshot(task)

    try:
        job_id = enqueue_signal_scan_task(task.id)
    except Exception as exc:
        task.status = "failed"
        task.error_message = f"failed to enqueue RQ task: {exc}"
        task.finished_at = datetime.now(UTC)
        session.commit()
        raise HTTPException(status_code=503, detail="Redis/RQ is unavailable; signal scan was not queued") from exc

    task.result_payload = {"rq_job_id": job_id}
    session.commit()
    return task_snapshot(task)


@router.get("/latest")
def latest_signals(
    watchlist_code: str | None = None,
    period: str | None = None,
    score_bucket: int | None = Query(default=None, ge=0, le=80),
    direction: str | None = None,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    session: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    query = select(StrategySignal).where(StrategySignal.is_active.is_(True))
    if watchlist_code:
        query = query.where(StrategySignal.watchlist_code == watchlist_code)
    if period:
        query = query.where(StrategySignal.period == period)
    if score_bucket is not None:
        query = query.where(StrategySignal.score_bucket == score_bucket)
    if direction:
        query = query.where(StrategySignal.direction == direction)
    if status:
        query = query.where(StrategySignal.status == status)
    rows = session.scalars(query.order_by(StrategySignal.signal_time.desc(), StrategySignal.score_bucket.desc()).limit(limit))
    return [signal_payload(row) for row in rows]


@router.get("/tasks/{task_no}")
def get_signal_task(task_no: str, session: Session = Depends(get_db)) -> dict[str, Any]:
    task = session.scalar(select(SignalScanTask).where(SignalScanTask.task_no == task_no))
    if task is None:
        raise HTTPException(status_code=404, detail="signal scan task not found")
    return task_snapshot(task)


@router.get("/tasks/{task_no}/signals")
def get_task_signals(task_no: str, session: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(StrategySignal).where(StrategySignal.task_no == task_no).order_by(StrategySignal.score_bucket.desc(), StrategySignal.signal_time.desc())
    )
    return [signal_payload(row) for row in rows]


@router.post("/{signal_id}/ack")
def ack_signal(signal_id: int, session: Session = Depends(get_db)) -> dict[str, Any]:
    signal = session.get(StrategySignal, signal_id)
    if signal is None:
        raise HTTPException(status_code=404, detail="signal not found")
    signal.alert_status = "acknowledged"
    signal.updated_at = datetime.now(UTC)
    session.commit()
    session.refresh(signal)
    return signal_payload(signal)
