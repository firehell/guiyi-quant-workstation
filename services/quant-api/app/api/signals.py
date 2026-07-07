from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.signal import SignalScanTask, StrategySignal
from app.schemas.signal import LiveSignalEvaluationRequest, LiveSignalEvaluationResponse, SignalScanRequest, SignalStatus, SignalStatusUpdate
from app.signal.scanner import (
    DEFAULT_PERIODS,
    SignalScanner,
    create_jm_v1b_signal_scan_task,
    create_signal_scan_task,
    enqueue_signal_scan_task,
    signal_payload,
    task_snapshot,
    update_signal_status,
)
from app.services.live_signal_evaluator import LiveSignalEvaluator

router = APIRouter(prefix="/api/signals", tags=["signals"])


@router.post("/live-evaluator/preview", response_model=LiveSignalEvaluationResponse)
def preview_live_evaluator(request: LiveSignalEvaluationRequest, session: Session = Depends(get_db)) -> LiveSignalEvaluationResponse:
    try:
        return LiveSignalEvaluator(session).preview(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/scan")
def scan_signals(request: SignalScanRequest, session: Session = Depends(get_db)) -> dict[str, Any]:
    payload = request.model_dump()
    if not payload["periods"]:
        payload["periods"] = DEFAULT_PERIODS.copy()
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


@router.post("/v1b/jm/scan")
def scan_jm_v1b_signals(run_inline: bool = True, session: Session = Depends(get_db)) -> dict[str, Any]:
    task = create_jm_v1b_signal_scan_task(session, {"run_inline": run_inline})
    session.commit()

    if run_inline:
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
    interval: str | None = None,
    score_bucket: int | None = Query(default=None, ge=0, le=80),
    direction: str | None = None,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    session: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    query = select(StrategySignal).where(StrategySignal.is_active.is_(True))
    if watchlist_code:
        query = query.where(StrategySignal.watchlist_code == watchlist_code)
    selected_period = period or interval
    if selected_period:
        query = query.where(StrategySignal.period == selected_period)
    if score_bucket is not None:
        query = query.where(StrategySignal.score_bucket == score_bucket)
    if direction:
        query = query.where(StrategySignal.direction == direction)
    rows = session.scalars(query.order_by(StrategySignal.signal_time.desc(), StrategySignal.score_bucket.desc()).limit(limit * 5 if status else limit))
    payloads = [signal_payload(row) for row in rows]
    if status:
        payloads = [item for item in payloads if item["status"] == status]
    return payloads[:limit]


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
    try:
        signal = update_signal_status(session, signal_id, SignalStatus.VIEWED)
    except ValueError:
        raise HTTPException(status_code=404, detail="signal not found")
    return signal_payload(signal)


@router.patch("/{signal_id}/status")
def update_signal_lifecycle(signal_id: int, request: SignalStatusUpdate, session: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        signal = update_signal_status(session, signal_id, request.status)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="signal not found") from exc
    return signal_payload(signal)
