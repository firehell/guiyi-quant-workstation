from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import base64
from datetime import UTC, date, datetime, timedelta
import json

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.alerts.models import AlertEvent, AlertRule
from app.db.session import get_db
from app.main import app


DAY = date(2026, 8, 15)
BAR_END = datetime(2026, 8, 14, 13, 15, tzinfo=UTC)


def test_alert_history_pages_stably_across_rules_and_equal_times() -> None:
    factory = _session_factory()
    first = _seed(factory, "htdy_original_15m", detected_at=BAR_END + timedelta(seconds=5))
    second = _seed(factory, "subing_ths_alert_15m_v1", detected_at=BAR_END + timedelta(seconds=5))
    third = _seed(
        factory,
        "htdy_original_15m",
        bar_end=BAR_END + timedelta(minutes=15),
        detected_at=BAR_END + timedelta(seconds=5),
    )

    with _client(factory) as client:
        page1 = client.get(
            "/api/alerts/history",
            params={"start_day": DAY.isoformat(), "end_day": DAY.isoformat(), "limit": 2},
        )
        page2 = client.get(
            "/api/alerts/history",
            params={
                "start_day": DAY.isoformat(),
                "end_day": DAY.isoformat(),
                "limit": 2,
                "before": page1.json()["next_before"],
            },
        )

    assert page1.status_code == page2.status_code == 200
    assert [item["id"] for item in page1.json()["items"]] == [third, second]
    assert [item["id"] for item in page2.json()["items"]] == [first]
    assert page2.json()["next_before"] is None
    assert page1.json()["status"] == "ready"
    assert page1.json()["start_day"] == page1.json()["end_day"] == DAY.isoformat()


def test_alert_history_filters_and_binds_cursor_to_the_exact_query() -> None:
    factory = _session_factory()
    _seed(factory, "htdy_original_15m", symbol="jm")
    _seed(
        factory,
        "htdy_original_15m",
        symbol="jm",
        bar_end=BAR_END + timedelta(minutes=15),
    )
    _seed(factory, "subing_ths_alert_15m_v1", symbol="ag")

    with _client(factory) as client:
        page = client.get(
            "/api/alerts/history",
            params={
                "start_day": DAY.isoformat(),
                "end_day": DAY.isoformat(),
                "symbol": "jm",
                "rule_code": "htdy_original_15m",
                "limit": 1,
            },
        )
        drifted = client.get(
            "/api/alerts/history",
            params={
                "start_day": DAY.isoformat(),
                "end_day": DAY.isoformat(),
                "symbol": "ag",
                "rule_code": "htdy_original_15m",
                "limit": 1,
                "before": page.json()["next_before"],
            },
        )

    assert [item["symbol"] for item in page.json()["items"]] == ["jm"]
    assert page.json()["next_before"] is not None
    assert drifted.status_code == 422
    assert drifted.json() == {"detail": {"code": "ALERT_EVENT_CURSOR_INVALID"}}


def test_alert_history_rejects_invalid_range_symbol_and_rule() -> None:
    with _client(_session_factory()) as client:
        backwards = client.get(
            "/api/alerts/history",
            params={"start_day": "2026-08-16", "end_day": "2026-08-15"},
        )
        too_wide = client.get(
            "/api/alerts/history",
            params={"start_day": "2025-08-14", "end_day": "2026-08-15"},
        )
        symbol = client.get(
            "/api/alerts/history",
            params={"start_day": DAY.isoformat(), "end_day": DAY.isoformat(), "symbol": "xx"},
        )
        rule = client.get(
            "/api/alerts/history",
            params={"start_day": DAY.isoformat(), "end_day": DAY.isoformat(), "rule_code": "future"},
        )

    assert backwards.json() == too_wide.json() == {
        "detail": {"code": "ALERT_EVENT_QUERY_INVALID"}
    }
    assert symbol.json() == {"detail": {"code": "ALERT_SYMBOL_NOT_OPERATIONAL"}}
    assert rule.status_code == 404
    assert rule.json() == {"detail": {"code": "ALERT_RULE_NOT_FOUND"}}


def test_alert_history_fails_closed_for_unknown_persisted_rule_without_loading_every_event() -> None:
    factory = _session_factory()
    _seed(factory, "future_rule", create_rule=True)
    selects: list[str] = []

    @event.listens_for(factory.kw["bind"], "before_cursor_execute")
    def _capture(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    try:
        with _client(factory) as client:
            response = client.get(
                "/api/alerts/history",
                params={"start_day": DAY.isoformat(), "end_day": DAY.isoformat(), "limit": 1},
            )
    finally:
        event.remove(factory.kw["bind"], "before_cursor_execute", _capture)

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "ALERT_EVENT_FACTS_INVALID"}}
    assert len(selects) <= 2


