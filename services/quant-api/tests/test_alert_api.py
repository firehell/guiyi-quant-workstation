from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.alerts.current_trading_day import (
    CurrentTradingDayResult,
    CurrentTradingDayStatus,
)
from app.alerts.models import AlertEvent, AlertRule
from app.alerts.strategy_payload import serialize_subing_strategy_payload
from app.api import alerts as alerts_api
from app.db.session import get_db
from app.main import app
from app.market_data.subing_lifecycle import ConfirmationSource
from app.market_data.subing_strategy.contracts import (
    SubingStrategyAction,
    SubingStrategyActionKind,
    SubingStrategyFillBasis,
    subing_strategy_action_id,
    subing_strategy_episode_id,
)


TRADING_DAY = date(2026, 8, 15)
DECISION_AT = datetime(2026, 8, 14, 13, 15, tzinfo=UTC)


def test_product_alert_state_returns_strategy_registry_metadata() -> None:
    with _client() as client:
        response = client.get("/api/alerts/products/jm")

    assert response.status_code == 200
    assert response.json() == {
        "symbol": "jm",
        "rules": [
            {
                "rule_code": "htdy_original_15m",
                "display_name": "火天大有",
                "kind": "indicator_observation",
                "input_frequencies": ["1m", "5m", "15m", "30m", "60m", "1d", "1w"],
                "enabled_frequencies": [],
                "enabled_for_product": False,
            },
            {
                "rule_code": "subing_strategy_v1",
                "display_name": "苏冰策略",
                "kind": "strategy_action",
                "input_frequencies": ["1m", "5m", "15m"],
                "enabled_frequencies": [],
                "enabled_for_product": False,
            },
        ],
    }


def test_current_views_return_typed_strategy_action_and_null_htdy_fields() -> None:
    factory = _session_factory()
    action = _strategy_action()
    _seed_htdy_event(factory)
    _seed_strategy_event(factory, action)
    _override_current_trading_day(
        CurrentTradingDayResult(CurrentTradingDayStatus.READY, TRADING_DAY)
    )

    with _client(factory) as client:
        strategy = client.get("/api/alerts/strategy-actions/current")
        product = client.get("/api/alerts/products/jm/current-events")

    assert strategy.status_code == 200
    assert strategy.json()["trading_day"] == "2026-08-15"
    item = strategy.json()["items"][0]
    assert item["rule_code"] == "subing_strategy_v1"
    assert item["display_name"] == "苏冰策略"
    assert item["product_name"] == "焦煤"
    assert item["action_id"] == action.action_id
    expected_action = serialize_subing_strategy_payload(action).to_json()
    for key in ("decision_at", "effective_open_at", "effective_bar_end"):
        expected_action[key] = str(expected_action[key]).replace("+00:00", "Z")
    assert item["strategy_action"] == expected_action
    by_rule = {entry["rule_code"]: entry for entry in product.json()["items"]}
    assert by_rule["htdy_original_15m"]["action_id"] is None
    assert by_rule["htdy_original_15m"]["strategy_action"] is None
    assert by_rule["subing_strategy_v1"]["strategy_action"]["kind"] == "open_long"
    assert all("lower_tf_confirmation" not in entry for entry in by_rule.values())


def test_cross_day_next_open_event_is_in_effective_trading_day_view() -> None:
    factory = _session_factory()
    action = _strategy_action(
        decision_at=datetime(2026, 8, 14, 13, 45, tzinfo=UTC),
        effective_bar_end=datetime(2026, 8, 14, 14, 15, tzinfo=UTC),
    )
    _seed_strategy_event(factory, action)
    _override_current_trading_day(
        CurrentTradingDayResult(CurrentTradingDayStatus.READY, TRADING_DAY)
    )

    with _client(factory) as client:
        response = client.get("/api/alerts/strategy-actions/current")

    assert response.status_code == 200
    assert [item["action_id"] for item in response.json()["items"]] == [
        action.action_id
    ]
    assert response.json()["items"][0]["bar_end"] == "2026-08-14T13:45:00Z"
    assert (
        response.json()["items"][0]["strategy_action"]["effective_bar_end"]
        == "2026-08-14T14:15:00Z"
    )


