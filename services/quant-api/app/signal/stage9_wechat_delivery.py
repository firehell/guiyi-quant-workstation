from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http.client import RemoteDisconnected
import json
import os
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.signal import SignalEvent, SignalNotification
from app.signal.events import signal_event_payload
from app.signal.stage9_gate import SENSITIVE_KEY_PARTS, evaluate_stage9_signal_event_gate
from app.signal.stage9_wechat import CHANNEL, build_stage9_wechat_payload_from_basis
from app.services.htdy_s6_09_wecom_gate import (
    HtDyS609Authorization,
    canonical_hash,
)

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_RETRY_DELAY_SECONDS = 300
DEFAULT_TIMEOUT_SECONDS = 8.0


@dataclass(frozen=True)
class SenderResult:
    success: bool
    status_code: int | None = None
    response_payload: dict[str, Any] | None = None
    error_type: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class DeliveryResult:
    event_id: int
    notification_id: int | None
    status: str
    attempt_count: int
    max_attempts: int
    blocked_reasons: list[str]
    http_status: int | None = None
    error_type: str | None = None
    error_message: str | None = None
    next_retry_at: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "notification_id": self.notification_id,
            "status": self.status,
            "attempt_count": self.attempt_count,
            "max_attempts": self.max_attempts,
            "http_status": self.http_status,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "blocked_reasons": self.blocked_reasons,
            "next_retry_at": self.next_retry_at,
        }


class Stage9WechatSender(Protocol):
    def send(self, webhook_url: str, payload: dict[str, Any], timeout_seconds: float) -> SenderResult:
        ...


class UrllibEnterpriseWechatSender:
    def send(self, webhook_url: str, payload: dict[str, Any], timeout_seconds: float) -> SenderResult:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            webhook_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - webhook URL is operator-provided env.
                status_code = response.status
                response_text = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            response_text = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
            return SenderResult(
                success=False,
                status_code=exc.code,
                response_payload=_parse_json_response(response_text),
                error_type="http_error",
                error_message=response_text or str(exc),
            )
        except (TimeoutError, URLError, RemoteDisconnected) as exc:
            return SenderResult(success=False, error_type=exc.__class__.__name__, error_message=str(exc))

        response_payload = _parse_json_response(response_text)
        errcode = response_payload.get("errcode") if response_payload else None
        success = 200 <= status_code < 300 and errcode == 0
        if success:
            return SenderResult(success=True, status_code=status_code, response_payload=response_payload)
        return SenderResult(
            success=False,
            status_code=status_code,
            response_payload=response_payload,
            error_type="wecom_error",
            error_message=response_text,
        )


