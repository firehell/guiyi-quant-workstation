from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.signal import SignalEvent, SignalNotification
from app.signal.stage9_wechat_delivery import (
    DeliveryResult,
    SenderResult,
    Stage9WechatDeliveryService,
    retry_pending_notifications,
)


def test_notification_payload_drops_retired_authorization_metadata() -> None:
    notification = SimpleNamespace(
        status="skipped",
        attempt_count=0,
        max_attempts=3,
        payload=None,
    )
    authorization = SimpleNamespace(
        authorization_scope="retired_scope",
        authorization_hash="a" * 64,
        event_id=1,
        dedupe_key="dedupe",
        event_sha256="b" * 64,
        rendered_message_sha256="c" * 64,
    )

    Stage9WechatDeliveryService._set_base_payload(
        notification,
        {
            "allowed": False,
            "blocked_reasons": ["default_off"],
            "delivery_allowed": False,
            "delivery_blocked_reasons": ["default_off"],
            "payload_basis": {},
        },
        None,
        authorization=authorization,
    )

    assert set(notification.payload) == {
        "allowed",
        "blocked_reasons",
        "delivery_allowed",
        "delivery_blocked_reasons",
        "payload_basis",
        "wechat_payload",
        "delivery",
    }


def test_allowed_event_fake_success_writes_sent_notification_without_secret() -> None:
    TestingSessionLocal = _session_factory()
    sender = FakeSender(SenderResult(success=True, status_code=200, response_payload={"errcode": 0, "errmsg": "ok"}))
    with TestingSessionLocal() as session:
        event = _event()
        session.add(event)
        session.commit()

        result = Stage9WechatDeliveryService(session, sender=sender, environ={"QYWX_WEBHOOK_URL": "https://example.invalid/token"}).send_event(event.id)

        assert result.status == "sent"
        assert result.notification_id is not None
        assert result.attempt_count == 1
        assert result.http_status == 200
        assert len(sender.requests) == 1

        notification = session.get(SignalNotification, result.notification_id)
        assert notification is not None
        assert notification.event_id == event.id
        assert notification.signal_id == event.signal_id
        assert notification.channel == "enterprise_wechat"
        assert notification.status == "sent"
        assert notification.attempt_count == 1
        assert notification.max_attempts == 3
        assert notification.sent_at is not None
        assert notification.last_attempt_at is not None
        assert notification.next_retry_at is None
        assert notification.response_status_code == 200
        assert _contains_no_secret_words(result.to_public_dict())
        assert _contains_no_secret_words(notification.payload)


def test_same_event_does_not_send_twice_after_sent() -> None:
    TestingSessionLocal = _session_factory()
    sender = FakeSender(SenderResult(success=True, status_code=200, response_payload={"errcode": 0}))
    with TestingSessionLocal() as session:
        event = _event()
        session.add(event)
        session.commit()
        service = Stage9WechatDeliveryService(session, sender=sender, environ={"QYWX_WEBHOOK_URL": "https://example.invalid/token"})

        first = service.send_event(event.id)
        second = service.send_event(event.id)

        assert first.status == "sent"
        assert second.status == "sent"
        assert second.notification_id == first.notification_id
        assert len(sender.requests) == 1
        assert session.scalar(select(func.count()).select_from(SignalNotification)) == 1


def test_gate_blocked_event_writes_skipped_without_sender_call() -> None:
    TestingSessionLocal = _session_factory()
    sender = FakeSender(SenderResult(success=True, status_code=200, response_payload={"errcode": 0}))
    with TestingSessionLocal() as session:
        event = _event(actual_contract=None)
        session.add(event)
        session.commit()

        result = Stage9WechatDeliveryService(session, sender=sender, environ={"QYWX_WEBHOOK_URL": "https://example.invalid/token"}).send_event(event.id)

        assert result.status == "skipped"
        assert "actual_contract_missing" in result.blocked_reasons
        assert len(sender.requests) == 0
        notification = session.get(SignalNotification, result.notification_id)
        assert notification is not None
        assert notification.status == "skipped"
        assert notification.attempt_count == 0


