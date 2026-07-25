from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.signal import HtdyObservationAlert, SignalNotification
from app.signal.htdy_wechat import build_htdy_wechat_payload
from app.signal.htdy_wechat_delivery import HtdyWechatDeliveryService
from app.signal.stage9_wechat_delivery import SenderResult
from app.services.htdy_realtime_alert import (
    HtdyObservationAlertService,
    HtdyObservationCandidate,
)
from app.services.htdy_notification_dispatch import HtdyNotificationDispatchService
from app.tasks.notifications import deliver_htdy_observation_alert_task


class FakeSender:
    def __init__(self, result: SenderResult) -> None:
        self.result = result
        self.requests: list[dict] = []

    def send(self, webhook_url: str, payload: dict, timeout_seconds: float) -> SenderResult:
        self.requests.append(
            {
                "webhook_url": webhook_url,
                "payload": payload,
                "timeout_seconds": timeout_seconds,
            }
        )
        return self.result


class FakeQueue:
    def __init__(self) -> None:
        self.jobs: list[dict] = []

    def enqueue(self, function: str, alert_id: int, **kwargs):
        self.jobs.append(
            {"function": function, "alert_id": alert_id, **kwargs}
        )


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_htdy_message_explicitly_warns_future_repainting_and_no_trading() -> None:
    factory = _session_factory()
    with factory() as session:
        alert = _persist_alert(session)

        payload = build_htdy_wechat_payload(alert)
        content = payload["markdown"]["content"]

        assert "火天大有原版 XMA" in content
        assert "未来函数" in content
        assert "可能重绘" in content
        assert "不是交易指令" in content
        assert "不自动下单" in content


def test_successful_htdy_delivery_is_idempotent_and_scoped_to_alert() -> None:
    factory = _session_factory()
    sender = FakeSender(SenderResult(success=True, status_code=200, response_payload={"errcode": 0}))
    with factory() as session:
        alert = _persist_alert(session)
        service = HtdyWechatDeliveryService(
            session,
            sender=sender,
            environ={"QYWX_WEBHOOK_URL": "https://example.invalid/token"},
        )

        first = service.send_alert(alert.id)
        second = service.send_alert(alert.id)

        assert first.status == "sent"
        assert second.status == "sent"
        assert len(sender.requests) == 1
        assert session.scalar(select(func.count()).select_from(SignalNotification)) == 1
        notification = session.get(SignalNotification, first.notification_id)
        assert notification is not None
        assert notification.event_id is None
        assert notification.observation_alert_id == alert.id
        assert notification.source_kind == "htdy_observation"
        assert notification.max_attempts == 3
        assert alert.notification_status == "sent"


def test_htdy_delivery_stops_after_three_failures() -> None:
    factory = _session_factory()
    sender = FakeSender(
        SenderResult(
            success=False,
            status_code=503,
            error_type="http_error",
            error_message="temporary https://example.invalid/token",
        )
    )
    with factory() as session:
        alert = _persist_alert(session)
        service = HtdyWechatDeliveryService(
            session,
            sender=sender,
            environ={"QYWX_WEBHOOK_URL": "https://example.invalid/token"},
        )

        first = service.send_alert(alert.id)
        notification = session.get(SignalNotification, first.notification_id)
        assert notification is not None
        notification.next_retry_at = datetime.now(UTC) - timedelta(seconds=1)
        second = service.send_alert(alert.id)
        notification.next_retry_at = datetime.now(UTC) - timedelta(seconds=1)
        third = service.send_alert(alert.id)
        fourth = service.send_alert(alert.id)

        assert second.status == "retry_pending"
        assert third.status == "failed"
        assert fourth.status == "failed"
        assert len(sender.requests) == 3
        assert "https://example.invalid/token" not in (notification.error_message or "")
        assert alert.notification_status == "failed"


