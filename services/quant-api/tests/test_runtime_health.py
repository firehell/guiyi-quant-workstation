from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.data_center import LiveAggregationCheckpoint, LiveIngestCheckpoint
from app.models.signal import SignalNotification
from app.services.runtime_health import build_runtime_health


def test_runtime_health_endpoint_returns_readonly_ok_payload(monkeypatch) -> None:
    TestingSessionLocal = _session_factory()
    now = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)
    with TestingSessionLocal() as session:
        session.add(_ingest_checkpoint(status="success", now=now))
        session.add(_aggregation_checkpoint(status="success", now=now))
        session.add(_notification(status="sent", now=now, payload={"token": "should-not-leak"}))
        session.commit()

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    monkeypatch.setattr("app.services.runtime_health.get_redis_connection", lambda: FakeRedis())
    monkeypatch.setattr("app.services.runtime_health._collect_rq_health", lambda connection: _rq_ok())
    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.get("/api/runtime/health")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["readonly"] is True
    assert payload["would_start_services"] is False
    assert payload["would_enqueue_jobs"] is False
    assert payload["would_send_notifications"] is False
    assert payload["components"]["db"]["status"] == "ok"
    assert payload["components"]["redis"]["status"] == "ok"
    assert payload["components"]["rq"]["worker_count"] == 1
    assert payload["components"]["live_checkpoints"]["ingest_count"] == 1
    assert payload["components"]["live_checkpoints"]["aggregation_count"] == 1
    assert payload["components"]["notification_retry"]["sent_count"] == 1
    assert _contains_no_secret_words(payload)


def test_runtime_health_returns_failed_payload_when_redis_unavailable() -> None:
    TestingSessionLocal = _session_factory()
    with TestingSessionLocal() as session:
        payload = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(exc=ConnectionError("redis password should-not-leak")),
            rq_collector=lambda connection: _rq_ok(),
            now=datetime(2026, 7, 9, 12, 0, tzinfo=UTC),
        )

    assert payload["status"] == "failed"
    assert payload["components"]["db"]["status"] == "ok"
    assert payload["components"]["redis"]["status"] == "failed"
    assert payload["components"]["redis"]["error_type"] == "ConnectionError"
    assert payload["components"]["redis"]["error_message"] is None
    assert payload["components"]["rq"]["status"] == "failed"
    assert payload["components"]["rq"]["error_type"] == "redis_unavailable"
    assert _contains_no_secret_words(payload)


def test_runtime_health_degrades_when_no_rq_workers() -> None:
    TestingSessionLocal = _session_factory()
    with TestingSessionLocal() as session:
        payload = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(),
            rq_collector=lambda connection: _rq_no_workers(),
            now=datetime(2026, 7, 9, 12, 0, tzinfo=UTC),
        )

    assert payload["status"] == "degraded"
    assert payload["components"]["rq"]["status"] == "degraded"
    assert payload["components"]["rq"]["worker_count"] == 0
    assert payload["components"]["live_checkpoints"]["status"] == "unknown"
    assert payload["components"]["notification_retry"]["status"] == "unknown"


def test_runtime_health_degrades_for_failed_live_checkpoint_and_due_retry() -> None:
    TestingSessionLocal = _session_factory()
    now = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)
    with TestingSessionLocal() as session:
        session.add(_ingest_checkpoint(status="failed", now=now, last_error_type="NoConfirmedBars"))
        session.add(_notification(status="retry_pending", now=now, next_retry_at=now - timedelta(minutes=1), last_error_type="http_error"))
        session.commit()

        payload = build_runtime_health(session, redis_factory=lambda: FakeRedis(), rq_collector=lambda connection: _rq_ok(), now=now)

    assert payload["status"] == "degraded"
    live = payload["components"]["live_checkpoints"]
    assert live["status"] == "degraded"
    assert live["status_counts"]["failed"] == 1
    assert live["latest_error"]["last_error_type"] == "NoConfirmedBars"
    notification = payload["components"]["notification_retry"]
    assert notification["status"] == "degraded"
    assert notification["retry_pending_count"] == 1
    assert notification["due_retry_count"] == 1
    assert notification["last_error_type_counts"]["http_error"] == 1


class FakeRedis:
    def __init__(self, exc: Exception | None = None) -> None:
        self.exc = exc

    def ping(self) -> bool:
        if self.exc is not None:
            raise self.exc
        return True


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    return TestingSessionLocal


def _rq_ok() -> dict:
    return {
        "status": "ok",
        "queues": [
            {
                "name": "guiyi-backtests",
                "status": "ok",
                "queued_count": 0,
                "started_count": 0,
                "failed_count": 0,
                "deferred_count": 0,
                "scheduled_count": 0,
                "error_type": None,
            }
        ],
        "worker_count": 1,
        "workers": [{"name": "worker-1", "state": "idle", "queues": ["guiyi-backtests"]}],
        "error_type": None,
        "error_message": None,
    }


def _rq_no_workers() -> dict:
    return {
        "status": "degraded",
        "queues": [],
        "worker_count": 0,
        "workers": [],
        "error_type": None,
        "error_message": None,
    }


def _ingest_checkpoint(*, status: str, now: datetime, last_error_type: str | None = None) -> LiveIngestCheckpoint:
    return LiveIngestCheckpoint(
        provider="rqdata",
        instrument_symbol="jm",
        contract_code="JM2609",
        period="1m",
        source_mode="poll_get_price_1m",
        last_confirmed_bar_at=now,
        last_polled_at=now,
        last_success_at=now if status == "success" else None,
        status=status,
        lag_seconds=30,
        consecutive_error_count=1 if status == "failed" else 0,
        last_error_type=last_error_type,
        last_error_message="secret token should not appear",
    )


def _aggregation_checkpoint(*, status: str, now: datetime) -> LiveAggregationCheckpoint:
    return LiveAggregationCheckpoint(
        provider="rqdata",
        instrument_symbol="jm",
        contract_code="JM2609",
        period="15m",
        source_period="1m",
        source_mode="live_1m_sequential_bucket",
        last_aggregated_bar_at=now,
        last_source_bar_at=now,
        last_run_at=now,
        last_success_at=now if status == "success" else None,
        status=status,
        lag_seconds=45,
        consecutive_error_count=0,
    )


def _notification(
    *,
    status: str,
    now: datetime,
    payload: dict | None = None,
    next_retry_at: datetime | None = None,
    last_error_type: str | None = None,
) -> SignalNotification:
    return SignalNotification(
        event_id=1,
        signal_id=1,
        task_no="task-runtime-health",
        dedupe_key=f"enterprise_wechat:runtime-health:{status}:{next_retry_at}",
        event_type="signal_created",
        channel="enterprise_wechat",
        status=status,
        payload=payload or {},
        error_message="https://example.invalid/webhook-token",
        attempt_count=1,
        max_attempts=3,
        last_attempt_at=now,
        next_retry_at=next_retry_at,
        last_error_type=last_error_type,
        response_status_code=500 if last_error_type else 200,
        sent_at=now if status == "sent" else None,
    )


def _contains_no_secret_words(payload: dict) -> bool:
    text = json.dumps(payload, ensure_ascii=False, default=str).lower()
    return not any(secret in text for secret in ("webhook", "token", "password", "cookie", "secret", "should-not-leak"))
