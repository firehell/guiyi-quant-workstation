from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from app.models.signal import SignalEvent, SignalNotification
from app.signal.stage9_gate import evaluate_stage9_signal_event_gate
from app.signal.stage9_wechat import CHANNEL
from app.signal.stage9_wechat_delivery import stage9_wechat_dedupe_key


@dataclass(frozen=True)
class NotificationDispatchResult:
    status: str
    enabled: bool
    new_enqueued: int
    retry_enqueued: int
    blocked: int
    event_ids: tuple[int, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "enabled": self.enabled,
            "new_enqueued": self.new_enqueued,
            "retry_enqueued": self.retry_enqueued,
            "blocked": self.blocked,
            "event_ids": list(self.event_ids),
        }


class NotificationDispatchService:
    """Enqueue eligible stage9 events; never imports or reads the webhook."""

    def __init__(self, session: Session, queue: Any, *, now: datetime | None = None) -> None:
        self.session = session
        self.queue = queue
        self.now = now or datetime.now(UTC)

    def enqueue_due(self, *, enabled: bool, limit: int = 100) -> NotificationDispatchResult:
        if not enabled:
            return NotificationDispatchResult("disabled", False, 0, 0, 0, ())

        event_ids: list[int] = []
        blocked = 0
        new_count = 0
        retry_count = 0
        notification_exists = exists().where(
            SignalNotification.event_id == SignalEvent.id,
            SignalNotification.channel == CHANNEL,
        )
        new_events = self.session.scalars(
            select(SignalEvent)
            .where(
                SignalEvent.event_type.in_(("signal_created", "signal_changed")),
                ~notification_exists,
            )
            .order_by(SignalEvent.id.asc())
            .limit(limit)
        )
        for event in new_events:
            gate = evaluate_stage9_signal_event_gate(event)
            if not gate["allowed"]:
                blocked += 1
                continue
            notification = SignalNotification(
                event_id=event.id,
                signal_id=event.signal_id,
                task_no=event.task_no,
                dedupe_key=stage9_wechat_dedupe_key(event.id),
                event_type=event.event_type,
                channel=CHANNEL,
                status="pending",
                payload={"dispatch": {"source_mode": event.source_mode, "queued": True}},
                attempt_count=0,
                max_attempts=3,
                next_retry_at=None,
            )
            self.session.add(notification)
            self.session.flush()
            self._enqueue(event.id, attempt=1)
            event_ids.append(event.id)
            new_count += 1

        remaining = max(0, limit - new_count)
        due_rows = self.session.scalars(
            select(SignalNotification)
            .join(SignalEvent, SignalEvent.id == SignalNotification.event_id)
            .where(
                SignalNotification.channel == CHANNEL,
                SignalNotification.attempt_count < SignalNotification.max_attempts,
                SignalNotification.event_id.is_not(None),
                or_(
                    (
                        (SignalNotification.status == "retry_pending")
                        & (SignalNotification.next_retry_at <= self.now)
                    ),
                    (
                        (SignalNotification.status == "pending")
                        & (SignalNotification.created_at <= self.now - timedelta(seconds=60))
                    ),
                ),
            )
            .order_by(SignalNotification.next_retry_at.asc(), SignalNotification.id.asc())
            .limit(remaining)
        )
        for notification in due_rows:
            event_id = int(notification.event_id)
            self._enqueue(event_id, attempt=notification.attempt_count + 1)
            event_ids.append(event_id)
            retry_count += 1

        status = "enqueued" if event_ids else "idle"
        return NotificationDispatchResult(status, True, new_count, retry_count, blocked, tuple(event_ids))

    def _enqueue(self, event_id: int, *, attempt: int) -> None:
        self.queue.enqueue(
            "app.tasks.notifications.deliver_live_notification_task",
            event_id,
            job_id=f"live-wechat:{event_id}:attempt:{attempt}",
            job_timeout=30,
            result_ttl=86400,
            failure_ttl=604800,
        )