def test_htdy_dispatch_creates_one_pending_notification_and_one_job() -> None:
    factory = _session_factory()
    queue = FakeQueue()
    with factory() as session:
        alert = _persist_alert(session)
        service = HtdyNotificationDispatchService(session, queue)

        first = service.enqueue_due(enabled=True)
        second = service.enqueue_due(enabled=True)

        assert first.new_enqueued == 1
        assert second.new_enqueued == 0
        assert len(queue.jobs) == 1
        assert queue.jobs[0]["function"] == (
            "app.tasks.notifications.deliver_htdy_observation_alert_task"
        )
        notification = session.scalar(select(SignalNotification))
        assert notification is not None
        assert notification.observation_alert_id == alert.id
        assert notification.source_kind == "htdy_observation"
        assert alert.notification_status == "queued"


def test_htdy_dispatch_requeues_due_retry_with_bounded_attempt_number() -> None:
    factory = _session_factory()
    queue = FakeQueue()
    now = datetime(2026, 7, 27, 2, 0, tzinfo=UTC)
    with factory() as session:
        alert = _persist_alert(session)
        notification = SignalNotification(
            observation_alert_id=alert.id,
            source_kind="htdy_observation",
            dedupe_key=f"enterprise_wechat:htdy_observation:{alert.id}",
            event_type="htdy_observation_created",
            channel="enterprise_wechat",
            status="retry_pending",
            payload={},
            attempt_count=1,
            max_attempts=3,
            next_retry_at=now - timedelta(seconds=1),
        )
        session.add(notification)
        session.flush()

        result = HtdyNotificationDispatchService(
            session,
            queue,
            now=now,
        ).enqueue_due(enabled=True)

        assert result.retry_enqueued == 1
        assert queue.jobs[0]["job_id"] == f"htdy-wechat:{alert.id}:attempt:2"


def test_htdy_worker_task_is_fail_closed_when_dedicated_flag_is_off(
    monkeypatch,
) -> None:
    monkeypatch.delenv("GUIYI_HTDY_WECOM_AUTOSEND_ENABLED", raising=False)

    result = deliver_htdy_observation_alert_task(123)

    assert result == {
        "alert_id": 123,
        "status": "disabled",
        "attempt_count": 0,
    }


def test_htdy_notification_status_api_returns_scoped_record() -> None:
    factory = _session_factory()
    sender = FakeSender(
        SenderResult(success=True, status_code=200, response_payload={"errcode": 0})
    )
    with factory() as session:
        alert = _persist_alert(session)
        result = HtdyWechatDeliveryService(
            session,
            sender=sender,
            environ={"QYWX_WEBHOOK_URL": "https://example.invalid/token"},
        ).send_alert(alert.id)
        alert_id = alert.id
        notification_id = result.notification_id

    def override_get_db():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).get(
            f"/api/observations/htdy/alerts/{alert_id}/notification"
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["id"] == notification_id
        assert payload["observation_alert_id"] == alert_id
        assert payload["source_kind"] == "htdy_observation"
        assert payload["status"] == "sent"
        assert "token" not in str(payload).lower()
    finally:
        app.dependency_overrides.clear()


def _persist_alert(session) -> HtdyObservationAlert:
    candidate = HtdyObservationCandidate(
        symbol="jm",
        continuous_contract="JM.MAIN",
        actual_contract="JM2609",
        dominant_mapping_date=datetime(2026, 7, 27, tzinfo=UTC).date(),
        period="15m",
        bar_end=datetime(2026, 7, 27, 1, 15, tzinfo=UTC),
        trigger_price=1234.5,
        direction="long",
        bar_status="confirmed",
        quality_status="passed",
        provider="rqdata",
        data_role="primary",
        profile_id="live_observation_v1",
        market_data_file_id=42,
        live_bar_id=101,
        live_bar_revision=1,
        confirmed_at=datetime(2026, 7, 27, 1, 15, 1, tzinfo=UTC),
        lineage={
            "schema_version": "htdy_observation_lineage_v1",
            "future_looking": True,
            "repainting_risk": "known",
        },
    )
    result = HtdyObservationAlertService(session).persist(candidate)
    session.commit()
    assert result.alert_id is not None
    alert = session.get(HtdyObservationAlert, result.alert_id)
    assert alert is not None
    return alert
