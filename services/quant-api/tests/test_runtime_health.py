from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import json

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Exchange, Instrument, TradingCalendar
from app.services.runtime_health import build_runtime_health


def test_runtime_health_endpoint_exposes_market_runtime_components(
    monkeypatch, tmp_path
) -> None:
    TestingSessionLocal = _session_factory()

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    monkeypatch.setattr(
        "app.services.runtime_health.get_redis_connection", lambda: FakeRedis()
    )
    monkeypatch.setattr(
        "app.services.runtime_health._market_runtime_activation_enabled", lambda: False
    )
    monkeypatch.setattr(
        "app.services.runtime_health._alert_runtime_activation_enabled", lambda: False
    )
    monkeypatch.setattr(
        "app.services.runtime_health.notification_transport_status_from_env",
        lambda: {
            "transport": "pushplus",
            "configured": False,
            "audience_count": 2,
            "would_send": False,
        },
    )
    monkeypatch.setattr(
        "app.api.runtime.build_runtime_health",
        lambda session: build_runtime_health(session, after_market_status_path=None),
    )
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
    assert set(payload["components"]) == {
        "db",
        "redis",
        "live_market",
        "after_market",
        "alert",
    }
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
        "configured_enabled": False,
        "run_state": "disabled",
        "expected_trading_day": None,
        "current_run": None,
        "last_run": None,
        "last_successful_trading_day": None,
        "last_failure": None,
        "error_type": None,
        "error_message": None,
    }
    assert payload["components"]["alert"] == {
        "status": "disabled",
        "configured_enabled": False,
        "notification": {
            "transport": "pushplus",
            "configured": False,
            "audience_count": 2,
            "would_send": False,
        },
        "last_heartbeat_at": None,
        "enabled_rule_count": 0,
        "scope_product_count": 0,
        "processing_state": "unobserved",
        "notification_state": "unobserved",
        "last_processed_bar_at": None,
        "last_processing_success_at": None,
        "last_processing_failure_at": None,
        "processing_error_type": None,
        "last_event_at": None,
        "last_transport_attempt_at": None,
        "last_provider_accepted_at": None,
        "last_notification_failure_at": None,
        "notification_acknowledged_at": None,
        "notification_error_type": None,
        "consecutive_notification_failures": 0,
        "strategy_state": "warming",
        "strategy_started_at": None,
        "strategy_ready_at": None,
        "strategy_product_count": 0,
        "strategy_ready_product_count": 0,
        "strategy_unavailable_product_count": 0,
        "strategy_unavailable_symbols": [],
        "last_strategy_action_at": None,
        "last_strategy_restore_at": None,
        "error_type": None,
    }


def test_alert_health_activation_and_transport_fail_closed(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr("app.services.runtime_health.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        "app.services.runtime_health.notification_transport_status_from_env",
        lambda: {
            "transport": "pushplus",
            "configured": False,
            "audience_count": 2,
            "would_send": False,
        },
    )
    TestingSessionLocal = _session_factory()

    with TestingSessionLocal() as session:
        disabled = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(),
            live_runtime_enabled=False,
            after_market_status_path=None,
        )
        marker = tmp_path / ".run" / "alert-runtime-enabled"
        marker.parent.mkdir()
        marker.write_text("enabled\n", encoding="utf-8")
        missing_transport = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(),
            live_runtime_enabled=False,
            after_market_status_path=None,
        )

    assert disabled["components"]["alert"]["status"] == "disabled"
    assert disabled["components"]["alert"]["configured_enabled"] is False
    assert missing_transport["components"]["alert"]["status"] == "degraded"
    assert (
        missing_transport["components"]["alert"]["error_type"]
        == "alert_notification_transport_missing"
    )


def test_alert_health_missing_stale_and_fresh_heartbeat(monkeypatch, tmp_path) -> None:
    now = datetime(2026, 8, 13, 2, 45, tzinfo=UTC)
    monkeypatch.setattr("app.services.runtime_health.PROJECT_ROOT", tmp_path)
    marker = tmp_path / ".run" / "alert-runtime-enabled"
    marker.parent.mkdir()
    marker.write_text("enabled\n", encoding="utf-8")
    TestingSessionLocal = _session_factory()

    with TestingSessionLocal() as session:
        missing = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(),
            now=now,
            live_runtime_enabled=False,
            notification_transport_configured=True,
            after_market_status_path=None,
        )
        stale = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(
                values={
                    "alert:heartbeat": json.dumps(
                        {
                            "generated_at": (now - timedelta(seconds=31)).isoformat(),
                            "available": True,
                            "enabled_rule_count": 1,
                            "scope_product_count": 2,
                        }
                    )
                }
            ),
            now=now,
            live_runtime_enabled=False,
            notification_transport_configured=True,
            after_market_status_path=None,
        )
        fresh = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(
                values={
                    "alert:heartbeat": json.dumps(
                        {
                            "generated_at": now.isoformat(),
                            "available": True,
                            "enabled_rule_count": 1,
                            "scope_product_count": 2,
                        }
                    )
                }
            ),
            now=now,
            live_runtime_enabled=False,
            notification_transport_configured=True,
            after_market_status_path=None,
        )

    assert missing["components"]["alert"]["error_type"] == "alert_heartbeat_missing"
    assert stale["components"]["alert"]["error_type"] == "alert_heartbeat_stale"
    assert fresh["components"]["alert"] == {
        "status": "ok",
        "configured_enabled": True,
        "notification": {
            "transport": "pushplus",
            "configured": True,
            "audience_count": 2,
            "would_send": False,
        },
        "last_heartbeat_at": now.isoformat(),
        "enabled_rule_count": 1,
        "scope_product_count": 2,
        "processing_state": "unobserved",
        "notification_state": "unobserved",
        "last_processed_bar_at": None,
        "last_processing_success_at": None,
        "last_processing_failure_at": None,
        "processing_error_type": None,
        "last_event_at": None,
        "last_transport_attempt_at": None,
        "last_provider_accepted_at": None,
        "last_notification_failure_at": None,
        "notification_acknowledged_at": None,
        "notification_error_type": None,
        "consecutive_notification_failures": 0,
        "strategy_state": "warming",
        "strategy_started_at": None,
        "strategy_ready_at": None,
        "strategy_product_count": 0,
        "strategy_ready_product_count": 0,
        "strategy_unavailable_product_count": 0,
        "strategy_unavailable_symbols": [],
        "last_strategy_action_at": None,
        "last_strategy_restore_at": None,
        "error_type": None,
    }
    rendered = json.dumps(fresh, ensure_ascii=False)
    assert "fixture/secrets" not in rendered