class Stage9WechatDeliveryService:
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

    def send_event(
        self,
        event_id: int,
        *,
        authorization: HtDyS609Authorization | Any | None = None,
    ) -> DeliveryResult:
        event = self.session.get(SignalEvent, event_id)
        if event is None:
            raise ValueError("signal event not found")

        gate = evaluate_stage9_signal_event_gate(event)
        wechat_payload = (
            build_stage9_wechat_payload_from_basis(gate["payload_basis"])
            if gate["allowed"]
            else None
        )
        if gate["allowed"] and not gate["delivery_allowed"]:
            authorization_reasons = _htdy_authorization_blocked_reasons(
                event=event,
                authorization=authorization,
                wechat_payload=wechat_payload or {},
                now=self.now,
            )
            if authorization_reasons:
                return DeliveryResult(
                    event_id=event.id,
                    notification_id=None,
                    status="blocked",
                    attempt_count=0,
                    max_attempts=self.max_attempts,
                    blocked_reasons=authorization_reasons,
                )

        notification = self._get_or_create_notification(event)
        if notification.status in {"sent", "skipped"}:
            return _result_from_notification(event.id, notification)
        if notification.status == "failed" and notification.attempt_count >= notification.max_attempts:
            return _result_from_notification(event.id, notification)
        if notification.status == "retry_pending" and notification.next_retry_at and _is_after(notification.next_retry_at, self.now):
            return _result_from_notification(event.id, notification)

        self._set_base_payload(notification, gate, wechat_payload)
        if not gate["allowed"]:
            notification.status = "skipped"
            notification.error_message = "stage9 gate blocked"
            notification.last_error_type = "stage9_gate_blocked"
            notification.next_retry_at = None
            self.session.commit()
            return _result_from_notification(event.id, notification)

        webhook_url = str(self.environ.get("QYWX_WEBHOOK_URL") or "").strip()
        if not webhook_url:
            notification.status = "failed"
            notification.error_message = "QYWX_WEBHOOK_URL is not configured"
            notification.last_error_type = "missing_webhook"
            notification.next_retry_at = None
            notification.payload = _merge_delivery_payload(
                notification.payload,
                status="failed",
                error_type="missing_webhook",
                attempt_count=notification.attempt_count,
                max_attempts=notification.max_attempts,
            )
            self.session.commit()
            return _result_from_notification(event.id, notification)

        sender_result = self.sender.send(webhook_url, wechat_payload or {}, self.timeout_seconds)
        notification.attempt_count += 1
        notification.last_attempt_at = self.now
        notification.response_status_code = sender_result.status_code
        notification.last_error_type = sender_result.error_type
        notification.error_message = redact_message(sender_result.error_message)

        if sender_result.success:
            notification.status = "sent"
            notification.sent_at = self.now
            notification.next_retry_at = None
        elif (
            notification.attempt_count >= notification.max_attempts
            or not _is_retryable_sender_result(sender_result)
        ):
            notification.status = "failed"
            notification.next_retry_at = None
        else:
            notification.status = "retry_pending"
            notification.next_retry_at = self.now + timedelta(seconds=self.retry_delay_seconds)

        notification.payload = _merge_delivery_payload(
            notification.payload,
            status=notification.status,
            error_type=notification.last_error_type,
            attempt_count=notification.attempt_count,
            max_attempts=notification.max_attempts,
            http_status=notification.response_status_code,
            response_payload=_sanitize(sender_result.response_payload or {}),
            next_retry_at=_iso(notification.next_retry_at),
        )
        self.session.commit()
        return _result_from_notification(event.id, notification)

    def _get_or_create_notification(self, event: SignalEvent) -> SignalNotification:
        dedupe_key = stage9_wechat_dedupe_key(event.id)
        notification = self.session.scalar(select(SignalNotification).where(SignalNotification.dedupe_key == dedupe_key))
        if notification is not None:
            return notification
        notification = SignalNotification(
            event_id=event.id,
            signal_id=event.signal_id,
            task_no=event.task_no,
            dedupe_key=dedupe_key,
            event_type=event.event_type,
            channel=CHANNEL,
            status="pending",
            payload={},
            attempt_count=0,
            max_attempts=self.max_attempts,
        )
        self.session.add(notification)
        self.session.flush()
        return notification

    @staticmethod
    def _set_base_payload(notification: SignalNotification, gate: dict[str, Any], wechat_payload: dict[str, Any] | None) -> None:
        notification.payload = _sanitize(
            {
                "allowed": gate["allowed"],
                "blocked_reasons": gate["blocked_reasons"],
                "delivery_allowed": gate["delivery_allowed"],
                "delivery_blocked_reasons": gate["delivery_blocked_reasons"],
                "payload_basis": gate["payload_basis"],
                "wechat_payload": wechat_payload,
                "delivery": {
                    "status": notification.status,
                    "attempt_count": notification.attempt_count,
                    "max_attempts": notification.max_attempts,
                },
            }
        )


def retry_pending_notifications(
    session: Session,
    *,
    sender: Stage9WechatSender | None = None,
    environ: Mapping[str, str] | None = None,
    now: datetime | None = None,
    limit: int = 10,
) -> list[DeliveryResult]:
    current_time = now or datetime.now(UTC)
    rows = session.scalars(
        select(SignalNotification)
        .where(
            SignalNotification.channel == CHANNEL,
            SignalNotification.status == "retry_pending",
            SignalNotification.next_retry_at <= current_time,
            SignalNotification.event_id.is_not(None),
        )
        .order_by(SignalNotification.next_retry_at.asc(), SignalNotification.id.asc())
        .limit(limit)
    )
    results: list[DeliveryResult] = []
    service = Stage9WechatDeliveryService(session, sender=sender, environ=environ, now=current_time)
    for notification in rows:
        if notification.event_id is not None:
            results.append(service.send_event(notification.event_id))
    return results


def latest_stage9_wechat_notification(session: Session, event_id: int) -> SignalNotification | None:
    return session.scalar(
        select(SignalNotification)
        .where(SignalNotification.event_id == event_id, SignalNotification.channel == CHANNEL)
        .order_by(SignalNotification.created_at.desc(), SignalNotification.id.desc())
        .limit(1)
    )


def stage9_wechat_dedupe_key(event_id: int) -> str:
    return f"{CHANNEL}:signal_event:{event_id}"