def test_alert_history_is_select_only() -> None:
    factory = _session_factory()
    _seed(factory, "htdy_original_15m")
    statements: list[str] = []

    @event.listens_for(factory.kw["bind"], "before_cursor_execute")
    def _capture(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        statements.append(statement.lstrip().split(None, 1)[0].upper())

    try:
        with _client(factory) as client:
            response = client.get(
                "/api/alerts/history",
                params={
                    "start_day": DAY.isoformat(),
                    "end_day": DAY.isoformat(),
                    "rule_code": "htdy_original_15m",
                },
            )
    finally:
        event.remove(factory.kw["bind"], "before_cursor_execute", _capture)

    assert response.status_code == 200
    assert statements and set(statements) == {"SELECT"}


def test_alert_history_rejects_oversized_cursor_before_querying() -> None:
    factory = _session_factory()
    selects: list[str] = []

    @event.listens_for(factory.kw["bind"], "before_cursor_execute")
    def _capture(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    try:
        identity = {
            "start_day": DAY.isoformat(),
            "end_day": DAY.isoformat(),
            "symbol": None,
            "rule_code": None,
            "limit": 30,
        }
        raw = json.dumps(
            {
                "v": 1,
                "query": identity,
                "key": [BAR_END.isoformat(), BAR_END.isoformat(), 1],
                "padding": "x" * 4097,
            }
        ).encode()
        oversized = base64.urlsafe_b64encode(raw).decode().rstrip("=")
        with _client(factory) as client:
            response = client.get(
                "/api/alerts/history",
                params={
                    "start_day": DAY.isoformat(),
                    "end_day": DAY.isoformat(),
                    "before": oversized,
                },
            )
    finally:
        event.remove(factory.kw["bind"], "before_cursor_execute", _capture)

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "ALERT_EVENT_CURSOR_INVALID"}}
    assert selects == []


def test_alert_history_normalizes_database_failure_to_typed_unavailable() -> None:
    factory = _session_factory()

    @event.listens_for(factory.kw["bind"], "before_cursor_execute")
    def _fail(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            raise OperationalError("SELECT", {}, RuntimeError("offline"))

    try:
        with _client(factory, raise_server_exceptions=False) as client:
            response = client.get(
                "/api/alerts/history",
                params={
                    "start_day": DAY.isoformat(),
                    "end_day": DAY.isoformat(),
                    "rule_code": "htdy_original_15m",
                },
            )
    finally:
        event.remove(factory.kw["bind"], "before_cursor_execute", _fail)

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "ALERT_EVENT_QUERY_UNAVAILABLE"}}


def test_alert_history_normalizes_operational_authority_failure(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.api.alerts.load_operational_products",
        lambda: (_ for _ in ()).throw(RuntimeError("authority missing")),
    )

    with _client(_session_factory(), raise_server_exceptions=False) as client:
        response = client.get(
            "/api/alerts/history",
            params={
                "start_day": DAY.isoformat(),
                "end_day": DAY.isoformat(),
                "symbol": "jm",
            },
        )

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "ALERT_EVENT_QUERY_UNAVAILABLE"}}


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
                AlertRule(rule_code="htdy_original_15m", enabled=True, scope_product_frequencies={}),
                AlertRule(rule_code="subing_ths_alert_15m_v1", enabled=True, scope_product_frequencies={}),
            ]
        )
        session.commit()
    return factory


@contextmanager
def _client(
    factory: sessionmaker[Session],
    *,
    raise_server_exceptions: bool = True,
) -> Iterator[TestClient]:
    def override_db() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app, raise_server_exceptions=raise_server_exceptions) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        factory.kw["bind"].dispose()


def _seed(
    factory: sessionmaker[Session],
    rule_code: str,
    *,
    symbol: str = "jm",
    bar_end: datetime = BAR_END,
    detected_at: datetime | None = None,
    create_rule: bool = False,
) -> int:
    with factory() as session:
        rule = session.scalar(select(AlertRule).where(AlertRule.rule_code == rule_code))
        if rule is None and create_rule:
            rule = AlertRule(rule_code=rule_code, enabled=True, scope_product_frequencies={})
            session.add(rule)
            session.flush()
        assert rule is not None
        event_row = AlertEvent(
            rule_id=rule.id,
            symbol=symbol,
            contract=f"{symbol.upper()}2609",
            trading_day=DAY,
            frequency="15m",
            bar_end=bar_end,
            result_codes=["buy"],
            detected_at=detected_at or bar_end + timedelta(seconds=1),
            notification_attempted_at=None,
        )
        session.add(event_row)
        session.commit()
        return event_row.id
