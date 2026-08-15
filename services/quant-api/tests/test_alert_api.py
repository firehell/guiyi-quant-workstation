from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.alerts.current_trading_day import (
    CurrentTradingDayResult,
    CurrentTradingDayStatus,
)
from app.alerts.models import AlertEvent, AlertRule
from app.api import alerts as alerts_api
from app.db.session import get_db
from app.main import app


TRADING_DAY = date(2026, 8, 15)
BAR_END = datetime(2026, 8, 14, 13, 15, tzinfo=UTC)


def test_product_alert_state_returns_registry_metadata() -> None:
    testing_session = _session_factory()

    def override_get_db():
        with testing_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).get("/api/alerts/products/jm")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "symbol": "jm",
        "rules": [
            {
                "rule_code": "htdy_original_15m",
                "display_name": "火天大有",
                "kind": "indicator_observation",
                "input_frequencies": ["15m"],
                "enabled_for_product": False,
            },
            {
                "rule_code": "subing_entry_signal_v1",
                "display_name": "苏冰入场信号",
                "kind": "formal_signal",
                "input_frequencies": ["5m", "15m"],
                "enabled_for_product": False,
            },
        ],
    }


def test_current_alert_views_return_ready_trading_day_events() -> None:
    testing_session = _session_factory()
    _seed_events(testing_session)

    def override_get_db():
        with testing_session() as session:
            yield session

    _override_current_trading_day(
        CurrentTradingDayResult(CurrentTradingDayStatus.READY, TRADING_DAY)
    )
    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        formal = client.get("/api/alerts/formal-signals/current")
        product = client.get("/api/alerts/products/jm/current-events")
    finally:
        app.dependency_overrides.clear()

    assert formal.status_code == 200
    assert formal.json()["status"] == "ready"
    assert formal.json()["trading_day"] == "2026-08-15"
    assert [item["rule_code"] for item in formal.json()["items"]] == [
        "subing_entry_signal_v1"
    ]
    assert formal.json()["items"][0]["display_name"] == "苏冰入场信号"
    assert formal.json()["items"][0]["product_name"] == "焦煤"

    assert product.status_code == 200
    assert product.json()["status"] == "ready"
    assert product.json()["trading_day"] == "2026-08-15"
    assert {item["rule_code"] for item in product.json()["items"]} == {
        "htdy_original_15m",
        "subing_entry_signal_v1",
    }


def test_current_product_events_excludes_database_rules_missing_from_registry() -> None:
    testing_session = _session_factory()
    _seed_current_events_with_rogue_rule(testing_session)

    def override_get_db():
        with testing_session() as session:
            yield session

    _override_current_trading_day(
        CurrentTradingDayResult(CurrentTradingDayStatus.READY, TRADING_DAY)
    )
    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).get("/api/alerts/products/jm/current-events")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert [item["rule_code"] for item in response.json()["items"]] == [
        "subing_entry_signal_v1",
        "htdy_original_15m",
    ]
    assert [item["bar_end"] for item in response.json()["items"]] == [
        "2026-08-14T14:00:00",
        "2026-08-14T13:30:00",
    ]


def test_history_and_current_views_serialize_null_notification_attempt() -> None:
    testing_session = _session_factory()
    _seed_event_with_null_notification_attempt(testing_session)

    def override_get_db():
        with testing_session() as session:
            yield session

    _override_current_trading_day(
        CurrentTradingDayResult(CurrentTradingDayStatus.READY, TRADING_DAY)
    )
    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        history = client.get(
            "/api/alerts/events",
            params={
                "symbol": "jm",
                "rule_code": "subing_entry_signal_v1",
                "start": "2026-08-14T00:00:00Z",
                "end": "2026-08-14T14:01:00Z",
            },
        )
        current = client.get("/api/alerts/formal-signals/current")
    finally:
        app.dependency_overrides.clear()

    assert history.status_code == 200
    assert history.json()["items"] == [
        {
            "id": 1,
            "rule_code": "subing_entry_signal_v1",
            "symbol": "jm",
            "contract": "JM2609",
            "trading_day": "2026-08-15",
            "frequency": "15m",
            "bar_end": "2026-08-14T14:00:00",
            "result_codes": ["buy"],
            "lower_tf_confirmation": False,
            "detected_at": "2026-08-14T14:00:01",
            "notification_attempted_at": None,
        }
    ]
    assert current.status_code == 200
    assert current.json()["items"][0]["notification_attempted_at"] is None


