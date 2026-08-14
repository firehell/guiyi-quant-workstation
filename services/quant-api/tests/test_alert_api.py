from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.alerts.models import AlertEvent, AlertRule
from app.db.session import get_db
from app.main import app


def test_alert_product_state_scope_toggle_and_event_range() -> None:
    testing_session = _session_factory()

    def override_get_db():
        with testing_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        initial = client.get("/api/alerts/products/ag")
        enabled = client.put(
            "/api/alerts/rules/htdy_original_15m/scope/ag",
            json={"enabled": True},
        )
        current = client.get("/api/alerts/products/AG")
        events = client.get(
            "/api/alerts/events",
            params={
                "symbol": "ag",
                "rule_code": "htdy_original_15m",
                "start": "2026-08-13T00:00:00Z",
                "end": "2026-08-14T00:00:00Z",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert initial.status_code == 200
    assert initial.json() == {
        "symbol": "ag",
        "rules": [
            {
                "rule_code": "htdy_original_15m",
                "display_name": "火天大有",
                "indicator_code": "huotian_dayou_original_v0",
                "series_kind": "actual_dominant",
                "frequency": "15m",
                "enabled_for_product": False,
            }
        ],
    }
    assert enabled.status_code == 200
    assert enabled.json()["enabled_for_product"] is True
    assert current.json()["rules"][0]["enabled_for_product"] is True
    assert events.status_code == 200
    assert events.json() == {"items": []}


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
            "/api/alerts/rules/not_a_rule/scope/ag",
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
        session.add(
            AlertRule(
                rule_code="htdy_original_15m",
                indicator_code="huotian_dayou_original_v0",
                frequency="15m",
                enabled=True,
                scope_mode="watchlist",
                scope_products=[],
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        session.commit()
    return factory
