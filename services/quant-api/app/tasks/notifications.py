from __future__ import annotations

import os

from app.db.session import SessionLocal
from app.signal.stage9_wechat_delivery import Stage9WechatDeliveryService
from app.signal.htdy_wechat_delivery import HtdyWechatDeliveryService


def deliver_live_notification_task(event_id: int) -> dict[str, object]:
    """Only the dedicated notification worker may read the webhook environment."""
    if not _enabled("GUIYI_WECHAT_AUTOSEND_ENABLED"):
        return {"event_id": event_id, "status": "disabled", "attempt_count": 0}
    with SessionLocal() as session:
        result = Stage9WechatDeliveryService(session).send_event(event_id)
        return result.to_public_dict()


def deliver_htdy_observation_alert_task(alert_id: int) -> dict[str, object]:
    """Deliver one HTDY observation only when its dedicated flag is enabled."""

    if not _enabled("GUIYI_HTDY_WECOM_AUTOSEND_ENABLED"):
        return {"alert_id": alert_id, "status": "disabled", "attempt_count": 0}
    with SessionLocal() as session:
        result = HtdyWechatDeliveryService(session).send_alert(alert_id)
        return result.to_public_dict()


def _enabled(name: str) -> bool:
    return str(os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"}