@pytest.mark.parametrize(
    ("heartbeat", "expected_error_type"),
    (
        (None, "alert_heartbeat_missing"),
        (
            {
                "generated_at": "2026-08-14T02:44:29+00:00",
                "available": True,
                "enabled_rule_count": 2,
                "scope_product_count": 1,
            },
            "alert_heartbeat_stale",
        ),
    ),
)
def test_alert_health_preserves_failed_persistent_observation_when_heartbeat_is_unhealthy(
    heartbeat: dict[str, object] | None,
    expected_error_type: str,
) -> None:
    """A short-lived heartbeat failure must not erase the persistent failure record."""
    now = datetime(2026, 8, 14, 2, 45, tzinfo=UTC)
    runtime_status = {
        "schema_version": 1,
        "last_processed_bar_at": "2026-08-14T02:42:58+00:00",
        "last_processing_success_at": "2026-08-14T02:42:00+00:00",
        "last_processing_failure_at": "2026-08-14T02:43:00+00:00",
        "processing_error_type": "processing_failed",
        "last_event_at": "2026-08-14T02:42:00+00:00",
        "last_transport_attempt_at": "2026-08-14T02:43:00+00:00",
        "last_provider_accepted_at": "2026-08-14T02:42:00+00:00",
        "last_notification_failure_at": "2026-08-14T02:43:00+00:00",
        "notification_error_type": "notification_transport_failed",
        "consecutive_notification_failures": 2,
    }
    values: dict[str, object] = {
        "alert:runtime-status": json.dumps(runtime_status),
    }
    if heartbeat is not None:
        values["alert:heartbeat"] = json.dumps(heartbeat)
    TestingSessionLocal = _session_factory()

    with TestingSessionLocal() as session:
        payload = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(values=values),
            now=now,
            live_runtime_enabled=False,
            alert_runtime_enabled=True,
            notification_transport_configured=True,
            after_market_status_path=None,
        )

    alert = payload["components"]["alert"]
    assert alert["status"] == "degraded"
    assert alert["error_type"] == expected_error_type
    assert alert["processing_state"] == "failed"
    assert alert["notification_state"] == "failed"
    assert alert["last_processing_failure_at"] == "2026-08-14T02:43:00+00:00"
    assert alert["processing_error_type"] == "processing_failed"
    assert alert["last_notification_failure_at"] == "2026-08-14T02:43:00+00:00"
    assert alert["notification_error_type"] == "notification_transport_failed"
    assert alert["consecutive_notification_failures"] == 2


def test_alert_health_accepts_v2_heartbeat_counts() -> None:
    """V2 scope count is the unique enabled-rule product union, not rule-product pairs."""
    now = datetime(2026, 8, 14, 2, 45, tzinfo=UTC)
    heartbeat = {
        "generated_at": now.isoformat(),
        "available": True,
        "enabled_rule_count": 2,
        "scope_product_count": 1,
    }
    TestingSessionLocal = _session_factory()

    with TestingSessionLocal() as session:
        health = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(
                values={"alert:heartbeat": json.dumps(heartbeat)}
            ),
            now=now,
            live_runtime_enabled=False,
            alert_runtime_enabled=True,
            notification_transport_configured=True,
            after_market_status_path=None,
        )

    alert = health["components"]["alert"]
    assert alert["status"] == "ok"
    assert alert["enabled_rule_count"] == 2
    assert alert["scope_product_count"] == 1


def test_alert_health_exposes_bounded_strategy_v3_observation() -> None:
    now = datetime(2026, 8, 14, 2, 45, tzinfo=UTC)
    heartbeat = {
        "generated_at": now.isoformat(),
        "available": True,
        "enabled_rule_count": 2,
        "scope_product_count": 1,
    }
    runtime_status = {
        "schema_version": 3,
        "last_processed_bar_at": None,
        "last_processing_success_at": None,
        "last_processing_failure_at": None,
        "processing_error_type": None,
        "last_event_at": None,
        "last_transport_attempt_at": None,
        "last_provider_accepted_at": None,
        "last_notification_failure_at": None,
        "notification_acknowledged_at": None,
        "notification_error_type": None,
        "consecutive_notification_failures": 0,
        "strategy_state": "degraded",
        "strategy_started_at": (now - timedelta(seconds=4)).isoformat(),
        "strategy_ready_at": (now - timedelta(seconds=1)).isoformat(),
        "strategy_product_count": 2,
        "strategy_ready_product_count": 1,
        "strategy_unavailable_product_count": 1,
        "strategy_unavailable_symbols": ["jm"],
        "last_strategy_action_at": None,
        "last_strategy_restore_at": (now - timedelta(seconds=1)).isoformat(),
    }
    TestingSessionLocal = _session_factory()

    with TestingSessionLocal() as session:
        health = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(
                values={
                    "alert:heartbeat": json.dumps(heartbeat),
                    "alert:runtime-status": json.dumps(runtime_status),
                }
            ),
            now=now,
            live_runtime_enabled=False,
            alert_runtime_enabled=True,
            notification_transport_configured=True,
            after_market_status_path=None,
        )

    alert = health["components"]["alert"]
    assert alert["status"] == "degraded"
    assert alert["strategy_state"] == "degraded"
    assert alert["strategy_product_count"] == 2
    assert alert["strategy_ready_product_count"] == 1
    assert alert["strategy_unavailable_product_count"] == 1
    assert alert["strategy_unavailable_symbols"] == ["jm"]


