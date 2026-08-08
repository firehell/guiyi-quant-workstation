from __future__ import annotations

from datetime import UTC, datetime
import json

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.services.runtime_health import _apply_worker_coverage, build_runtime_health


def test_runtime_health_endpoint_returns_readonly_ok_payload(monkeypatch) -> None:
    TestingSessionLocal = _session_factory()
    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    monkeypatch.setattr("app.services.runtime_health.get_redis_connection", lambda: FakeRedis())
    monkeypatch.setattr("app.services.runtime_health._collect_rq_health", lambda connection, **kwargs: _rq_ok())
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
    assert "scheduler" not in payload["components"]
    assert payload["components"]["live_checkpoints"]["status"] == "disabled"
    assert payload["components"]["live_checkpoints"]["retired"] is True
    assert payload["components"]["notification_retry"]["status"] == "disabled"
    assert payload["components"]["notification_retry"]["channel"] == "retired"
    archive = payload["components"]["archive"]
    assert archive["status"] == "disabled"
    assert archive["retired"] is True
    after_market = payload["components"]["after_market_scheduler"]
    assert after_market["status"] == "disabled"
    assert after_market["enabled"] is False
    assert after_market["retired"] is True
    assert {
        "last_successful_trading_day",
        "latest_completed_trading_day",
        "latest_eligible_trading_day",
        "archive_lag_trading_days",
        "current_task",
        "last_error_type",
        "last_error_at",
        "retry_count",
        "scheduler_heartbeat",
        "next_retry_at",
        "authorization_hash",
        "lock_status",
    } <= set(after_market)
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
    assert payload["components"]["live_checkpoints"]["status"] == "disabled"
    assert payload["components"]["notification_retry"]["status"] == "disabled"
    assert payload["components"]["archive"]["retired"] is True
    assert payload["components"]["after_market_scheduler"]["retired"] is True


def test_worker_coverage_requires_each_expected_queue() -> None:
    queues = [{"name": "guiyi-signals", "status": "ok"}, {"name": "guiyi-notifications", "status": "ok"}]
    workers = [{"name": "worker-1", "queues": ["guiyi-signals"]}]

    missing = _apply_worker_coverage(queues, workers)

    assert missing is True
    assert queues[0]["worker_present"] is True
    assert queues[1]["worker_present"] is False
    assert queues[1]["error_type"] == "worker_missing"


def test_archive_and_after_market_health_remain_retired_even_when_enabled_flags_passed() -> None:
    TestingSessionLocal = _session_factory()
    with TestingSessionLocal() as session:
        payload = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(),
            rq_collector=lambda connection: _rq_ok(),
            now=datetime(2026, 7, 9, 12, 0, tzinfo=UTC),
            archive_enabled=True,
            after_market_automation_enabled=True,
        )

    assert payload["components"]["archive"]["status"] == "disabled"
    assert payload["components"]["archive"]["retired"] is True
    assert payload["components"]["after_market_scheduler"]["status"] == "disabled"
    assert payload["components"]["after_market_scheduler"]["retired"] is True
    assert payload["status"] == "ok"


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
                "name": "guiyi-signals",
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
        "workers": [{"name": "worker-1", "state": "idle", "queues": ["guiyi-signals"]}],
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


def _contains_no_secret_words(payload: dict) -> bool:
    text = json.dumps(payload, ensure_ascii=False, default=str).lower()
    return not any(secret in text for secret in ("webhook", "token", "password", "cookie", "secret", "should-not-leak"))
