from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import json

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.data_center import (
    AfterMarketSchedulerCheckpoint,
    DataDownloadTask,
    LiveAggregationCheckpoint,
    LiveIngestCheckpoint,
    MarketDataFile,
    ProfileActiveBinding,
)
from app.models.signal import SignalNotification
from app.services.runtime_health import _apply_worker_coverage, _collect_scheduler_health, build_runtime_health


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
    assert payload["components"]["live_checkpoints"]["ingest_count"] == 1
    assert payload["components"]["live_checkpoints"]["aggregation_count"] == 1
    assert payload["components"]["notification_retry"]["sent_count"] == 1
    assert payload["components"]["live_checkpoints"]["status"] == "disabled"
    assert payload["components"]["notification_retry"]["status"] == "disabled"
    after_market = payload["components"]["after_market_scheduler"]
    assert after_market["status"] == "disabled"
    assert after_market["enabled"] is False
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
        "active_binding_end",
        "active_binding_ends",
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


def test_scheduler_health_exposes_redacted_signal_gate_state() -> None:
    now = datetime(2026, 7, 24, 1, 31, tzinfo=UTC)

    class SignalHeartbeatRedis(FakeRedis):
        def get(self, key: str):
            return json.dumps(
                {
                    "generated_at": now.isoformat(),
                    "status": "success",
                    "error_type": None,
                    "signal_events_enabled": True,
                    "signal_event_gate_status": "authorized",
                    "signal_event_authorization_hash": "a" * 64,
                    "signal_event_target_trading_day": "2026-07-24",
                    "signal_event_result": {
                        "created": 1,
                        "changed": 0,
                        "unchanged": 1,
                        "blocked": 0,
                        "event_ids": [21],
                    },
                    "approval_packet": "/secret/path/packet.json",
                }
            )

    health = _collect_scheduler_health(SignalHeartbeatRedis(), now, enabled=True)

    assert health["signal_events_enabled"] is True
    assert health["signal_event_gate_status"] == "authorized"
    assert health["signal_event_authorization_hash"] == "a" * 64
    assert health["signal_event_target_trading_day"] == "2026-07-24"
    assert health["signal_event_result"]["event_ids"] == [21]
    assert "approval_packet" not in health


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


def test_runtime_health_degrades_for_failed_live_checkpoint_and_due_retry() -> None:
    TestingSessionLocal = _session_factory()
    now = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)
    with TestingSessionLocal() as session:
        session.add(_ingest_checkpoint(status="failed", now=now, last_error_type="NoConfirmedBars"))
        session.add(_notification(status="retry_pending", now=now, next_retry_at=now - timedelta(minutes=1), last_error_type="http_error"))
        session.commit()

        payload = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(),
            rq_collector=lambda connection: _rq_ok(),
            now=now,
            live_runtime_enabled=True,
            notification_autosend_enabled=True,
        )

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


def test_runtime_health_degrades_when_enabled_checkpoint_is_missing_or_stale() -> None:
    TestingSessionLocal = _session_factory()
    now = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)
    with TestingSessionLocal() as session:
        missing = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(),
            rq_collector=lambda connection: _rq_ok(),
            now=now,
            live_runtime_enabled=True,
            live_freshness_seconds=60,
        )
        session.add(_ingest_checkpoint(status="success", now=now - timedelta(minutes=5)))
        session.commit()
        stale = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(),
            rq_collector=lambda connection: _rq_ok(),
            now=now,
            live_runtime_enabled=True,
            live_freshness_seconds=60,
        )

    assert missing["status"] == "degraded"
    assert missing["components"]["live_checkpoints"]["stale"] is True
    assert stale["status"] == "degraded"
    assert stale["components"]["live_checkpoints"]["stale"] is True


