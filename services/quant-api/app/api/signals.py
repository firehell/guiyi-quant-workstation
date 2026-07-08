from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.signal import SignalEvent, SignalScanTask, StrategySignal
from app.schemas.signal import (
    LiveSignalEvaluationRequest,
    LiveSignalEvaluationResponse,
    SignalEventOut,
    SignalScanRequest,
    SignalStatus,
    SignalStatusUpdate,
    Stage9WechatNotificationOut,
    Stage9WechatPreviewOut,
)
from app.signal.events import list_signal_events, signal_event_payload
from app.signal.stage9_wechat_delivery import latest_stage9_wechat_notification, notification_payload
from app.signal.stage9_wechat import build_stage9_wechat_preview
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
    product: str | None = None,
    continuous_contract: str | None = None,
    actual_contract: str | None = None,
    provider: str | None = None,
    source: str | None = None,
    data_role: str | None = None,
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
    if product:
        query = query.where(StrategySignal.product == product)
    if continuous_contract:
        query = query.where(StrategySignal.continuous_contract == continuous_contract)
    if actual_contract:
        query = query.where(StrategySignal.actual_contract == actual_contract)
    if provider:
        query = query.where(StrategySignal.provider == provider)
    if source:
        query = query.where(StrategySignal.source == source)
    if data_role:
        query = query.where(StrategySignal.data_role == data_role)
    if score_bucket is not None:
        query = query.where(StrategySignal.score_bucket == score_bucket)
    if direction:
        query = query.where(StrategySignal.direction == direction)
    rows = session.scalars(query.order_by(StrategySignal.signal_time.desc(), StrategySignal.score_bucket.desc()).limit(limit * 5 if status else limit))
    payloads = [signal_payload(row) for row in rows]
    if status:
        payloads = [item for item in payloads if item["status"] == status]
    return payloads[:limit]


@router.get("/events", response_model=list[SignalEventOut])
def get_signal_events(
    signal_id: int | None = None,
    task_no: str | None = None,
    symbol: str | None = None,
    event_type: str | None = None,
    source_mode: str | None = None,
    product: str | None = None,
    continuous_contract: str | None = None,
    actual_contract: str | None = None,
    provider: str | None = None,
    source: str | None = None,
    data_role: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    events = list_signal_events(
        session,
        signal_id=signal_id,
        task_no=task_no,
        symbol=symbol,
        event_type=event_type,
        source_mode=source_mode,
        product=product,
        continuous_contract=continuous_contract,
        actual_contract=actual_contract,
        provider=provider,
        source=source,
        data_role=data_role,
        limit=limit,
    )
    return [signal_event_payload(event) for event in events]


@router.get("/events/{event_id}/stage9-wechat/preview", response_model=Stage9WechatPreviewOut)
def preview_stage9_wechat(event_id: int, session: Session = Depends(get_db)) -> dict[str, Any]:
    event = session.get(SignalEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="signal event not found")
    return build_stage9_wechat_preview(event)


@router.get("/events/{event_id}/stage9-wechat/notification", response_model=Stage9WechatNotificationOut)
def get_stage9_wechat_notification(event_id: int, session: Session = Depends(get_db)) -> dict[str, Any]:
    event = session.get(SignalEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="signal event not found")
    notification = latest_stage9_wechat_notification(session, event_id)
    if notification is None:
        raise HTTPException(status_code=404, detail="stage9 wechat notification not found")
    return notification_payload(notification)


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


@router.get("/{signal_id}/events", response_model=list[SignalEventOut])
def get_events_for_signal(signal_id: int, limit: int = Query(default=100, ge=1, le=500), session: Session = Depends(get_db)) -> list[dict[str, Any]]:
    signal = session.get(StrategySignal, signal_id)
    if signal is None:
        raise HTTPException(status_code=404, detail="signal not found")
    return [signal_event_payload(event) for event in list_signal_events(session, signal_id=signal_id, limit=limit)]


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
