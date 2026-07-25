from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import os
from typing import Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.signal import HtdyObservationAlert, SignalNotification
from app.signal.htdy_wechat import build_htdy_wechat_payload
from app.signal.stage9_wechat import CHANNEL
from app.signal.stage9_wechat_delivery import (
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_RETRY_DELAY_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    Stage9WechatSender,
    UrllibEnterpriseWechatSender,
    redact_message,
)


SOURCE_KIND = "htdy_observation"
EVENT_TYPE = "htdy_observation_created"


@dataclass(frozen=True)
class HtdyDeliveryResult:
    alert_id: int
    notification_id: int | None
    status: str
    attempt_count: int
    max_attempts: int
    http_status: int | None = None
    error_type: str | None = None
    error_message: str | None = None
    next_retry_at: str | None = None

    def to_public_dict(self) -> dict[str, object]:
        return {
            "alert_id": self.alert_id,
            "notification_id": self.notification_id,
            "status": self.status,
            "attempt_count": self.attempt_count,
            "max_attempts": self.max_attempts,
            "http_status": self.http_status,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "next_retry_at": self.next_retry_at,
        }


class HtdyWechatDeliveryService:
    def __init__(
        self,
        session: Session,
        *,
        sender: Stage9WechatSender | None = None,
        environ: Mapping[str, str] | None = None,
        now: datetime | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        retry_delay_seconds: int = DEFAULT_RETRY_DELAY_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        self.session = session
        self.sender = sender or UrllibEnterpriseWechatSender()
        self.environ = environ if environ is not None else os.environ
        self.now = now or datetime.now(UTC)
        self.timeout_seconds = timeout_seconds
        self.retry_delay_seconds = retry_delay_seconds
        self.max_attempts = max_attempts

    def send_alert(self, alert_id: int) -> HtdyDeliveryResult:
        alert = self.session.get(HtdyObservationAlert, alert_id)
        if alert is None:
            raise ValueError("htdy observation alert not found")
        notification = self._get_or_create_notification(alert)
        if notification.status in {"sent", "skipped"}:
            return _result(alert.id, notification)
        if notification.status == "failed" and notification.attempt_count >= notification.max_attempts:
            return _result(alert.id, notification)
        if (
            notification.status == "retry_pending"
            and notification.next_retry_at
            and _is_after(notification.next_retry_at, self.now)
        ):
            return _result(alert.id, notification)

        blocked_reason = _blocked_reason(alert)
        wechat_payload = build_htdy_wechat_payload(alert) if blocked_reason is None else None
        notification.payload = {
            "allowed": blocked_reason is None,
            "blocked_reason": blocked_reason,
            "observation": {
                "alert_id": alert.id,
                "alert_key": alert.alert_key,
                "indicator_code": alert.indicator_code,
                "indicator_version": alert.indicator_version,
                "actual_contract": alert.actual_contract,
                "period": alert.period,
                "bar_end": alert.bar_end.isoformat(),
                "direction": alert.direction,
                "future_looking": True,
                "repainting_risk": "known",
                "not_trading_instruction": True,
            },
            "wechat_payload": wechat_payload,
            "delivery": {
                "status": notification.status,
                "attempt_count": notification.attempt_count,
                "max_attempts": notification.max_attempts,
            },
        }
        if blocked_reason:
            notification.status = "skipped"
            notification.last_error_type = "htdy_observation_gate_blocked"
            notification.error_message = blocked_reason
            alert.notification_status = "skipped"
            self.session.commit()
            return _result(alert.id, notification)

        webhook_url = str(self.environ.get("QYWX_WEBHOOK_URL") or "").strip()
        if not webhook_url:
            notification.status = "failed"
            notification.last_error_type = "missing_webhook"
            notification.error_message = "QYWX_WEBHOOK_URL is not configured"
            alert.notification_status = "failed"
            self.session.commit()
            return _result(alert.id, notification)

        sender_result = self.sender.send(
            webhook_url,
            wechat_payload or {},
            self.timeout_seconds,
        )
        notification.attempt_count += 1
        notification.last_attempt_at = self.now
        notification.response_status_code = sender_result.status_code
        notification.last_error_type = sender_result.error_type
        notification.error_message = redact_message(sender_result.error_message)
        if sender_result.success:
            notification.status = "sent"
            notification.sent_at = self.now
            notification.next_retry_at = None
        elif notification.attempt_count >= notification.max_attempts:
            notification.status = "failed"
            notification.next_retry_at = None
        else:
            notification.status = "retry_pending"
            notification.next_retry_at = self.now + timedelta(
                seconds=self.retry_delay_seconds
            )
        alert.notification_status = notification.status
        notification.payload["delivery"] = {
            "status": notification.status,
            "attempt_count": notification.attempt_count,
            "max_attempts": notification.max_attempts,
            "http_status": notification.response_status_code,
            "error_type": notification.last_error_type,
            "next_retry_at": _iso(notification.next_retry_at),
        }
        self.session.commit()
        return _result(alert.id, notification)

    def _get_or_create_notification(
        self,
        alert: HtdyObservationAlert,
    ) -> SignalNotification:
        dedupe_key = f"{CHANNEL}:{SOURCE_KIND}:{alert.id}"
        notification = self.session.scalar(
            select(SignalNotification).where(
                SignalNotification.dedupe_key == dedupe_key
            )
        )
        if notification is not None:
            return notification
        notification = SignalNotification(
            event_id=None,
            observation_alert_id=alert.id,
            source_kind=SOURCE_KIND,
            signal_id=None,
            task_no=None,
            dedupe_key=dedupe_key,
            event_type=EVENT_TYPE,
            channel=CHANNEL,
            status="pending",
            payload={},
            attempt_count=0,
            max_attempts=self.max_attempts,
        )
        self.session.add(notification)
        self.session.flush()
        return notification


def _blocked_reason(alert: HtdyObservationAlert) -> str | None:
    checks = (
        (alert.alert_policy == "htdy_original_repainting_realtime_v1", "alert_policy_invalid"),
        (alert.indicator_code == "huotian_dayou_original_v0", "indicator_invalid"),
        (alert.actual_contract and not alert.actual_contract.upper().endswith(".MAIN"), "actual_contract_invalid"),
        (alert.period == "15m", "period_invalid"),
        (alert.quality_status == "passed", "quality_invalid"),
        (alert.future_looking is True, "future_looking_metadata_missing"),
        (alert.repainting_risk == "known", "repainting_metadata_missing"),
        ((alert.payload or {}).get("not_trading_instruction") is True, "trading_warning_missing"),
    )
    return next((reason for allowed, reason in checks if not allowed), None)


def _result(
    alert_id: int,
    notification: SignalNotification,
) -> HtdyDeliveryResult:
    return HtdyDeliveryResult(
        alert_id=alert_id,
        notification_id=notification.id,
        status=notification.status,
        attempt_count=notification.attempt_count,
        max_attempts=notification.max_attempts,
        http_status=notification.response_status_code,
        error_type=notification.last_error_type,
        error_message=redact_message(notification.error_message),
        next_retry_at=_iso(notification.next_retry_at),
    )


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _is_after(left: datetime, right: datetime) -> bool:
    if left.tzinfo is None and right.tzinfo is not None:
        right = right.replace(tzinfo=None)
    elif left.tzinfo is not None and right.tzinfo is None:
        left = left.replace(tzinfo=None)
    return left > right


__all__ = [
    "HtdyDeliveryResult",
    "HtdyWechatDeliveryService",
    "SOURCE_KIND",
]