def test_runtime_health_does_not_mark_old_checkpoints_stale_while_market_is_closed() -> None:
    TestingSessionLocal = _session_factory()
    now = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)
    with TestingSessionLocal() as session:
        session.add(_ingest_checkpoint(status="success", now=now - timedelta(hours=2)))
        legacy_idle = _aggregation_checkpoint(status="warning", now=now - timedelta(hours=2))
        legacy_idle.period = "1w"
        legacy_idle.last_error_type = "NoClosedBuckets"
        legacy_idle.consecutive_error_count = 120
        session.add(legacy_idle)
        session.commit()

        payload = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(),
            rq_collector=lambda connection: _rq_ok(),
            now=now,
            live_runtime_enabled=True,
            live_freshness_seconds=60,
            live_polling_expected=False,
            live_market_phase="closed",
        )

    live = payload["components"]["live_checkpoints"]
    assert live["status"] == "ok"
    assert live["polling_expected"] is False
    assert live["market_phase"] == "closed"
    assert live["stale"] is False
    assert live["status_counts"] == {"success": 1, "idle": 1}
    assert live["latest_error"] is None
    assert live["recent_aggregation"][0]["status"] == "idle"
    assert live["recent_aggregation"][0]["last_error_type"] is None


def test_worker_coverage_requires_each_expected_queue() -> None:
    queues = [{"name": "guiyi-backtests", "status": "ok"}, {"name": "guiyi-signals", "status": "ok"}]
    workers = [{"name": "worker-1", "queues": ["guiyi-backtests"]}]

    missing = _apply_worker_coverage(queues, workers)

    assert missing is True
    assert queues[0]["worker_present"] is True
    assert queues[1]["worker_present"] is False
    assert queues[1]["error_type"] == "worker_missing"


def test_enabled_archive_failure_is_visible_in_runtime_health() -> None:
    TestingSessionLocal = _session_factory()
    now = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)
    with TestingSessionLocal() as session:
        session.add(
            DataDownloadTask(
                task_no="archive:jm:JM2609:2026-07-08",
                provider="rqdata",
                data_type="after_market_archive",
                instrument_symbol="jm",
                contract_code="JM2609",
                period="1m_bundle",
                start_time=now - timedelta(days=1),
                end_time=now - timedelta(days=1),
                status="failed",
                progress=0,
                result={"quality_gate": "failed", "error_type": "RowCountMismatch"},
                finished_at=now - timedelta(hours=1),
            )
        )
        session.commit()
        payload = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(),
            rq_collector=lambda connection: _rq_ok(),
            now=now,
            archive_enabled=True,
        )

    archive = payload["components"]["archive"]
    assert payload["status"] == "degraded"
    assert archive["status"] == "degraded"
    assert archive["latest_task_status"] == "failed"
    assert archive["latest_error_type"] == "RowCountMismatch"


def test_after_market_scheduler_health_has_independent_watermark_retry_and_heartbeat_fields() -> None:
    from app.services.runtime_health import _collect_after_market_scheduler_health

    TestingSessionLocal = _session_factory()
    now = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)
    with TestingSessionLocal() as session:
        session.add(
            AfterMarketSchedulerCheckpoint(
                product="jm",
                exchange_code="DCE",
                status="retry_wait",
                authorization_hash="a" * 64,
                last_successful_trading_day=date(2026, 7, 21),
                current_trading_day=date(2026, 7, 22),
                retry_count=2,
                last_error_type="ConnectionError",
                last_error_at=now - timedelta(minutes=5),
                next_retry_at=now + timedelta(minutes=10),
                last_result={},
            )
        )
        session.commit()
        health = _collect_after_market_scheduler_health(
            session,
            connection=HeartbeatRedis(now),
            now=now,
            enabled=True,
            clock=HealthClock(),
        )

    assert health["last_successful_trading_day"] == "2026-07-21"
    assert health["latest_completed_trading_day"] == "2026-07-22"
    assert health["latest_eligible_trading_day"] == "2026-07-22"
    assert health["archive_lag_trading_days"] == 1
    assert health["current_task"] == "archive:jm:2026-07-22"
    assert health["retry_count"] == 2
    assert health["scheduler_heartbeat"]["status"] == "retry_wait"
    assert health["scheduler_heartbeat"]["pid"] == 4321
    assert health["lock_status"] == "held"
    assert "active_binding_end" in health


