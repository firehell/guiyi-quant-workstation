from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from collections.abc import Iterator

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


def test_product_alert_state_contains_only_htdy() -> None:
    with client() as value:
        response = value.get("/api/alerts/products/jm")
    assert response.status_code == 200
    assert response.json()["symbol"] == "jm"
    rules = response.json()["rules"]
    assert len(rules) == 1
    assert rules[0]["rule_code"] == "htdy_original_15m"
    assert rules[0]["kind"] == "indicator_observation"


def test_frequency_scope_put_and_removed_product_scope_path() -> None:
    with client() as value:
        enabled = value.put(
            "/api/alerts/rules/htdy_original_15m/scope/jm/15m",
            json={"enabled": True},
        )
        removed = value.put(
            "/api/alerts/rules/htdy_original_15m/scope/jm",
            json={"enabled": True},
        )
    assert enabled.status_code == 200
    assert enabled.json()["enabled_frequencies"] == ["15m"]
    assert removed.status_code == 404


def test_event_range_returns_typed_htdy_event() -> None:
    factory = session_factory()
    seed_event(factory)
    with client(factory) as value:
        response = value.get(
            "/api/alerts/events",
            params={
                "symbol": "jm",
                "rule_code": "htdy_original_15m",
                "start": (BAR_END - timedelta(minutes=1)).isoformat(),
                "end": (BAR_END + timedelta(minutes=1)).isoformat(),
            },
        )
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["rule_code"] == "htdy_original_15m"
    assert item["result_codes"] == ["sell"]
    assert set(item) == {
        "id", "rule_code", "symbol", "contract", "trading_day", "frequency",
        "bar_end", "result_codes", "detected_at", "notification_attempted_at",
    }


def test_current_events_are_ready_or_typed_unavailable() -> None:
    factory = session_factory()
    seed_event(factory)
    with client(
        factory,
        CurrentTradingDayResult(CurrentTradingDayStatus.READY, TRADING_DAY),
    ) as value:
        ready = value.get("/api/alerts/products/jm/current-events")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert len(ready.json()["items"]) == 1

    with client(
        factory,
        CurrentTradingDayResult(CurrentTradingDayStatus.UNAVAILABLE, None),
    ) as value:
        unavailable = value.get("/api/alerts/products/jm/current-events")
    assert unavailable.json() == {
        "status": "unavailable", "trading_day": None, "items": []
    }


def test_event_range_rejects_unknown_rule_and_naive_time() -> None:
    with client() as value:
        unknown = value.get(
            "/api/alerts/events",
            params={
                "symbol": "jm", "rule_code": "future_rule",
                "start": (BAR_END - timedelta(minutes=1)).isoformat(),
                "end": (BAR_END + timedelta(minutes=1)).isoformat(),
            },
        )
        naive = value.get(
            "/api/alerts/events",
            params={
                "symbol": "jm", "rule_code": "htdy_original_15m",
                "start": "2026-08-14T13:14:00",
                "end": "2026-08-14T13:16:00",
            },
        )
    assert unknown.status_code == 404
    assert naive.status_code == 422


def session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    AlertRule.__table__.create(engine)
    AlertEvent.__table__.create(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        session.add(AlertRule(
            rule_code="htdy_original_15m",
            enabled=True,
            scope_product_frequencies={},
        ))
        session.commit()
    return factory


@contextmanager
def client(
    factory: sessionmaker[Session] | None = None,
    current_day: CurrentTradingDayResult | None = None,
) -> Iterator[TestClient]:
    factory = factory or session_factory()

    def override_db() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[alerts_api.get_current_alert_trading_day] = lambda: (
        current_day
        or CurrentTradingDayResult(CurrentTradingDayStatus.READY, TRADING_DAY)
    )
    try:
        with TestClient(app) as value:
            yield value
    finally:
        app.dependency_overrides.clear()
        factory.kw["bind"].dispose()


def seed_event(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        rule = session.scalar(
            select(AlertRule).where(AlertRule.rule_code == "htdy_original_15m")
        )
        assert rule is not None
        session.add(AlertEvent(
            rule_id=rule.id,
            symbol="jm",
            contract="JM2609",
            trading_day=TRADING_DAY,
            frequency="15m",
            bar_end=BAR_END,
            result_codes=["sell"],
            detected_at=BAR_END + timedelta(seconds=1),
            notification_attempted_at=BAR_END + timedelta(seconds=2),
        ))
        session.commit()
