from __future__ import annotations

from datetime import date, datetime
import json

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.signal import SignalEvent, SignalNotification
from app.signal.stage9_wechat import build_stage9_wechat_preview


def test_stage9_wechat_preview_builds_markdown_for_allowed_event() -> None:
    event = _event(payload={"signal": {"reason": "confirmed bar", "webhook_url": "https://example.invalid/token"}})

    preview = build_stage9_wechat_preview(event)

    assert preview["allowed"] is True
    assert preview["blocked_reasons"] == []
    assert preview["would_send"] is False
    assert preview["channel"] == "enterprise_wechat"
    assert preview["notification_recorded"] is False
    assert preview["payload_basis"]["notice_scope"] == "observation_only"
    assert preview["payload_basis"]["trading_instruction"] == "not_trading_instruction"
    assert preview["payload_basis"]["auto_order"] is False
    assert preview["wechat_payload"]["msgtype"] == "markdown"
    content = preview["wechat_payload"]["markdown"]["content"]
    assert "JM2609" in content
    assert "jm.MAIN" in content
    assert "trigger_price" in content
    assert "不构成交易指令" in content
    assert "自动下单" in content
    assert _contains_no_secret_words(preview)


def test_stage9_wechat_preview_blocks_event_without_send_payload() -> None:
    event = _event(actual_contract=None)

    preview = build_stage9_wechat_preview(event)

    assert preview["allowed"] is False
    assert "actual_contract_missing" in preview["blocked_reasons"]
    assert preview["would_send"] is False
    assert preview["notification_recorded"] is False
    assert preview["wechat_payload"] is None
    assert _contains_no_secret_words(preview)


def test_stage9_wechat_preview_api_returns_allowed_payload_and_does_not_record_notification() -> None:
    TestingSessionLocal = _session_factory()
    with TestingSessionLocal() as session:
        event = _event()
        session.add(event)
        session.commit()
        event_id = event.id

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.get(f"/api/signals/events/{event_id}/stage9-wechat/preview")

        assert response.status_code == 200
        payload = response.json()
        assert payload["allowed"] is True
        assert payload["would_send"] is False
        assert payload["notification_recorded"] is False
        assert payload["wechat_payload"]["msgtype"] == "markdown"
        assert "JM2609" in payload["wechat_payload"]["markdown"]["content"]
        assert _contains_no_secret_words(payload)

        with TestingSessionLocal() as session:
            assert session.scalar(select(func.count()).select_from(SignalNotification)) == 0
    finally:
        app.dependency_overrides.clear()


def test_stage9_wechat_preview_api_returns_blocked_reasons() -> None:
    TestingSessionLocal = _session_factory()
    with TestingSessionLocal() as session:
        event = _event(actual_contract=None, contract="jm.MAIN")
        session.add(event)
        session.commit()
        event_id = event.id

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.get(f"/api/signals/events/{event_id}/stage9-wechat/preview")

        assert response.status_code == 200
        payload = response.json()
        assert payload["allowed"] is False
        assert "actual_contract_missing" in payload["blocked_reasons"]
        assert payload["would_send"] is False
        assert payload["notification_recorded"] is False
        assert payload["wechat_payload"] is None

        with TestingSessionLocal() as session:
            assert session.scalar(select(func.count()).select_from(SignalNotification)) == 0
    finally:
        app.dependency_overrides.clear()


def test_stage9_wechat_preview_api_returns_404_for_missing_event() -> None:
    TestingSessionLocal = _session_factory()

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.get("/api/signals/events/999/stage9-wechat/preview")

        assert response.status_code == 404
        assert response.json()["detail"] == "signal event not found"
    finally:
        app.dependency_overrides.clear()


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
        "payload": {"signal": {"reason": "confirmed bar"}},
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


def _contains_no_secret_words(payload: dict) -> bool:
    text = json.dumps(payload, ensure_ascii=False, default=str).lower()
    return not any(secret in text for secret in ("webhook", "token", "password", "cookie", "secret"))