def test_missing_webhook_writes_failed_without_sender_call() -> None:
    TestingSessionLocal = _session_factory()
    sender = FakeSender(SenderResult(success=True, status_code=200, response_payload={"errcode": 0}))
    with TestingSessionLocal() as session:
        event = _event()
        session.add(event)
        session.commit()

        result = Stage9WechatDeliveryService(session, sender=sender, environ={}).send_event(event.id)

        assert result.status == "failed"
        assert result.error_type == "missing_webhook"
        assert len(sender.requests) == 0
        notification = session.get(SignalNotification, result.notification_id)
        assert notification is not None
        assert notification.status == "failed"
        assert notification.last_error_type == "missing_webhook"
        assert "QYWX_WEBHOOK_URL is not configured" in (notification.error_message or "")


def test_transient_failure_writes_retry_pending() -> None:
    TestingSessionLocal = _session_factory()
    sender = FakeSender(SenderResult(success=False, status_code=500, error_type="http_error", error_message="bad https://example.invalid/token"))
    with TestingSessionLocal() as session:
        event = _event()
        session.add(event)
        session.commit()

        result = Stage9WechatDeliveryService(session, sender=sender, environ={"QYWX_WEBHOOK_URL": "https://example.invalid/token"}).send_event(event.id)

        assert result.status == "retry_pending"
        assert result.attempt_count == 1
        assert result.http_status == 500
        assert result.error_type == "http_error"
        assert result.next_retry_at is not None
        assert _contains_no_secret_words(result.to_public_dict())
        notification = session.get(SignalNotification, result.notification_id)
        assert notification is not None
        assert notification.status == "retry_pending"
        assert notification.attempt_count == 1
        assert notification.next_retry_at is not None
        assert "https://example.invalid/token" not in (notification.error_message or "")


def test_non_retryable_http_failure_stops_immediately() -> None:
    TestingSessionLocal = _session_factory()
    sender = FakeSender(
        SenderResult(
            success=False,
            status_code=400,
            error_type="http_error",
            error_message="bad request",
        )
    )
    with TestingSessionLocal() as session:
        event = _event()
        session.add(event)
        session.commit()

        result = Stage9WechatDeliveryService(
            session,
            sender=sender,
            environ={"QYWX_WEBHOOK_URL": "https://example.invalid/token"},
        ).send_event(event.id)

        assert result.status == "failed"
        assert result.attempt_count == 1
        assert result.next_retry_at is None


def test_third_failure_marks_failed_without_infinite_retry() -> None:
    TestingSessionLocal = _session_factory()
    sender = FakeSender(SenderResult(success=False, status_code=503, error_type="http_error", error_message="temporary fail"))
    with TestingSessionLocal() as session:
        event = _event()
        session.add(event)
        session.commit()
        service = Stage9WechatDeliveryService(session, sender=sender, environ={"QYWX_WEBHOOK_URL": "https://example.invalid/token"})

        first = service.send_event(event.id)
        notification = session.get(SignalNotification, first.notification_id)
        assert notification is not None
        notification.next_retry_at = datetime.now(UTC) - timedelta(seconds=1)
        second = service.send_event(event.id)
        notification.next_retry_at = datetime.now(UTC) - timedelta(seconds=1)
        third = service.send_event(event.id)
        fourth = service.send_event(event.id)

        assert second.status == "retry_pending"
        assert third.status == "failed"
        assert fourth.status == "failed"
        assert third.attempt_count == 3
        assert len(sender.requests) == 3
        assert notification.status == "failed"
        assert notification.next_retry_at is None


def test_retry_pending_only_processes_due_notifications() -> None:
    TestingSessionLocal = _session_factory()
    sender = FakeSender(SenderResult(success=True, status_code=200, response_payload={"errcode": 0}))
    with TestingSessionLocal() as session:
        due_event = _event(event_key="signal_created:due", signal_id=1)
        future_event = _event(event_key="signal_created:future", signal_id=2)
        session.add_all([due_event, future_event])
        session.commit()
        due_notification = _notification(due_event, next_retry_at=datetime.now(UTC) - timedelta(seconds=1))
        future_notification = _notification(future_event, next_retry_at=datetime.now(UTC) + timedelta(minutes=10))
        session.add_all([due_notification, future_notification])
        session.commit()

        results = retry_pending_notifications(
            session,
            sender=sender,
            environ={"QYWX_WEBHOOK_URL": "https://example.invalid/token"},
            limit=10,
        )

        assert [item.event_id for item in results] == [due_event.id]
        assert len(sender.requests) == 1
        assert session.get(SignalNotification, due_notification.id).status == "sent"
        assert session.get(SignalNotification, future_notification.id).status == "retry_pending"


