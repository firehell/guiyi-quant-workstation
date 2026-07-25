from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.models.signal import HtdyObservationAlert, SignalNotification
from app.signal.htdy_wechat_delivery import EVENT_TYPE, SOURCE_KIND
from app.signal.stage9_wechat import CHANNEL


@dataclass(frozen=True)
class HtdyNotificationDispatchResult:
    status: str
    enabled: bool
    new_enqueued: int
    retry_enqueued: int
    alert_ids: tuple[int, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "enabled": self.enabled,
            "new_enqueued": self.new_enqueued,
            "retry_enqueued": self.retry_enqueued,
            "alert_ids": list(self.alert_ids),
        }


class HtdyNotificationDispatchService:
    def __init__(
        self,
        session: Session,
        queue: Any,
        *,
        now: datetime | None = None,
    ) -> None:
        self.session = session
        self.queue = queue
        self.now = now or datetime.now(UTC)

    def enqueue_due(
        self,
        *,
        enabled: bool,
        limit: int = 100,
    ) -> HtdyNotificationDispatchResult:
        if not enabled:
            return HtdyNotificationDispatchResult("disabled", False, 0, 0, ())
        notification_exists = exists().where(
            SignalNotification.observation_alert_id == HtdyObservationAlert.id,
            SignalNotification.source_kind == SOURCE_KIND,
            SignalNotification.channel == CHANNEL,
        )
        alerts = list(
            self.session.scalars(
                select(HtdyObservationAlert)
                .where(~notification_exists)
                .order_by(HtdyObservationAlert.id.asc())
                .limit(limit)
            )
        )
        alert_ids: list[int] = []
        for alert in alerts:
            notification = SignalNotification(
                event_id=None,
                observation_alert_id=alert.id,
                source_kind=SOURCE_KIND,
                signal_id=None,
                task_no=None,
                dedupe_key=f"{CHANNEL}:{SOURCE_KIND}:{alert.id}",
                event_type=EVENT_TYPE,
                channel=CHANNEL,
                status="pending",
                payload={
                    "dispatch": {
                        "source_kind": SOURCE_KIND,
                        "queued": True,
                    }
                },
                attempt_count=0,
                max_attempts=3,
            )
            self.session.add(notification)
            self.session.flush()
            alert.notification_status = "queued"
            self._enqueue(alert.id, attempt=1)
            alert_ids.append(alert.id)
        retry_count = 0
        remaining = max(0, limit - len(alert_ids))
        due_notifications = list(
            self.session.scalars(
                select(SignalNotification)
                .where(
                    SignalNotification.source_kind == SOURCE_KIND,
                    SignalNotification.channel == CHANNEL,
                    SignalNotification.observation_alert_id.is_not(None),
                    SignalNotification.status == "retry_pending",
                    SignalNotification.next_retry_at <= self.now,
                    SignalNotification.attempt_count
                    < SignalNotification.max_attempts,
                )
                .order_by(
                    SignalNotification.next_retry_at.asc(),
                    SignalNotification.id.asc(),
                )
                .limit(remaining)
            )
        )
        for notification in due_notifications:
            alert_id = int(notification.observation_alert_id)
            self._enqueue(alert_id, attempt=notification.attempt_count + 1)
            alert_ids.append(alert_id)
            retry_count += 1
        return HtdyNotificationDispatchResult(
            "enqueued" if alert_ids else "idle",
            True,
            len(alert_ids) - retry_count,
            retry_count,
            tuple(alert_ids),
        )

    def _enqueue(self, alert_id: int, *, attempt: int) -> None:
        self.queue.enqueue(
            "app.tasks.notifications.deliver_htdy_observation_alert_task",
            alert_id,
            job_id=f"htdy-wechat:{alert_id}:attempt:{attempt}",
            job_timeout=30,
            result_ttl=86400,
            failure_ttl=604800,
        )


__all__ = [
    "HtdyNotificationDispatchResult",
    "HtdyNotificationDispatchService",
]