def test_alert_range_fails_closed_for_malformed_rule_payload_pair() -> None:
    factory = _session_factory()
    action = _strategy_action()
    _seed_strategy_event(factory, action, payload_override=None)

    with _client(factory) as client:
        response = client.get(
            "/api/alerts/events",
            params={
                "symbol": "jm",
                "rule_code": "subing_strategy_v1",
                "start": "2026-08-14T00:00:00Z",
                "end": "2026-08-14T14:01:00Z",
            },
        )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ALERT_EVENT_FACTS_INVALID"


def test_current_views_fail_closed_when_trading_day_is_unavailable() -> None:
    _override_current_trading_day(
        CurrentTradingDayResult(CurrentTradingDayStatus.UNAVAILABLE, None)
    )
    with _client() as client:
        strategy = client.get("/api/alerts/strategy-actions/current")
        product = client.get("/api/alerts/products/jm/current-events")

    for response in (strategy, product):
        assert response.status_code == 200
        assert response.json() == {
            "status": "unavailable",
            "trading_day": None,
            "items": [],
        }


def test_old_formal_signal_route_and_rule_code_are_absent() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    assert "/api/alerts/formal-signals/current" not in paths
    assert "/api/alerts/strategy-actions/current" in paths

    with _client() as client:
        old_rule = client.put(
            "/api/alerts/rules/subing_entry_signal_v1/scope/jm",
            json={"enabled": True},
        )
    assert old_rule.status_code == 404


def test_alert_api_mutates_only_each_rules_authoritative_scope() -> None:
    factory = _session_factory()
    with _client(factory) as client:
        htdy_pair = client.put(
            "/api/alerts/rules/htdy_original_15m/scope/jm/15m", json={"enabled": True}
        )
        strategy_pair = client.put(
            "/api/alerts/rules/subing_strategy_v1/scope/jm/15m", json={"enabled": True}
        )
        htdy_product = client.put(
            "/api/alerts/rules/htdy_original_15m/scope/jm", json={"enabled": True}
        )
        strategy_product = client.put(
            "/api/alerts/rules/subing_strategy_v1/scope/jm", json={"enabled": True}
        )

    assert htdy_pair.status_code == 200
    assert strategy_pair.status_code == 422
    assert strategy_pair.json()["detail"]["code"] == "ALERT_SCOPE_MODE_INVALID"
    assert htdy_product.status_code == 422
    assert htdy_product.json()["detail"]["code"] == "ALERT_SCOPE_MODE_INVALID"
    assert strategy_product.status_code == 200


def test_current_product_events_exclude_unregistered_database_rules() -> None:
    factory = _session_factory()
    _seed_htdy_event(factory)
    with factory() as session:
        rogue = AlertRule(
            rule_code="rogue_rule",
            enabled=True,
            scope_products=["jm"],
            scope_product_frequencies={},
            created_at=DECISION_AT,
            updated_at=DECISION_AT,
        )
        session.add(rogue)
        session.flush()
        session.add(
            AlertEvent(
                rule_id=rogue.id,
                symbol="jm",
                contract="JM2609",
                trading_day=TRADING_DAY,
                frequency="15m",
                bar_end=DECISION_AT + timedelta(minutes=30),
                result_codes=["buy"],
                action_id=None,
                strategy_payload=None,
                detected_at=DECISION_AT + timedelta(minutes=30, seconds=1),
                notification_attempted_at=None,
            )
        )
        session.commit()
    _override_current_trading_day(
        CurrentTradingDayResult(CurrentTradingDayStatus.READY, TRADING_DAY)
    )

    with _client(factory) as client:
        response = client.get("/api/alerts/products/jm/current-events")

    assert response.status_code == 200
    assert [item["rule_code"] for item in response.json()["items"]] == [
        "htdy_original_15m"
    ]