def test_notification_status_api_is_unmounted() -> None:
    client = TestClient(app)
    response = client.get("/api/signals/events/1/stage9-wechat/notification")
    assert response.status_code == 404


class FakeSender:
    def __init__(self, result: SenderResult) -> None:
        self.result = result
        self.requests: list[dict] = []

    def send(self, webhook_url: str, payload: dict, timeout_seconds: float) -> SenderResult:
        self.requests.append({"webhook_url": webhook_url, "payload": payload, "timeout_seconds": timeout_seconds})
        return self.result


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    return TestingSessionLocal


def _event(**overrides) -> SignalEvent:
    values = {
        "event_key": "signal_created:jm:JM2609:15m:20260707T150000",
        "event_type": "signal_created",
        "signal_id": 1,
        "task_no": "task-stage9-wechat",
        "source_mode": "live_confirmed",
        "strategy_name": "jm_v1b_daily_direction_fast_entry",
        "strategy_version": "v1b.0",
        "watchlist_code": "jm_v1b",
        "symbol": "jm",
        "contract": "JM2609",
        "product": "jm",
        "continuous_contract": "jm.MAIN",
        "actual_contract": "JM2609",
        "dominant_mapping_date": date(2026, 7, 7),
        "exchange": "DCE",
        "period": "15m",
        "signal_time": datetime(2026, 7, 7, 15, 0),
        "bar_start": datetime(2026, 7, 7, 14, 45),
        "bar_end": datetime(2026, 7, 7, 15, 0),
        "trigger_price": 1234.5,
        "provider": "rqdata",
        "source": "live_db_actual_contract",
        "direction": "long",
        "signal_status": "entry_signal",
        "lifecycle_status": "new",
        "score_bucket": 80,
        "data_role": "primary",
        "quality_status": {"status": "passed"},
        "payload": {"signal": {"reason": "confirmed bar", "token": "should-not-leak"}},
        "profile_id": "live_observation_v1",
        "market_data_file_id": 101,
    }
    values.update(overrides)
    payload = dict(values.get("payload") or {})
    payload.setdefault("formal_lineage", _formal_lineage())
    values["payload"] = payload
    return SignalEvent(**values)


def _formal_lineage() -> dict:
    return {
        "schema_version": "signal_review_lineage_v1",
        "resolver_name": "ProfileLineageResolver",
        "resolver_contract_version": "signal_profile_v1",
        "quality_policy": "passed_only",
        "primary": {
            "profile_id": "live_observation_v1",
            "market_data_file_id": 101,
            "provider": "rqdata",
            "data_role": "primary",
            "quality_status": "passed",
        },
        "contract": {
            "continuous_contract": "jm.MAIN",
            "actual_contract": "JM2609",
            "dominant_mapping_date": "2026-07-07",
        },
        "bar": {
            "bar_start": "2026-07-07T14:45:00",
            "bar_end": "2026-07-07T15:00:00",
            "trigger_price": 1234.5,
            "confirmation_mode": "live_confirmed",
            "bar_status": "confirmed",
            "live_bar_id": 501,
            "live_bar_revision": 1,
            "confirmed_at": "2026-07-07T15:00:01+00:00",
        },
    }


def _notification(event: SignalEvent, *, next_retry_at: datetime | None = None) -> SignalNotification:
    return SignalNotification(
        event_id=event.id,
        signal_id=event.signal_id,
        task_no=event.task_no,
        dedupe_key=f"enterprise_wechat:signal_event:{event.id}",
        event_type=event.event_type,
        channel="enterprise_wechat",
        status="retry_pending",
        payload={"blocked_reasons": [], "delivery": {"status": "retry_pending"}},
        attempt_count=1,
        max_attempts=3,
        next_retry_at=next_retry_at,
        last_error_type="http_error",
        error_message="temporary fail",
    )


def _contains_no_secret_words(payload: dict | DeliveryResult) -> bool:
    text = json.dumps(payload, ensure_ascii=False, default=str).lower()
    return not any(secret in text for secret in ("webhook", "token", "password", "cookie", "secret"))