def test_alert_health_derives_latest_processing_and_notification_outcomes() -> None:
    now = datetime(2026, 8, 14, 2, 45, tzinfo=UTC)
    heartbeat = json.dumps(
        {
            "generated_at": now.isoformat(),
            "available": True,
            "enabled_rule_count": 2,
            "scope_product_count": 1,
        }
    )
    healthy_status = json.dumps(
        {
            "schema_version": 1,
            "last_processed_bar_at": (now - timedelta(seconds=2)).isoformat(),
            "last_processing_success_at": now.isoformat(),
            "last_processing_failure_at": (now - timedelta(minutes=1)).isoformat(),
            "processing_error_type": None,
            "last_event_at": now.isoformat(),
            "last_transport_attempt_at": now.isoformat(),
            "last_provider_accepted_at": now.isoformat(),
            "last_notification_failure_at": None,
            "notification_error_type": None,
            "consecutive_notification_failures": 0,
        }
    )
    failed_status = json.dumps(
        {
            "schema_version": 1,
            "last_processed_bar_at": (now - timedelta(seconds=2)).isoformat(),
            "last_processing_success_at": (now - timedelta(minutes=2)).isoformat(),
            "last_processing_failure_at": (now - timedelta(minutes=1)).isoformat(),
            "processing_error_type": "processing_failed",
            "last_event_at": (now - timedelta(minutes=2)).isoformat(),
            "last_transport_attempt_at": (now - timedelta(minutes=1)).isoformat(),
            "last_provider_accepted_at": (now - timedelta(minutes=2)).isoformat(),
            "last_notification_failure_at": (now - timedelta(minutes=1)).isoformat(),
            "notification_error_type": "notification_transport_failed",
            "consecutive_notification_failures": 2,
        }
    )
    TestingSessionLocal = _session_factory()

    with TestingSessionLocal() as session:
        healthy = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(
                values={
                    "alert:heartbeat": heartbeat,
                    "alert:runtime-status": healthy_status,
                }
            ),
            now=now,
            live_runtime_enabled=False,
            alert_runtime_enabled=True,
            notification_transport_configured=True,
            after_market_status_path=None,
        )
        failed = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(
                values={
                    "alert:heartbeat": heartbeat,
                    "alert:runtime-status": failed_status,
                }
            ),
            now=now,
            live_runtime_enabled=False,
            alert_runtime_enabled=True,
            notification_transport_configured=True,
            after_market_status_path=None,
        )

    healthy_alert = healthy["components"]["alert"]
    assert healthy_alert["status"] == "ok"
    assert healthy_alert["processing_state"] == "ok"
    assert healthy_alert["notification_state"] == "provider_accepted"
    failed_alert = failed["components"]["alert"]
    assert failed_alert["status"] == "degraded"
    assert failed_alert["processing_state"] == "failed"
    assert failed_alert["notification_state"] == "failed"
    assert failed_alert["processing_error_type"] == "processing_failed"
    assert failed_alert["notification_error_type"] == "notification_transport_failed"
    assert failed_alert["consecutive_notification_failures"] == 2
    assert "provider_reference" not in json.dumps(failed_alert)


def test_alert_health_acknowledges_failure_without_erasing_failure_facts() -> None:
    now = datetime(2026, 8, 14, 2, 45, tzinfo=UTC)
    failure_at = now - timedelta(minutes=5)
    acknowledged_at = now - timedelta(minutes=1)
    heartbeat = json.dumps(
        {
            "generated_at": now.isoformat(),
            "available": True,
            "enabled_rule_count": 2,
            "scope_product_count": 1,
        }
    )
    runtime_status = json.dumps(
        {
            "schema_version": 2,
            "last_processed_bar_at": now.isoformat(),
            "last_processing_success_at": now.isoformat(),
            "last_processing_failure_at": None,
            "processing_error_type": None,
            "last_event_at": failure_at.isoformat(),
            "last_transport_attempt_at": failure_at.isoformat(),
            "last_provider_accepted_at": failure_at.isoformat(),
            "last_notification_failure_at": failure_at.isoformat(),
            "notification_acknowledged_at": acknowledged_at.isoformat(),
            "notification_error_type": "notification_transport_failed",
            "consecutive_notification_failures": 1,
        }
    )
    TestingSessionLocal = _session_factory()

    with TestingSessionLocal() as session:
        health = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(
                values={
                    "alert:heartbeat": heartbeat,
                    "alert:runtime-status": runtime_status,
                }
            ),
            now=now,
            live_runtime_enabled=False,
            alert_runtime_enabled=True,
            notification_transport_configured=True,
            after_market_status_path=None,
        )

    alert = health["components"]["alert"]
    assert health["status"] == "ok"
    assert alert["status"] == "ok"
    assert alert["notification_state"] == "acknowledged"
    assert alert["last_notification_failure_at"] == failure_at.isoformat()
    assert alert["notification_acknowledged_at"] == acknowledged_at.isoformat()
    assert alert["notification_error_type"] == "notification_transport_failed"
    assert alert["consecutive_notification_failures"] == 1


def test_alert_health_new_failure_after_acknowledgement_is_failed_again() -> None:
    now = datetime(2026, 8, 14, 2, 45, tzinfo=UTC)
    latest_failure_at = now - timedelta(minutes=1)
    prior_acknowledgement_at = now - timedelta(minutes=2)
    values = {
        "alert:heartbeat": json.dumps(
            {
                "generated_at": now.isoformat(),
                "available": True,
                "enabled_rule_count": 2,
                "scope_product_count": 1,
            }
        ),
        "alert:runtime-status": json.dumps(
            {
                "schema_version": 2,
                "last_processed_bar_at": now.isoformat(),
                "last_processing_success_at": now.isoformat(),
                "last_processing_failure_at": None,
                "processing_error_type": None,
                "last_event_at": latest_failure_at.isoformat(),
                "last_transport_attempt_at": latest_failure_at.isoformat(),
                "last_provider_accepted_at": (now - timedelta(minutes=3)).isoformat(),
                "last_notification_failure_at": latest_failure_at.isoformat(),
                "notification_acknowledged_at": (prior_acknowledgement_at.isoformat()),
                "notification_error_type": "notification_transport_failed",
                "consecutive_notification_failures": 1,
            }
        ),
    }
    TestingSessionLocal = _session_factory()

    with TestingSessionLocal() as session:
        health = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(values=values),
            now=now,
            live_runtime_enabled=False,
            alert_runtime_enabled=True,
            notification_transport_configured=True,
            after_market_status_path=None,
        )

    alert = health["components"]["alert"]
    assert alert["status"] == "degraded"
    assert alert["notification_state"] == "failed"
    assert alert["last_notification_failure_at"] == latest_failure_at.isoformat()
    assert alert["notification_acknowledged_at"] == (
        prior_acknowledgement_at.isoformat()
    )


@pytest.mark.parametrize(
    "invalid_status",
    ("not-json", json.dumps([]), 17),
)
def test_alert_health_distinguishes_missing_from_invalid_runtime_status(
    invalid_status: object,
) -> None:
    now = datetime(2026, 8, 14, 2, 45, tzinfo=UTC)
    heartbeat = json.dumps(
        {
            "generated_at": now.isoformat(),
            "available": True,
            "enabled_rule_count": 2,
            "scope_product_count": 1,
        }
    )
    TestingSessionLocal = _session_factory()

    with TestingSessionLocal() as session:
        missing = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(values={"alert:heartbeat": heartbeat}),
            now=now,
            live_runtime_enabled=False,
            alert_runtime_enabled=True,
            notification_transport_configured=True,
            after_market_status_path=None,
        )
        invalid = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(
                values={
                    "alert:heartbeat": heartbeat,
                    "alert:runtime-status": invalid_status,
                }
            ),
            now=now,
            live_runtime_enabled=False,
            alert_runtime_enabled=True,
            notification_transport_configured=True,
            after_market_status_path=None,
        )

    missing_alert = missing["components"]["alert"]
    assert missing_alert["status"] == "ok"
    assert missing_alert["processing_state"] == "unobserved"
    assert missing_alert["notification_state"] == "unobserved"
    invalid_alert = invalid["components"]["alert"]
    assert invalid_alert["status"] == "degraded"
    assert invalid_alert["error_type"] == "alert_runtime_status_invalid"
    assert invalid_alert["processing_state"] == "unobserved"
    assert invalid_alert["notification_state"] == "unobserved"


