from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from collections.abc import Iterator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.alerts.current_trading_day import CurrentTradingDayResult, CurrentTradingDayStatus
from app.alerts.models import AlertEvent, AlertRule
from app.api import alerts as alerts_api
from app.db.session import get_db
from app.main import app


TRADING_DAY = date(2026, 8, 15)
BAR_END = datetime(2026, 8, 14, 13, 15, tzinfo=UTC)


def test_current_events_returns_only_current_htdy_events_in_descending_order() -> None:
    factory = _session_factory()
    _seed_events(factory)

    with _client(factory, CurrentTradingDayResult(CurrentTradingDayStatus.READY, TRADING_DAY)) as client:
        response = client.get("/api/alerts/current-events")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["trading_day"] == "2026-08-15"
    assert [item["frequency"] for item in payload["items"]] == ["30m", "15m"]
    assert all(item["rule_code"] == "htdy_original_15m" for item in payload["items"])


def test_current_events_keeps_unavailable_distinct_from_an_empty_ready_list() -> None:
    with _client(
        _session_factory(),
        CurrentTradingDayResult(CurrentTradingDayStatus.UNAVAILABLE, None),
    ) as client:
        response = client.get("/api/alerts/current-events", params={"limit": 30})

    assert response.status_code == 200
    assert response.json() == {
        "status": "unavailable",
        "trading_day": None,
        "items": [],
    }


def test_current_events_validates_limit() -> None:
    with _client(_session_factory(), CurrentTradingDayResult(CurrentTradingDayStatus.READY, TRADING_DAY)) as client:
        too_small = client.get("/api/alerts/current-events", params={"limit": 0})
        too_large = client.get("/api/alerts/current-events", params={"limit": 101})

    assert too_small.status_code == 422
    assert too_large.status_code == 422


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    AlertRule.__table__.create(engine)
    AlertEvent.__table__.create(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        session.add_all(
            [
                AlertRule(
                    rule_code="htdy_original_15m",
                    enabled=True,
                    scope_product_frequencies={},
                ),
                AlertRule(
                    rule_code="retired_rule",
                    enabled=True,
                    scope_product_frequencies={},
                ),
            ]
        )
        session.commit()
    return factory


def _seed_events(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        active = session.scalar(select(AlertRule).where(AlertRule.rule_code == "htdy_original_15m"))
        legacy = session.scalar(select(AlertRule).where(AlertRule.rule_code == "retired_rule"))
        assert active is not None
        assert legacy is not None
        session.add_all(
            [
                _event(active.id, frequency="15m", detected_at=BAR_END + timedelta(seconds=5)),
                _event(
                    active.id,
                    frequency="30m",
                    bar_end=BAR_END + timedelta(minutes=15),
                    detected_at=BAR_END + timedelta(seconds=10),
                ),
                _event(
                    legacy.id,
                    frequency="60m",
                    detected_at=BAR_END + timedelta(seconds=20),
                ),
                _event(
                    active.id,
                    frequency="5m",
                    trading_day=date(2026, 8, 14),
                    detected_at=BAR_END + timedelta(seconds=30),
                ),
            ]
        )
        session.commit()


def _event(
    rule_id: int,
    *,
    frequency: str,
    trading_day: date = TRADING_DAY,
    bar_end: datetime = BAR_END,
    detected_at: datetime,
) -> AlertEvent:
    return AlertEvent(
        rule_id=rule_id,
        symbol="jm",
        contract="JM2609",
        trading_day=trading_day,
        frequency=frequency,
        bar_end=bar_end,
        result_codes=["buy"],
        detected_at=detected_at,
        notification_attempted_at=None,
    )


@contextmanager
def _client(
    factory: sessionmaker[Session], current_day: CurrentTradingDayResult
) -> Iterator[TestClient]:
    def override_db() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[alerts_api.get_current_alert_trading_day] = lambda: current_day
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        factory.kw["bind"].dispose()