def notification_payload(notification: SignalNotification) -> dict[str, Any]:
    return {
        "id": notification.id,
        "event_id": notification.event_id,
        "signal_id": notification.signal_id,
        "task_no": notification.task_no,
        "dedupe_key": notification.dedupe_key,
        "event_type": notification.event_type,
        "channel": notification.channel,
        "status": notification.status,
        "payload": _sanitize(notification.payload or {}),
        "error_message": redact_message(notification.error_message),
        "attempt_count": notification.attempt_count,
        "max_attempts": notification.max_attempts,
        "last_attempt_at": _iso(notification.last_attempt_at),
        "next_retry_at": _iso(notification.next_retry_at),
        "last_error_type": notification.last_error_type,
        "response_status_code": notification.response_status_code,
        "created_at": _iso(notification.created_at),
        "sent_at": _iso(notification.sent_at),
    }


def redact_message(value: str | None) -> str | None:
    if value is None:
        return None
    redacted = str(value)
    for key, secret in os.environ.items():
        if secret and _is_sensitive_text(key):
            redacted = redacted.replace(secret, "[redacted]")
    return _redact_sensitive_urls(redacted)


def _merge_delivery_payload(payload: dict[str, Any], **delivery: Any) -> dict[str, Any]:
    merged = dict(payload or {})
    existing_delivery = dict(merged.get("delivery") or {})
    existing_delivery.update({key: value for key, value in delivery.items() if value is not None})
    merged["delivery"] = existing_delivery
    return _sanitize(merged)


def _result_from_notification(event_id: int, notification: SignalNotification) -> DeliveryResult:
    blocked_reasons = []
    if isinstance(notification.payload, dict):
        blocked_reasons = list(notification.payload.get("blocked_reasons") or [])
    return DeliveryResult(
        event_id=event_id,
        notification_id=notification.id,
        status=notification.status,
        attempt_count=notification.attempt_count,
        max_attempts=notification.max_attempts,
        http_status=notification.response_status_code,
        error_type=notification.last_error_type,
        error_message=redact_message(notification.error_message),
        blocked_reasons=blocked_reasons,
        next_retry_at=_iso(notification.next_retry_at),
    )


def _parse_json_response(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_sensitive_text(key_text):
                continue
            clean[key_text] = _sanitize(item)
        return clean
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        return redact_message(value) if _is_sensitive_text(value) else value
    return value


def _is_sensitive_text(value: str) -> bool:
    normalized = value.lower()
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def _redact_sensitive_urls(value: str) -> str:
    words = value.split()
    return " ".join("[redacted]" if _is_sensitive_text(word) else word for word in words)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _is_after(left: datetime, right: datetime) -> bool:
    if left.tzinfo is None and right.tzinfo is not None:
        right = right.replace(tzinfo=None)
    elif left.tzinfo is not None and right.tzinfo is None:
        left = left.replace(tzinfo=None)
    return left > right


def _htdy_authorization_blocked_reasons(
    *,
    event: SignalEvent,
    authorization: HtDyS609Authorization | Any | None,
    wechat_payload: dict[str, Any],
    now: datetime,
) -> list[str]:
    if authorization is None:
        return ["htdy_observation_delivery_requires_separate_gate"]
    expected_dedupe_key = stage9_wechat_dedupe_key(event.id)
    scope = getattr(authorization, "authorization_scope", "")
    if (
        authorization.event_id != event.id
        or authorization.signal_id != event.signal_id
        or authorization.event_sha256
        != canonical_hash(signal_event_payload(event))
        or authorization.dedupe_key != expected_dedupe_key
        or authorization.max_attempts != DEFAULT_MAX_ATTEMPTS
        or authorization.rendered_message_sha256
        != canonical_hash(wechat_payload)
    ):
        return [
            "htdy_s6_10_authorization_mismatch"
            if scope == "s6_10_one_day_bounded"
            else "htdy_s6_09_authorization_mismatch"
        ]
    if _is_after(now, authorization.retry_deadline):
        return [
            "htdy_s6_10_authorization_expired"
            if scope == "s6_10_one_day_bounded"
            else "htdy_s6_09_authorization_expired"
        ]
    return []


def _is_retryable_sender_result(result: SenderResult) -> bool:
    if result.status_code is not None:
        return (
            result.status_code in {408, 429}
            or 500 <= result.status_code <= 599
        )
    return result.error_type in {
        "TimeoutError",
        "URLError",
        "RemoteDisconnected",
    }