@pytest.mark.parametrize(
    "error_field",
    ("processing_error_type", "notification_error_type"),
)
def test_alert_health_rejects_nonpublic_error_token_without_exposing_it(
    error_field: str,
) -> None:
    now = datetime(2026, 8, 14, 2, 45, tzinfo=UTC)
    heartbeat = json.dumps(
        {
            "generated_at": now.isoformat(),
            "available": True,
            "enabled_rule_count": 2,
            "scope_product_count": 1,
        }
    )
    runtime_status: dict[str, object] = {
        "schema_version": 1,
        "last_processed_bar_at": now.isoformat(),
        "last_processing_success_at": None,
        "last_processing_failure_at": now.isoformat(),
        "processing_error_type": "processing_failed",
        "last_event_at": now.isoformat(),
        "last_transport_attempt_at": now.isoformat(),
        "last_provider_accepted_at": None,
        "last_notification_failure_at": now.isoformat(),
        "notification_error_type": "notification_transport_failed",
        "consecutive_notification_failures": 1,
    }
    runtime_status[error_field] = "must_not_leak"
    TestingSessionLocal = _session_factory()

    with TestingSessionLocal() as session:
        health = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(
                values={
                    "alert:heartbeat": heartbeat,
                    "alert:runtime-status": json.dumps(runtime_status),
                }
            ),
            now=now,
            live_runtime_enabled=False,
            alert_runtime_enabled=True,
            notification_transport_configured=True,
            after_market_status_path=None,
        )

    alert = health["components"]["alert"]
    assert alert["status"] == "degraded"
    assert alert["error_type"] == "alert_runtime_status_invalid"
    assert "must_not_leak" not in json.dumps(alert)


def test_alert_health_structural_transport_is_ready_from_process_environment(
    monkeypatch,
) -> None:
    now = datetime(2026, 8, 14, 2, 45, tzinfo=UTC)
    calls: list[str] = []
    monkeypatch.setattr(
        "app.services.runtime_health.notification_transport_status_from_env",
        lambda: (
            calls.append("structural-check")
            or {
                "transport": "pushplus",
                "configured": True,
                "audience_count": 2,
                "would_send": False,
            }
        ),
    )
    TestingSessionLocal = _session_factory()

    with TestingSessionLocal() as session:
        payload = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(
                values={
                    "alert:heartbeat": json.dumps(
                        {
                            "generated_at": now.isoformat(),
                            "available": True,
                            "enabled_rule_count": 2,
                            "scope_product_count": 1,
                        }
                    )
                }
            ),
            now=now,
            live_runtime_enabled=False,
            alert_runtime_enabled=True,
            after_market_status_path=None,
        )

    assert calls == ["structural-check"]
    assert payload["components"]["alert"]["status"] == "ok"
    assert payload["components"]["alert"]["notification"] == {
        "transport": "pushplus",
        "configured": True,
        "audience_count": 2,
        "would_send": False,
    }


def test_alert_health_rejects_invalid_transport_config_path(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr("app.services.runtime_health.PROJECT_ROOT", tmp_path)
    marker = tmp_path / ".run" / "alert-runtime-enabled"
    marker.parent.mkdir()
    marker.write_text("enabled\n", encoding="utf-8")
    monkeypatch.setattr(
        "app.services.runtime_health.notification_transport_status_from_env",
        lambda: {
            "transport": "pushplus",
            "configured": False,
            "audience_count": 2,
            "would_send": False,
        },
    )
    monkeypatch.setenv(
        "GUIYI_ALERT_NOTIFICATION_CONFIG_PATH",
        "relative/notification.json",
    )
    TestingSessionLocal = _session_factory()

    with TestingSessionLocal() as session:
        payload = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(),
            live_runtime_enabled=False,
            after_market_status_path=None,
        )

    alert = payload["components"]["alert"]
    assert alert["status"] == "degraded"
    assert alert["notification"]["configured"] is False
    assert alert["error_type"] == "alert_notification_transport_invalid"


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
            now=now,
            live_runtime_enabled=True,
            alert_runtime_enabled=False,
            notification_transport_configured=False,
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


def test_runtime_health_missing_or_stale_live_heartbeat_only_degrades_when_enabled() -> (
    None
):
    now = datetime(2026, 8, 10, 1, 10, tzinfo=UTC)
    TestingSessionLocal = _session_factory()
    with TestingSessionLocal() as session:
        disabled = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(),
            now=now,
            live_runtime_enabled=False,
            alert_runtime_enabled=False,
            notification_transport_configured=False,
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
            now=now,
            live_runtime_enabled=True,
            live_freshness_seconds=300,
            alert_runtime_enabled=False,
            notification_transport_configured=False,
            after_market_status_path=None,
        )

    assert disabled["status"] == "ok"
    assert disabled["components"]["db"]["status"] == "ok"
    assert disabled["components"]["live_market"]["status"] == "disabled"
    assert stale["status"] == "degraded"
    assert stale["components"]["db"]["status"] == "ok"
    assert stale["components"]["live_market"]["status"] == "degraded"
    assert stale["components"]["live_market"]["error_type"] == "live_heartbeat_stale"


def test_runtime_health_is_disabled_before_local_market_runtime_activation(
    monkeypatch, tmp_path
) -> None:
    """The API must remain fail-closed without the fixed local activation marker."""
    monkeypatch.setattr("app.services.runtime_health.PROJECT_ROOT", tmp_path)
    # An env var in the API process cannot stand in for the explicit local activation.
    monkeypatch.setenv("GUIYI_MARKET_RUNTIME_ENABLED", "1")
    TestingSessionLocal = _session_factory()

    with TestingSessionLocal() as session:
        payload = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(),
            after_market_status_path=None,
        )

    live = payload["components"]["live_market"]
    assert live["configured_enabled"] is False
    assert live["status"] == "disabled"