def test_current_alert_views_fail_closed_when_trading_day_is_unavailable() -> None:
    testing_session = _session_factory()
    _seed_events(testing_session)

    def override_get_db():
        with testing_session() as session:
            yield session

    _override_current_trading_day(
        CurrentTradingDayResult(CurrentTradingDayStatus.UNAVAILABLE, None)
    )
    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        formal = client.get("/api/alerts/formal-signals/current")
        product = client.get("/api/alerts/products/jm/current-events")
    finally:
        app.dependency_overrides.clear()

    for response in (formal, product):
        assert response.status_code == 200
        assert response.json() == {
            "status": "unavailable",
            "trading_day": None,
            "items": [],
        }


def test_alert_event_range_returns_v2_dto() -> None:
    testing_session = _session_factory()
    _seed_events(testing_session)

    def override_get_db():
        with testing_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).get(
            "/api/alerts/events",
            params={
                "symbol": "jm",
                "rule_code": "subing_entry_signal_v1",
                "start": "2026-08-14T00:00:00Z",
                "end": "2026-08-14T13:31:00Z",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "id": 2,
                "rule_code": "subing_entry_signal_v1",
                "symbol": "jm",
                "contract": "JM2609",
                "trading_day": "2026-08-15",
                "frequency": "15m",
                "bar_end": "2026-08-14T13:30:00",
                "result_codes": ["buy"],
                "lower_tf_confirmation": True,
                "detected_at": "2026-08-14T13:30:01",
                "notification_attempted_at": "2026-08-14T13:30:02",
            }
        ]
    }


def test_alert_api_rejects_invalid_symbol_and_unknown_rule() -> None:
    testing_session = _session_factory()

    def override_get_db():
        with testing_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        invalid_symbol = client.put(
            "/api/alerts/rules/htdy_original_15m/scope/not-operational",
            json={"enabled": True},
        )
        unknown_rule = client.put(
            "/api/alerts/rules/not_a_rule/scope/jm",
            json={"enabled": True},
        )
    finally:
        app.dependency_overrides.clear()

    assert invalid_symbol.status_code == 422
    assert invalid_symbol.json()["detail"]["code"] == "ALERT_SYMBOL_NOT_OPERATIONAL"
    assert unknown_rule.status_code == 404
    assert unknown_rule.json()["detail"]["code"] == "ALERT_RULE_NOT_FOUND"


def test_alert_api_exposes_no_rule_definition_mutation_surface() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]

    assert "/api/alerts/rules" not in paths
    assert not any(
        "post" in methods
        for path, methods in paths.items()
        if path.startswith("/api/alerts")
    )
    scope_methods = paths["/api/alerts/rules/{rule_code}/scope/{symbol}"]
    assert set(scope_methods) == {"put"}


