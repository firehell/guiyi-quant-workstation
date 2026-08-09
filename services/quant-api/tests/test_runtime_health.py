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
from app.services.runtime_health import _apply_worker_coverage, build_runtime_health


def test_runtime_health_endpoint_exposes_market_runtime_components(monkeypatch, tmp_path) -> None:
    TestingSessionLocal = _session_factory()

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    monkeypatch.setattr("app.services.runtime_health.get_redis_connection", lambda: FakeRedis())
    monkeypatch.setattr("app.services.runtime_health._collect_rq_health", lambda connection, **kwargs: _rq_ok())
    monkeypatch.setattr("app.services.runtime_health.DEFAULT_AFTER_MARKET_STATUS_PATH", tmp_path / "missing.json")
    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).get("/api/runtime/health")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["readonly"] is True
    assert payload["would_start_services"] is False
    assert payload["would_enqueue_jobs"] is False
    assert payload["would_send_notifications"] is False
    assert set(payload["components"]) == {"db", "redis", "rq", "live_market", "after_market"}
    assert payload["components"]["live_market"] == {
        "status": "disabled",
        "configured_enabled": False,
        "operational_count": 0,
        "subscribed_count": 0,
        "last_heartbeat_at": None,
        "last_bar_at": None,
        "phase_counts": {},
        "error_type": None,
        "error_message": None,
    }
    assert payload["components"]["after_market"] == {
        "status": "disabled",
        "last_run": None,
        "last_successful_trading_day": None,
        "last_failure": None,
        "error_type": None,
        "error_message": None,
    }


def test_runtime_health_marks_fresh_live_heartbeat_ok() -> None:
    now = datetime(2026, 8, 10, 1, 2, tzinfo=UTC)
    redis = FakeRedis(
        values={
            "live:heartbeat": json.dumps(
                {
                    "generated_at": now.isoformat(),
                    "operational_count": 4,
                    "subscribed_count": 4,
                    "last_bar_at": (now - timedelta(minutes=1)).isoformat(),
                    "phase_counts": {"trading": 4},
                    "available": True,
                }
            )
        }
    )
    TestingSessionLocal = _session_factory()
    with TestingSessionLocal() as session:
        payload = build_runtime_health(
            session,
            redis_factory=lambda: redis,
            rq_collector=lambda connection: _rq_ok(),
            now=now,
            live_runtime_enabled=True,
            after_market_status_path=None,
        )

    live = payload["components"]["live_market"]
    assert payload["status"] == "ok"
    assert live["status"] == "ok"
    assert live["configured_enabled"] is True
    assert live["operational_count"] == 4
    assert live["subscribed_count"] == 4
    assert live["last_heartbeat_at"] == now.isoformat()
    assert live["last_bar_at"] == (now - timedelta(minutes=1)).isoformat()
    assert live["phase_counts"] == {"trading": 4}


def test_runtime_health_missing_or_stale_live_heartbeat_only_degrades_when_enabled() -> None:
    now = datetime(2026, 8, 10, 1, 10, tzinfo=UTC)
    TestingSessionLocal = _session_factory()
    with TestingSessionLocal() as session:
        disabled = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(),
            rq_collector=lambda connection: _rq_ok(),
            now=now,
            live_runtime_enabled=False,
            after_market_status_path=None,
        )
        stale = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(
                values={
                    "live:heartbeat": json.dumps(
                        {
                            "generated_at": (now - timedelta(minutes=6)).isoformat(),
                            "operational_count": 4,
                            "subscribed_count": 4,
                            "last_bar_at": None,
                            "phase_counts": {"trading": 4},
                            "available": True,
                        }
                    )
                }
            ),
            rq_collector=lambda connection: _rq_ok(),
            now=now,
            live_runtime_enabled=True,
            live_freshness_seconds=300,
            after_market_status_path=None,
        )

    assert disabled["status"] == "ok"
    assert disabled["components"]["db"]["status"] == "ok"
    assert disabled["components"]["live_market"]["status"] == "disabled"
    assert stale["status"] == "degraded"
    assert stale["components"]["db"]["status"] == "ok"
    assert stale["components"]["live_market"]["status"] == "degraded"
    assert stale["components"]["live_market"]["error_type"] == "live_heartbeat_stale"