def test_runtime_health_uses_local_activation_marker_not_process_environment(
    monkeypatch, tmp_path
) -> None:
    """A marker enables missing-heartbeat degradation; another launchd job's env cannot."""
    monkeypatch.setattr("app.services.runtime_health.PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("GUIYI_MARKET_RUNTIME_ENABLED", "0")
    marker = tmp_path / ".run" / "market-runtime-enabled"
    marker.parent.mkdir()
    marker.write_text("enabled\n", encoding="utf-8")
    TestingSessionLocal = _session_factory()

    with TestingSessionLocal() as session:
        payload = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(),
            after_market_status_path=None,
        )

    live = payload["components"]["live_market"]
    assert live["configured_enabled"] is True
    assert live["status"] == "degraded"
    assert live["error_type"] == "live_heartbeat_missing"


def test_enabled_after_market_is_pending_before_its_first_runtime_run(
    monkeypatch, tmp_path
) -> None:
    """新 detached Runtime 不迁移旧状态时应显示待首跑，而不是误报未启用。"""
    missing_status = tmp_path / "after-market-status.json"
    monkeypatch.setattr(
        "app.services.runtime_health.load_operational_products", lambda: ("jm",)
    )
    TestingSessionLocal = _session_factory()

    with TestingSessionLocal() as session:
        _seed_calendar(
            session,
            exchanges={"DCE": ("jm",)},
            days={"DCE": ((date(2026, 8, 21), True),)},
        )
        payload = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(),
            now=datetime(2026, 8, 24, 10, 19, tzinfo=UTC),
            live_runtime_enabled=False,
            after_market_automation_enabled=True,
            alert_runtime_enabled=False,
            notification_transport_configured=False,
            after_market_status_path=missing_status,
        )

    after_market = payload["components"]["after_market"]
    assert payload["status"] == "ok"
    assert after_market == {
        "status": "pending",
        "configured_enabled": True,
        "run_state": "pending",
        "expected_trading_day": "2026-08-21",
        "current_run": None,
        "last_run": None,
        "last_successful_trading_day": None,
        "last_failure": None,
        "error_type": None,
        "error_message": None,
    }


def test_enabled_after_market_preserves_activation_state_after_completed_run(
    monkeypatch, tmp_path
) -> None:
    """已完成的盘后状态不能覆盖 Runtime activation 的真实值。"""
    status_path = tmp_path / "after-market-status.json"
    status_path.write_text(
        json.dumps(
            {
                "last_run": {
                    "trading_day": "2026-08-10",
                    "status": "passed",
                    "attempts": 1,
                    "started_at": "2026-08-10T17:00:00+08:00",
                    "finished_at": "2026-08-10T17:30:00+08:00",
                    "products": ["jm"],
                    "error_code": None,
                },
                "last_successful_trading_day": "2026-08-10",
                "last_failure": None,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "app.services.runtime_health.load_operational_products", lambda: ("jm",)
    )
    TestingSessionLocal = _session_factory()

    with TestingSessionLocal() as session:
        _seed_calendar(
            session,
            exchanges={"DCE": ("jm",)},
            days={"DCE": ((date(2026, 8, 10), True),)},
        )
        payload = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(),
            now=datetime(2026, 8, 11, 8, 0, tzinfo=UTC),
            live_runtime_enabled=False,
            after_market_automation_enabled=True,
            after_market_status_path=status_path,
        )

    after_market = payload["components"]["after_market"]
    assert after_market["status"] == "ok"
    assert after_market["configured_enabled"] is True


@pytest.mark.parametrize(
    "legacy_payload",
    (
        pytest.param(
            json.dumps(
                {
                    "last_run": {
                        "trading_day": "2026-08-10",
                        "status": "passed",
                        "attempts": 1,
                        "started_at": "2026-08-10T18:05:00+08:00",
                        "finished_at": "2026-08-10T18:10:00+08:00",
                        "products": ["jm"],
                        "error_code": None,
                    },
                    "last_successful_trading_day": "2026-08-10",
                    "last_failure": None,
                }
            ),
            id="valid-legacy-status",
        ),
        pytest.param("{invalid-json", id="invalid-legacy-status"),
    ),
)
def test_disabled_after_market_ignores_legacy_status_file(
    tmp_path,
    legacy_payload: str,
) -> None:
    """Activation state is authoritative even when an old status file remains."""
    status_path = tmp_path / "after-market-status.json"
    status_path.write_text(legacy_payload, encoding="utf-8")
    TestingSessionLocal = _session_factory()

    with TestingSessionLocal() as session:
        payload = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(),
            now=datetime(2026, 8, 24, 10, 10, tzinfo=UTC),
            live_runtime_enabled=False,
            after_market_automation_enabled=False,
            alert_runtime_enabled=False,
            notification_transport_configured=False,
            after_market_status_path=status_path,
        )

    assert payload["components"]["after_market"] == {
        "status": "disabled",
        "configured_enabled": False,
        "run_state": "disabled",
        "expected_trading_day": None,
        "current_run": None,
        "last_run": None,
        "last_successful_trading_day": None,
        "last_failure": None,
        "error_type": None,
        "error_message": None,
    }


def test_after_market_before_cutoff_is_pending_and_excludes_today(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(
        "app.services.runtime_health.load_operational_products",
        lambda: ("jm",),
        raising=False,
    )
    TestingSessionLocal = _session_factory()
    with TestingSessionLocal() as session:
        _seed_calendar(
            session,
            exchanges={"DCE": ("jm",)},
            days={
                "DCE": (
                    (date(2026, 8, 21), True),
                    (date(2026, 8, 24), True),
                )
            },
        )
        payload = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(),
            now=datetime(2026, 8, 24, 10, 19, tzinfo=UTC),
            live_runtime_enabled=False,
            after_market_automation_enabled=True,
            alert_runtime_enabled=False,
            notification_transport_configured=False,
            after_market_status_path=tmp_path / "missing.json",
        )

    after_market = payload["components"]["after_market"]
    assert after_market["status"] == "pending"
    assert after_market["run_state"] == "pending"
    assert after_market["expected_trading_day"] == "2026-08-21"


def test_after_market_completed_today_before_cutoff_is_healthy(
    monkeypatch, tmp_path
) -> None:
    """Expected day controls due/missed only; local today bounds recorded chronology."""
    monkeypatch.setattr(
        "app.services.runtime_health.load_operational_products", lambda: ("jm",)
    )
    status_path = tmp_path / "after-market-status.json"
    status_path.write_text(
        json.dumps(_completed_after_market_status()),
        encoding="utf-8",
    )
    TestingSessionLocal = _session_factory()

    with TestingSessionLocal() as session:
        _seed_calendar(
            session,
            exchanges={"DCE": ("jm",)},
            days={
                "DCE": (
                    (date(2026, 8, 21), True),
                    (date(2026, 8, 24), True),
                )
            },
        )
        payload = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(),
            now=datetime(2026, 8, 24, 10, 10, tzinfo=UTC),
            live_runtime_enabled=False,
            after_market_automation_enabled=True,
            alert_runtime_enabled=False,
            notification_transport_configured=False,
            after_market_status_path=status_path,
        )

    after_market = payload["components"]["after_market"]
    assert after_market["status"] == "ok"
    assert after_market["run_state"] == "completed"
    assert after_market["expected_trading_day"] == "2026-08-21"
    assert after_market["last_successful_trading_day"] == "2026-08-24"