def _override_current_trading_day(result: CurrentTradingDayResult) -> None:
    app.dependency_overrides[alerts_api.get_current_alert_trading_day] = lambda: result


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    AlertRule.__table__.create(engine)
    AlertEvent.__table__.create(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with factory() as session:
        session.add_all(
            [
                AlertRule(
                    rule_code="htdy_original_15m",
                    enabled=True,
                    scope_products=[],
                    created_at=BAR_END,
                    updated_at=BAR_END,
                ),
                AlertRule(
                    rule_code="subing_entry_signal_v1",
                    enabled=True,
                    scope_products=[],
                    created_at=BAR_END,
                    updated_at=BAR_END,
                ),
            ]
        )
        session.commit()
    return factory


def _seed_events(testing_session: sessionmaker[Session]) -> None:
    with testing_session() as session:
        htdy = session.scalar(
            select(AlertRule).where(AlertRule.rule_code == "htdy_original_15m")
        )
        subing = session.scalar(
            select(AlertRule).where(AlertRule.rule_code == "subing_entry_signal_v1")
        )
        assert htdy is not None
        assert subing is not None
        session.add_all(
            [
                AlertEvent(
                    rule_id=htdy.id,
                    symbol="jm",
                    contract="JM2609",
                    trading_day=TRADING_DAY,
                    frequency="15m",
                    bar_end=BAR_END + timedelta(minutes=15),
                    result_codes=["sell"],
                    lower_tf_confirmation=False,
                    detected_at=BAR_END + timedelta(minutes=15, seconds=1),
                    notification_attempted_at=BAR_END
                    + timedelta(minutes=15, seconds=2),
                ),
                AlertEvent(
                    rule_id=subing.id,
                    symbol="jm",
                    contract="JM2609",
                    trading_day=TRADING_DAY,
                    frequency="15m",
                    bar_end=BAR_END + timedelta(minutes=15),
                    result_codes=["buy"],
                    lower_tf_confirmation=True,
                    detected_at=BAR_END + timedelta(minutes=15, seconds=1),
                    notification_attempted_at=BAR_END
                    + timedelta(minutes=15, seconds=2),
                ),
                AlertEvent(
                    rule_id=subing.id,
                    symbol="jm",
                    contract="JM2609",
                    trading_day=None,
                    frequency="15m",
                    bar_end=BAR_END + timedelta(minutes=30),
                    result_codes=["buy"],
                    lower_tf_confirmation=False,
                    detected_at=BAR_END + timedelta(minutes=30, seconds=1),
                    notification_attempted_at=BAR_END
                    + timedelta(minutes=30, seconds=2),
                ),
            ]
        )
        session.commit()


def _seed_event_with_null_notification_attempt(
    testing_session: sessionmaker[Session],
) -> None:
    with testing_session() as session:
        subing = session.scalar(
            select(AlertRule).where(AlertRule.rule_code == "subing_entry_signal_v1")
        )
        assert subing is not None
        session.add(
            AlertEvent(
                rule_id=subing.id,
                symbol="jm",
                contract="JM2609",
                trading_day=TRADING_DAY,
                frequency="15m",
                bar_end=BAR_END + timedelta(minutes=45),
                result_codes=["buy"],
                lower_tf_confirmation=False,
                detected_at=BAR_END + timedelta(minutes=45, seconds=1),
                notification_attempted_at=None,
            )
        )
        session.commit()


def _seed_current_events_with_rogue_rule(
    testing_session: sessionmaker[Session],
) -> None:
    with testing_session() as session:
        htdy = session.scalar(
            select(AlertRule).where(AlertRule.rule_code == "htdy_original_15m")
        )
        subing = session.scalar(
            select(AlertRule).where(AlertRule.rule_code == "subing_entry_signal_v1")
        )
        assert htdy is not None
        assert subing is not None
        rogue = AlertRule(
            rule_code="rogue_rule",
            enabled=True,
            scope_products=["jm"],
            created_at=BAR_END,
            updated_at=BAR_END,
        )
        session.add(rogue)
        session.flush()
        session.add_all(
            [
                AlertEvent(
                    rule_id=htdy.id,
                    symbol="jm",
                    contract="JM2609",
                    trading_day=TRADING_DAY,
                    frequency="15m",
                    bar_end=BAR_END + timedelta(minutes=15),
                    result_codes=["sell"],
                    lower_tf_confirmation=False,
                    detected_at=BAR_END + timedelta(minutes=15, seconds=1),
                    notification_attempted_at=BAR_END
                    + timedelta(minutes=15, seconds=2),
                ),
                AlertEvent(
                    rule_id=subing.id,
                    symbol="jm",
                    contract="JM2609",
                    trading_day=TRADING_DAY,
                    frequency="15m",
                    bar_end=BAR_END + timedelta(minutes=45),
                    result_codes=["buy"],
                    lower_tf_confirmation=True,
                    detected_at=BAR_END + timedelta(minutes=45, seconds=1),
                    notification_attempted_at=BAR_END
                    + timedelta(minutes=45, seconds=2),
                ),
                AlertEvent(
                    rule_id=rogue.id,
                    symbol="jm",
                    contract="JM2609",
                    trading_day=TRADING_DAY,
                    frequency="15m",
                    bar_end=BAR_END + timedelta(minutes=60),
                    result_codes=["buy"],
                    lower_tf_confirmation=False,
                    detected_at=BAR_END + timedelta(minutes=60, seconds=1),
                    notification_attempted_at=BAR_END
                    + timedelta(minutes=60, seconds=2),
                ),
            ]
        )
        session.commit()
