from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.signal import HtdyObservationAlert, SignalNotification
from app.schemas.signal import HtdyObservationAlertListOut, HtdyObservationAlertOut
from app.schemas.signal import (
    HtdyObservationPreviewOut,
    HtdyObservationPreviewRequest,
    Stage9WechatNotificationOut,
)
from app.signal.htdy_wechat_delivery import SOURCE_KIND
from app.signal.stage9_wechat import CHANNEL
from app.signal.stage9_wechat_delivery import notification_payload
from app.services.htdy_realtime_alert import HtdyRealtimeObservationEvaluator


router = APIRouter(prefix="/api/observations", tags=["observations"])


def get_htdy_evaluator(
    session: Session = Depends(get_db),
) -> HtdyRealtimeObservationEvaluator:
    return HtdyRealtimeObservationEvaluator(session)


@router.post("/htdy/preview", response_model=HtdyObservationPreviewOut)
def preview_htdy_observation(
    request: HtdyObservationPreviewRequest,
    evaluator: HtdyRealtimeObservationEvaluator = Depends(get_htdy_evaluator),
) -> dict[str, object]:
    try:
        return evaluator.preview(
            contract=request.contract,
            profile_id=request.profile_id,
            provider=request.provider,
            source_mode=request.source_mode,
            limit=request.limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/htdy/alerts", response_model=HtdyObservationAlertListOut)
def list_htdy_observation_alerts(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
) -> dict[str, object]:
    total = int(
        session.scalar(select(func.count()).select_from(HtdyObservationAlert)) or 0
    )
    alerts = list(
        session.scalars(
            select(HtdyObservationAlert)
            .order_by(HtdyObservationAlert.id.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    return {"total": total, "items": [_payload(alert) for alert in alerts]}


@router.get("/htdy/alerts/{alert_id}", response_model=HtdyObservationAlertOut)
def get_htdy_observation_alert(
    alert_id: int,
    session: Session = Depends(get_db),
) -> dict[str, object]:
    alert = session.get(HtdyObservationAlert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="htdy_observation_alert_not_found")
    return _payload(alert)


@router.get(
    "/htdy/alerts/{alert_id}/notification",
    response_model=Stage9WechatNotificationOut,
)
def get_htdy_observation_notification(
    alert_id: int,
    session: Session = Depends(get_db),
) -> dict[str, object]:
    notification = session.scalar(
        select(SignalNotification)
        .where(
            SignalNotification.observation_alert_id == alert_id,
            SignalNotification.source_kind == SOURCE_KIND,
            SignalNotification.channel == CHANNEL,
        )
        .order_by(SignalNotification.id.desc())
        .limit(1)
    )
    if notification is None:
        raise HTTPException(
            status_code=404,
            detail="htdy_observation_notification_not_found",
        )
    return notification_payload(notification)


def _payload(alert: HtdyObservationAlert) -> dict[str, object]:
    return {
        "id": alert.id,
        "alert_key": alert.alert_key,
        "alert_policy": alert.alert_policy,
        "indicator_code": alert.indicator_code,
        "indicator_version": alert.indicator_version,
        "strategy_name": alert.strategy_name,
        "strategy_version": alert.strategy_version,
        "symbol": alert.symbol,
        "continuous_contract": alert.continuous_contract,
        "actual_contract": alert.actual_contract,
        "dominant_mapping_date": alert.dominant_mapping_date.isoformat(),
        "period": alert.period,
        "bar_end": alert.bar_end.isoformat(),
        "trigger_price": alert.trigger_price,
        "direction": alert.direction,
        "source_mode": alert.source_mode,
        "provider": alert.provider,
        "data_role": alert.data_role,
        "quality_status": alert.quality_status,
        "profile_id": alert.profile_id,
        "market_data_file_id": alert.market_data_file_id,
        "live_bar_id": alert.live_bar_id,
        "live_bar_revision": alert.live_bar_revision,
        "confirmed_at": alert.confirmed_at.isoformat(),
        "future_looking": alert.future_looking,
        "repainting_risk": alert.repainting_risk,
        "alert_status": alert.alert_status,
        "notification_status": alert.notification_status,
        "payload": dict(alert.payload or {}),
        "created_at": alert.created_at.isoformat(),
    }


__all__ = ["get_htdy_evaluator", "router"]