def test_runtime_health_surfaces_only_public_after_market_failure(tmp_path) -> None:
    status_path = tmp_path / "after-market-status.json"
    status_path.write_text(
        json.dumps(
            {
                "last_run": {
                    "trading_day": "2026-08-10",
                    "status": "failed",
                    "attempts": 2,
                    "started_at": "2026-08-10T17:00:00+08:00",
                    "finished_at": "2026-08-10T18:00:00+08:00",
                    "products": ["j", "jm", "ap", "ag"],
                    "error_code": "UPDATE_FAILED",
                    "provider_token": "must-not-leak",
                },
                "last_successful_trading_day": "2026-08-09",
                "last_failure": {"trading_day": "2026-08-10", "error_code": "UPDATE_FAILED"},
            }
        ),
        encoding="utf-8",
    )
    TestingSessionLocal = _session_factory()
    with TestingSessionLocal() as session:
        payload = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(),
            rq_collector=lambda connection: _rq_ok(),
            after_market_status_path=status_path,
        )

    after_market = payload["components"]["after_market"]
    assert payload["status"] == "failed"
    assert after_market["status"] == "failed"
    assert after_market["last_run"] == {
        "trading_day": "2026-08-10",
        "status": "failed",
        "attempts": 2,
        "started_at": "2026-08-10T17:00:00+08:00",
        "finished_at": "2026-08-10T18:00:00+08:00",
        "products": ["j", "jm", "ap", "ag"],
        "error_code": "UPDATE_FAILED",
    }
    assert after_market["last_successful_trading_day"] == "2026-08-09"
    assert after_market["last_failure"] == {
        "trading_day": "2026-08-10",
        "error_code": "UPDATE_FAILED",
    }
    assert _contains_no_secret_words(payload)


def test_runtime_health_returns_failed_payload_when_redis_unavailable() -> None:
    TestingSessionLocal = _session_factory()
    with TestingSessionLocal() as session:
        payload = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(exc=ConnectionError("redis password should-not-leak")),
            rq_collector=lambda connection: _rq_ok(),
            now=datetime(2026, 7, 9, 12, 0, tzinfo=UTC),
            after_market_status_path=None,
        )

    assert payload["status"] == "failed"
    assert payload["components"]["db"]["status"] == "ok"
    assert payload["components"]["redis"]["status"] == "failed"
    assert payload["components"]["redis"]["error_type"] == "ConnectionError"
    assert payload["components"]["redis"]["error_message"] is None
    assert payload["components"]["rq"]["status"] == "failed"
    assert payload["components"]["rq"]["error_type"] == "redis_unavailable"
    assert _contains_no_secret_words(payload)


def test_worker_coverage_requires_each_expected_queue() -> None:
    queues = [{"name": "guiyi-signals", "status": "ok"}, {"name": "guiyi-notifications", "status": "ok"}]
    workers = [{"name": "worker-1", "queues": ["guiyi-signals"]}]

    missing = _apply_worker_coverage(queues, workers)

    assert missing is True
    assert queues[0]["worker_present"] is True
    assert queues[1]["worker_present"] is False
    assert queues[1]["error_type"] == "worker_missing"


class FakeRedis:
    def __init__(self, exc: Exception | None = None, values: dict[str, str] | None = None) -> None:
        self.exc = exc
        self.values = values or {}

    def ping(self) -> bool:
        if self.exc is not None:
            raise self.exc
        return True

    def get(self, key: str) -> str | None:
        return self.values.get(key)


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
        "queues": [],
        "worker_count": 0,
        "workers": [],
        "error_type": None,
        "error_message": None,
    }


def _contains_no_secret_words(payload: dict) -> bool:
    text = json.dumps(payload, ensure_ascii=False, default=str).lower()
    return not any(secret in text for secret in ("webhook", "token", "password", "cookie", "secret", "must-not-leak"))