def _client(factory: sessionmaker[Session] | None = None):
    selected = factory or _session_factory()

    def override_get_db():
        with selected() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    class _ClientContext:
        def __enter__(self):
            return client

        def __exit__(self, *_args: object) -> None:
            app.dependency_overrides.clear()

    return _ClientContext()


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
                    scope_product_frequencies={},
                    created_at=DECISION_AT,
                    updated_at=DECISION_AT,
                ),
                AlertRule(
                    rule_code="subing_strategy_v1",
                    enabled=True,
                    scope_products=[],
                    scope_product_frequencies={},
                    created_at=DECISION_AT,
                    updated_at=DECISION_AT,
                ),
            ]
        )
        session.commit()
    return factory


def _strategy_action(
    *,
    decision_at: datetime = DECISION_AT,
    effective_bar_end: datetime = DECISION_AT + timedelta(minutes=15),
) -> SubingStrategyAction:
    identity = {
        "strategy_id": "subing_strategy_v1",
        "formula_version": "subing_strategy_15m_v1",
        "symbol": "jm",
        "contract": "JM2609",
        "segment_start_trading_day": TRADING_DAY.isoformat(),
        "opportunity_id": "subing-opportunity:test",
        "kind": "open_long",
        "decision_at": decision_at.isoformat(),
        "effective_bar_end": effective_bar_end.isoformat(),
        "fill_basis": "next_bar_open",
    }
    return SubingStrategyAction(
        action_id=subing_strategy_action_id(identity),
        episode_id=subing_strategy_episode_id(identity),
        strategy_id="subing_strategy_v1",
        formula_version="subing_strategy_15m_v1",
        kind=SubingStrategyActionKind.OPEN_LONG,
        symbol="jm",
        contract="JM2609",
        trading_day=TRADING_DAY,
        segment_start_trading_day=TRADING_DAY,
        opportunity_id="subing-opportunity:test",
        decision_at=decision_at,
        effective_open_at=effective_bar_end - timedelta(minutes=15),
        effective_bar_end=effective_bar_end,
        reference_price=Decimal("100.00"),
        fill_basis=SubingStrategyFillBasis.NEXT_BAR_OPEN,
        confirmation_source=ConfirmationSource.FORMAL_V1,
        reason_codes=(),
        direction_context_source_day=TRADING_DAY,
        direction_context_target_day=TRADING_DAY,
        bound_reference_pivot=None,
    )


def _seed_htdy_event(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        rule = session.scalar(
            select(AlertRule).where(AlertRule.rule_code == "htdy_original_15m")
        )
        assert rule is not None
        session.add(
            AlertEvent(
                rule_id=rule.id,
                symbol="jm",
                contract="JM2609",
                trading_day=TRADING_DAY,
                frequency="15m",
                bar_end=DECISION_AT,
                result_codes=["sell"],
                action_id=None,
                strategy_payload=None,
                detected_at=DECISION_AT + timedelta(seconds=1),
                notification_attempted_at=DECISION_AT + timedelta(seconds=2),
            )
        )
        session.commit()


_DEFAULT_PAYLOAD = object()


def _seed_strategy_event(
    factory: sessionmaker[Session],
    action: SubingStrategyAction,
    *,
    payload_override: object = _DEFAULT_PAYLOAD,
) -> None:
    payload = (
        serialize_subing_strategy_payload(action).to_json()
        if payload_override is _DEFAULT_PAYLOAD
        else payload_override
    )
    with factory() as session:
        rule = session.scalar(
            select(AlertRule).where(AlertRule.rule_code == "subing_strategy_v1")
        )
        assert rule is not None
        session.add(
            AlertEvent(
                rule_id=rule.id,
                symbol=action.symbol,
                contract=action.contract,
                trading_day=action.trading_day,
                frequency="15m",
                bar_end=action.decision_at,
                result_codes=[action.kind.value],
                action_id=action.action_id,
                strategy_payload=payload,
                detected_at=action.decision_at + timedelta(seconds=1),
                notification_attempted_at=None,
            )
        )
        session.commit()