def test_after_market_missing_at_cutoff_is_degraded_missed(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(
        "app.services.runtime_health.load_operational_products",
        lambda: ("jm",),
        raising=False,
    )
    TestingSessionLocal = _session_factory()
    with TestingSessionLocal() as session:
        _seed_calendar(
            session,
            exchanges={"DCE": ("jm",)},
            days={"DCE": ((date(2026, 8, 24), True),)},
        )
        payload = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(),
            now=datetime(2026, 8, 24, 10, 20, tzinfo=UTC),
            live_runtime_enabled=False,
            after_market_automation_enabled=True,
            alert_runtime_enabled=False,
            notification_transport_configured=False,
            after_market_status_path=tmp_path / "missing.json",
        )

    after_market = payload["components"]["after_market"]
    assert payload["status"] == "degraded"
    assert after_market["status"] == "degraded"
    assert after_market["run_state"] == "missed"
    assert after_market["expected_trading_day"] == "2026-08-24"
    assert after_market["error_type"] == "after_market_run_missed"


def test_after_market_weekend_missing_status_remains_pending(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(
        "app.services.runtime_health.load_operational_products",
        lambda: ("jm",),
        raising=False,
    )
    TestingSessionLocal = _session_factory()
    with TestingSessionLocal() as session:
        _seed_calendar(
            session,
            exchanges={"DCE": ("jm",)},
            days={
                "DCE": (
                    (date(2026, 8, 21), True),
                    (date(2026, 8, 22), False),
                )
            },
        )
        payload = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(),
            now=datetime(2026, 8, 22, 11, 0, tzinfo=UTC),
            live_runtime_enabled=False,
            after_market_automation_enabled=True,
            alert_runtime_enabled=False,
            notification_transport_configured=False,
            after_market_status_path=tmp_path / "missing.json",
        )

    after_market = payload["components"]["after_market"]
    assert after_market["status"] == "pending"
    assert after_market["run_state"] == "pending"
    assert after_market["expected_trading_day"] == "2026-08-21"


def test_after_market_stale_success_is_degraded_missed(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "app.services.runtime_health.load_operational_products",
        lambda: ("jm",),
        raising=False,
    )
    status_path = tmp_path / "after-market-status.json"
    status_path.write_text(
        json.dumps(
            {
                "last_run": {
                    "trading_day": "2026-08-20",
                    "status": "passed",
                    "attempts": 1,
                    "started_at": "2026-08-20T18:05:00+08:00",
                    "finished_at": "2026-08-20T18:15:00+08:00",
                    "products": ["jm"],
                    "error_code": None,
                },
                "last_successful_trading_day": "2026-08-20",
                "last_failure": None,
            }
        ),
        encoding="utf-8",
    )
    TestingSessionLocal = _session_factory()
    with TestingSessionLocal() as session:
        _seed_calendar(
            session,
            exchanges={"DCE": ("jm",)},
            days={"DCE": ((date(2026, 8, 21), True),)},
        )
        payload = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(),
            now=datetime(2026, 8, 24, 8, 0, tzinfo=UTC),
            live_runtime_enabled=False,
            after_market_automation_enabled=True,
            alert_runtime_enabled=False,
            notification_transport_configured=False,
            after_market_status_path=status_path,
        )

    after_market = payload["components"]["after_market"]
    assert after_market["status"] == "degraded"
    assert after_market["run_state"] == "missed"
    assert after_market["expected_trading_day"] == "2026-08-21"


@pytest.mark.parametrize(
    ("started_at", "now", "run_state", "status", "error_type"),
    (
        (
            "2026-08-24T18:05:00+08:00",
            datetime(2026, 8, 24, 11, 0, tzinfo=UTC),
            "running",
            "pending",
            None,
        ),
        (
            "2026-08-24T18:05:00+08:00",
            datetime(2026, 8, 24, 12, 6, tzinfo=UTC),
            "stuck",
            "degraded",
            "after_market_run_stuck",
        ),
        (
            "2026-08-24T22:05:00+08:00",
            datetime(2026, 8, 24, 11, 0, tzinfo=UTC),
            "degraded",
            "degraded",
            "after_market_current_run_invalid",
        ),
        (
            "invalid",
            datetime(2026, 8, 24, 11, 0, tzinfo=UTC),
            "degraded",
            "degraded",
            "after_market_current_run_invalid",
        ),
    ),
)
def test_after_market_current_run_age_is_fail_closed(
    monkeypatch,
    tmp_path,
    started_at: str,
    now: datetime,
    run_state: str,
    status: str,
    error_type: str | None,
) -> None:
    monkeypatch.setattr(
        "app.services.runtime_health.load_operational_products",
        lambda: ("jm",),
        raising=False,
    )
    status_path = tmp_path / "after-market-status.json"
    status_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "current_run": {
                    "scheduled_date": "2026-08-24",
                    "started_at": started_at,
                    "products": ["jm"],
                },
                "last_run": None,
                "last_successful_trading_day": None,
                "last_failure": None,
            }
        ),
        encoding="utf-8",
    )
    TestingSessionLocal = _session_factory()
    with TestingSessionLocal() as session:
        _seed_calendar(
            session,
            exchanges={"DCE": ("jm",)},
            days={"DCE": ((date(2026, 8, 24), True),)},
        )
        payload = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(),
            now=now,
            live_runtime_enabled=False,
            after_market_automation_enabled=True,
            alert_runtime_enabled=False,
            notification_transport_configured=False,
            after_market_status_path=status_path,
        )

    after_market = payload["components"]["after_market"]
    assert after_market["status"] == status
    assert after_market["run_state"] == run_state
    assert after_market["error_type"] == error_type
    assert after_market["current_run"] == (
        None
        if started_at == "invalid"
        else {
            "scheduled_date": "2026-08-24",
            "started_at": started_at,
            "products": ["jm"],
        }
    )