def test_after_market_active_binding_end_uses_latest_passed_file_per_required_identity() -> None:
    from app.services.runtime_health import _after_market_active_binding_end

    TestingSessionLocal = _session_factory()
    latest_end = datetime(2026, 7, 21, 15, 0, tzinfo=UTC)
    required = (
        ("intraday_research_v1", "1m"),
        ("intraday_research_v1", "5m"),
        ("intraday_research_v1", "15m"),
        ("live_observation_v1", "1m"),
        ("live_observation_v1", "5m"),
        ("live_observation_v1", "15m"),
        ("long_horizon_daily_v1", "1d"),
    )
    with TestingSessionLocal() as session:
        for index, (profile_id, period) in enumerate(required):
            market_file = MarketDataFile(
                provider="rqdata",
                data_type="bars",
                instrument_symbol="jm",
                contract_code="JM2609",
                period=period,
                start_time=datetime(2026, 6, 12, tzinfo=UTC),
                end_time=latest_end,
                file_path=f"/tmp/latest-{index}.parquet",
                row_count=1,
                checksum=f"{index + 1:064x}",
                data_version=f"latest-{index}",
                data_role="primary",
                quality_status="passed",
            )
            session.add(market_file)
            session.flush()
            session.add(
                ProfileActiveBinding(
                    profile_id=profile_id,
                    instrument_symbol="jm",
                    contract_code="JM2609",
                    period=period,
                    data_version=market_file.data_version,
                    market_data_file_id=market_file.id,
                    binding_status="active",
                )
            )

        historical_file = MarketDataFile(
            provider="rqdata",
            data_type="bars",
            instrument_symbol="jm",
            contract_code="JM2005",
            period="1d",
            start_time=datetime(2020, 1, 2, tzinfo=UTC),
            end_time=datetime(2020, 4, 3, tzinfo=UTC),
            file_path="/tmp/historical.parquet",
            row_count=1,
            checksum="f" * 64,
            data_version="historical",
            data_role="primary",
            quality_status="passed",
        )
        session.add(historical_file)
        session.flush()
        session.add(
            ProfileActiveBinding(
                profile_id="long_horizon_daily_v1",
                instrument_symbol="jm",
                contract_code="JM2005",
                period="1d",
                data_version=historical_file.data_version,
                market_data_file_id=historical_file.id,
                binding_status="active",
            )
        )
        session.commit()

        active_end, details = _after_market_active_binding_end(session)

    assert active_end == "2026-07-21"
    assert len(details) == 7
    assert all(row["contract"] == "JM2609" for row in details)


def test_after_market_scheduler_health_degrades_on_stale_heartbeat_even_when_last_state_was_success() -> None:
    from app.services.runtime_health import _collect_after_market_scheduler_health

    TestingSessionLocal = _session_factory()
    now = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)
    with TestingSessionLocal() as session:
        session.add(
            AfterMarketSchedulerCheckpoint(
                product="jm",
                exchange_code="DCE",
                status="success",
                authorization_hash="a" * 64,
                last_successful_trading_day=date(2026, 7, 22),
                retry_count=0,
                last_result={},
            )
        )
        session.commit()
        health = _collect_after_market_scheduler_health(
            session,
            connection=HeartbeatRedis(now - timedelta(minutes=4), status="success"),
            now=now,
            enabled=True,
            clock=HealthClock(),
        )

    assert health["status"] == "degraded"
    assert health["scheduler_heartbeat"]["health_status"] == "degraded"


class FakeRedis:
    def __init__(self, exc: Exception | None = None) -> None:
        self.exc = exc

    def ping(self) -> bool:
        if self.exc is not None:
            raise self.exc
        return True


class HeartbeatRedis(FakeRedis):
    def __init__(
        self,
        now: datetime,
        *,
        status: str = "retry_wait",
        pid: int = 4321,
    ) -> None:
        super().__init__()
        self.now = now
        self.status = status
        self.pid = pid

    def get(self, key: str):
        return json.dumps(
            {
                "generated_at": self.now.isoformat(),
                "status": self.status,
                "error_type": None,
                "lock_status": "held",
                "pid": self.pid,
            }
        )


class HealthClock:
    def latest_completed_trading_day(self, *, product: str, exchange: str, now: datetime):
        return date(2026, 7, 22)

    def trading_days_between(self, start: date, end: date, *, exchange: str):
        return [date(2026, 7, 22)], True

    def final_close_at(self, trading_day: date, *, product: str, exchange: str):
        return datetime(2026, 7, 22, 15, 0)


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