def test_after_market_valid_current_run_does_not_mask_invalid_last_run(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(
        "app.services.runtime_health.load_operational_products", lambda: ("jm",)
    )
    status_path = tmp_path / "after-market-status.json"
    status_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "current_run": {
                    "scheduled_date": "2026-08-24",
                    "started_at": "2026-08-24T18:05:00+08:00",
                    "products": ["jm"],
                },
                "last_run": {"status": "passed"},
                "last_successful_trading_day": "2026-08-21",
                "last_failure": None,
            }
        ),
        encoding="utf-8",
    )
    TestingSessionLocal = _session_factory()
    with TestingSessionLocal() as session:
        _seed_calendar(
            session,
            exchanges={"DCE": ("jm",)},
            days={"DCE": ((date(2026, 8, 24), True),)},
        )
        payload = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(),
            now=datetime(2026, 8, 24, 11, 0, tzinfo=UTC),
            live_runtime_enabled=False,
            after_market_automation_enabled=True,
            alert_runtime_enabled=False,
            notification_transport_configured=False,
            after_market_status_path=status_path,
        )

    after_market = payload["components"]["after_market"]
    assert payload["status"] == "degraded"
    assert after_market["status"] == "degraded"
    assert after_market["run_state"] == "degraded"
    assert after_market["error_type"] == "after_market_status_invalid"


@pytest.mark.parametrize("missing_product", (False, True))
def test_after_market_expected_day_unavailable_or_non_unique_fails_closed(
    monkeypatch, tmp_path, missing_product: bool
) -> None:
    products = ("jm", "rb") if not missing_product else ("jm", "missing")
    monkeypatch.setattr(
        "app.services.runtime_health.load_operational_products",
        lambda: products,
        raising=False,
    )
    TestingSessionLocal = _session_factory()
    with TestingSessionLocal() as session:
        _seed_calendar(
            session,
            exchanges={"DCE": ("jm",), "SHFE": ("rb",)},
            days={
                "DCE": ((date(2026, 8, 21), True),),
                "SHFE": ((date(2026, 8, 20), True),),
            },
        )
        payload = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(),
            now=datetime(2026, 8, 24, 8, 0, tzinfo=UTC),
            live_runtime_enabled=False,
            after_market_automation_enabled=True,
            alert_runtime_enabled=False,
            notification_transport_configured=False,
            after_market_status_path=tmp_path / "missing.json",
        )

    after_market = payload["components"]["after_market"]
    assert after_market["status"] == "degraded"
    assert after_market["run_state"] == "degraded"
    assert after_market["expected_trading_day"] is None
    assert after_market["error_type"] == "after_market_expected_day_invalid"


def test_after_market_cutoff_requires_explicit_today_calendar_fact(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(
        "app.services.runtime_health.load_operational_products", lambda: ("jm",)
    )
    TestingSessionLocal = _session_factory()
    with TestingSessionLocal() as session:
        _seed_calendar(
            session,
            exchanges={"DCE": ("jm",)},
            days={"DCE": ((date(2026, 8, 21), True),)},
        )
        payload = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(),
            now=datetime(2026, 8, 24, 10, 20, tzinfo=UTC),
            live_runtime_enabled=False,
            after_market_automation_enabled=True,
            alert_runtime_enabled=False,
            notification_transport_configured=False,
            after_market_status_path=tmp_path / "missing.json",
        )

    after_market = payload["components"]["after_market"]
    assert after_market["status"] == "degraded"
    assert after_market["run_state"] == "degraded"
    assert after_market["expected_trading_day"] is None
    assert after_market["error_type"] == "after_market_expected_day_invalid"


def test_after_market_present_invalid_last_run_with_valid_success_fails_closed(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(
        "app.services.runtime_health.load_operational_products", lambda: ("jm",)
    )
    status_path = tmp_path / "after-market-status.json"
    status_path.write_text(
        json.dumps(
            {
                "last_run": {"status": "passed"},
                "last_successful_trading_day": "2026-08-24",
                "last_failure": None,
            }
        ),
        encoding="utf-8",
    )
    TestingSessionLocal = _session_factory()
    with TestingSessionLocal() as session:
        _seed_calendar(
            session,
            exchanges={"DCE": ("jm",)},
            days={"DCE": ((date(2026, 8, 24), True),)},
        )
        payload = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(),
            now=datetime(2026, 8, 24, 11, 0, tzinfo=UTC),
            live_runtime_enabled=False,
            after_market_automation_enabled=True,
            alert_runtime_enabled=False,
            notification_transport_configured=False,
            after_market_status_path=status_path,
        )

    after_market = payload["components"]["after_market"]
    assert payload["status"] == "degraded"
    assert after_market["status"] == "degraded"
    assert after_market["run_state"] == "degraded"
    assert after_market["error_type"] == "after_market_status_invalid"


def test_after_market_future_finalized_success_fails_closed(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(
        "app.services.runtime_health.load_operational_products", lambda: ("jm",)
    )
    status_path = tmp_path / "after-market-status.json"
    status_path.write_text(
        json.dumps(
            _completed_after_market_status(
                trading_day="2099-01-01",
                started_at="2099-01-01T18:05:00+08:00",
                finished_at="2099-01-01T18:10:00+08:00",
                last_successful_trading_day="2099-01-01",
            )
        ),
        encoding="utf-8",
    )
    TestingSessionLocal = _session_factory()
    with TestingSessionLocal() as session:
        _seed_calendar(
            session,
            exchanges={"DCE": ("jm",)},
            days={"DCE": ((date(2026, 8, 24), True),)},
        )
        payload = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(),
            now=datetime(2026, 8, 24, 11, 0, tzinfo=UTC),
            live_runtime_enabled=False,
            after_market_automation_enabled=True,
            alert_runtime_enabled=False,
            notification_transport_configured=False,
            after_market_status_path=status_path,
        )

    after_market = payload["components"]["after_market"]
    assert payload["status"] == "degraded"
    assert after_market["status"] == "degraded"
    assert after_market["run_state"] == "degraded"
    assert after_market["error_type"] == "after_market_status_invalid"


@pytest.mark.parametrize(
    "overrides",
    (
        {"finished_at": "2026-08-24T18:04:00+08:00"},
        {"last_successful_trading_day": "2099-01-01"},
        {
            "last_failure": {
                "trading_day": "2099-01-01",
                "error_code": "UPDATE_FAILED",
            }
        },
        {"trading_day": "2026-08-25"},
    ),
)
def test_after_market_finalized_chronology_fails_closed(
    monkeypatch, tmp_path, overrides: dict[str, object]
) -> None:
    monkeypatch.setattr(
        "app.services.runtime_health.load_operational_products", lambda: ("jm",)
    )
    raw = _completed_after_market_status()
    last_run_keys = {"trading_day", "started_at", "finished_at"}
    for key, value in overrides.items():
        if key in last_run_keys:
            raw["last_run"][key] = value
        else:
            raw[key] = value
    status_path = tmp_path / "after-market-status.json"
    status_path.write_text(json.dumps(raw), encoding="utf-8")
    TestingSessionLocal = _session_factory()
    with TestingSessionLocal() as session:
        _seed_calendar(
            session,
            exchanges={"DCE": ("jm",)},
            days={"DCE": ((date(2026, 8, 24), True),)},
        )
        payload = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(),
            now=datetime(2026, 8, 24, 11, 0, tzinfo=UTC),
            live_runtime_enabled=False,
            after_market_automation_enabled=True,
            alert_runtime_enabled=False,
            notification_transport_configured=False,
            after_market_status_path=status_path,
        )

    after_market = payload["components"]["after_market"]
    assert after_market["status"] == "degraded"
    assert after_market["run_state"] == "degraded"
    assert after_market["error_type"] == "after_market_status_invalid"


def test_runtime_health_rejects_invalid_utf8_live_heartbeat_without_leaking_bytes() -> (
    None
):
    TestingSessionLocal = _session_factory()
    with TestingSessionLocal() as session:
        payload = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(
                values={"live:heartbeat": b"\xff\xfetoken=must-not-leak"}
            ),
            live_runtime_enabled=True,
            alert_runtime_enabled=False,
            notification_transport_configured=False,
            after_market_status_path=None,
        )

    live = payload["components"]["live_market"]
    assert payload["status"] == "degraded"
    assert live["status"] == "degraded"
    assert live["error_type"] == "live_heartbeat_invalid"
    assert live["error_message"] is None
    assert _contains_no_secret_words(payload)


def test_runtime_health_surfaces_live_dominant_mismatch(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "app.services.runtime_health.load_operational_products",
        lambda: ("j", "jm", "ap", "ag"),
    )
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
                    "error_code": "LIVE_DOMINANT_MISMATCH",
                    "provider_token": "must-not-leak",
                },
                "last_successful_trading_day": "2026-08-09",
                "last_failure": {
                    "trading_day": "2026-08-10",
                    "error_code": "LIVE_DOMINANT_MISMATCH",
                },
            }
        ),
        encoding="utf-8",
    )
    TestingSessionLocal = _session_factory()
    with TestingSessionLocal() as session:
        _seed_calendar(
            session,
            exchanges={"DCE": ("j", "jm", "ap", "ag")},
            days={"DCE": ((date(2026, 8, 10), True),)},
        )
        payload = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(),
            now=datetime(2026, 8, 10, 10, 30, tzinfo=UTC),
            after_market_automation_enabled=True,
            alert_runtime_enabled=False,
            notification_transport_configured=False,
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
        "error_code": "LIVE_DOMINANT_MISMATCH",
    }
    assert after_market["last_successful_trading_day"] == "2026-08-09"
    assert after_market["last_failure"] == {
        "trading_day": "2026-08-10",
        "error_code": "LIVE_DOMINANT_MISMATCH",
    }
    assert _contains_no_secret_words(payload)


def test_runtime_health_returns_failed_payload_when_redis_unavailable() -> None:
    TestingSessionLocal = _session_factory()
    with TestingSessionLocal() as session:
        payload = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(
                exc=ConnectionError("redis password should-not-leak")
            ),
            now=datetime(2026, 7, 9, 12, 0, tzinfo=UTC),
            alert_runtime_enabled=False,
            notification_transport_configured=False,
            after_market_status_path=None,
        )

    assert payload["status"] == "failed"
    assert payload["components"]["db"]["status"] == "ok"
    assert payload["components"]["redis"]["status"] == "failed"
    assert payload["components"]["redis"]["error_type"] == "ConnectionError"
    assert payload["components"]["redis"]["error_message"] is None
    assert _contains_no_secret_words(payload)


def test_runtime_health_never_exposes_arbitrary_exception_messages() -> None:
    """Catches internal paths, hosts, or query text escaping when no secret keyword is present."""
    TestingSessionLocal = _session_factory()
    with TestingSessionLocal() as session:
        payload = build_runtime_health(
            session,
            redis_factory=lambda: FakeRedis(
                exc=ConnectionError(
                    "127.0.0.1 /private/runtime/catalog.db select internal_table"
                )
            ),
            after_market_status_path=None,
        )

    assert payload["components"]["redis"]["error_type"] == "ConnectionError"
    assert payload["components"]["redis"]["error_message"] is None


class FakeRedis:
    def __init__(
        self, exc: Exception | None = None, values: dict[str, object] | None = None
    ) -> None:
        self.exc = exc
        self.values = values or {}

    def ping(self) -> bool:
        if self.exc is not None:
            raise self.exc
        return True

    def get(self, key: str) -> object:
        return self.values.get(key)


def _completed_after_market_status(
    *,
    trading_day: str = "2026-08-24",
    started_at: str = "2026-08-24T18:05:00+08:00",
    finished_at: str = "2026-08-24T18:10:00+08:00",
    last_successful_trading_day: str = "2026-08-24",
) -> dict[str, object]:
    return {
        "schema_version": 2,
        "current_run": None,
        "last_run": {
            "trading_day": trading_day,
            "status": "passed",
            "attempts": 1,
            "started_at": started_at,
            "finished_at": finished_at,
            "products": ["jm"],
            "error_code": None,
            "failure_notification": None,
        },
        "last_successful_trading_day": last_successful_trading_day,
        "last_failure": None,
    }


def _seed_calendar(
    session,
    *,
    exchanges: dict[str, tuple[str, ...]],
    days: dict[str, tuple[tuple[date, bool], ...]],
) -> None:
    for exchange_code, products in exchanges.items():
        session.add(
            Exchange(
                code=exchange_code,
                name=exchange_code,
                country="CN",
                timezone="Asia/Shanghai",
                is_active=True,
            )
        )
        for product in products:
            session.add(
                Instrument(
                    symbol=product,
                    name=product,
                    exchange_code=exchange_code,
                    is_active=True,
                )
            )
        for trade_date, is_trading_day in days.get(exchange_code, ()):
            session.add(
                TradingCalendar(
                    exchange_code=exchange_code,
                    trade_date=trade_date,
                    is_trading_day=is_trading_day,
                    has_night_session=False,
                )
            )
    session.commit()


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    return TestingSessionLocal


def _contains_no_secret_words(payload: dict) -> bool:
    public = json.loads(json.dumps(payload, ensure_ascii=False, default=str))
    alert = public.get("components", {}).get("alert", {})
    if isinstance(alert, dict):
        alert.pop("notification_transport_configured", None)
    text = json.dumps(public, ensure_ascii=False, default=str).lower()
    return not any(
        secret in text
        for secret in (
            "webhook",
            "token",
            "password",
            "cookie",
            "secret",
            "must-not-leak",
        )
    )
