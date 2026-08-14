from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.alerts.models import AlertEvent, AlertRule


@pytest.fixture
def session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    AlertRule.__table__.create(engine)
    AlertEvent.__table__.create(engine)
    with Session(engine) as session:
        session.add(
            AlertRule(
                rule_code="htdy_original_15m",
                indicator_code="huotian_dayou_original_v0",
                frequency="15m",
                enabled=True,
                scope_mode="watchlist",
                scope_products=[],
            )
        )
        session.commit()
        yield session
    engine.dispose()


def test_scope_add_normalizes_and_remove_is_idempotent(session: Session) -> None:
    from app.alerts.service import AlertService

    service = AlertService(session, operational_products=("ag", "jm"))

    enabled = service.set_product_enabled("htdy_original_15m", " AG ", True)
    assert enabled.enabled_for_product is True
    assert session.scalar(select(AlertRule)).scope_products == ["ag"]

    disabled = service.set_product_enabled("htdy_original_15m", "ag", False)
    disabled_again = service.set_product_enabled("htdy_original_15m", "ag", False)
    assert disabled.enabled_for_product is False
    assert disabled_again.enabled_for_product is False
    assert session.scalar(select(AlertRule)).scope_products == []


def test_scope_update_locks_rule_row_before_replacing_array(session: Session) -> None:
    from app.alerts.service import AlertService

    statements: list[object] = []

    def capture_statement(execute_state: object) -> None:
        statement = execute_state.statement  # type: ignore[attr-defined]
        if getattr(execute_state, "is_select", False):
            statements.append(statement)

    event.listen(session, "do_orm_execute", capture_statement)
    try:
        AlertService(session, operational_products=("ag",)).set_product_enabled(
            "htdy_original_15m", "ag", True
        )
    finally:
        event.remove(session, "do_orm_execute", capture_statement)

    assert any(
        getattr(statement, "_for_update_arg", None) is not None
        for statement in statements
    )


def test_scope_commit_failure_rolls_back_and_returns_stable_error(session: Session) -> None:
    from app.alerts.service import AlertScopeError, AlertService

    def fail_commit(_: Session) -> None:
        raise SQLAlchemyError("database detail must not escape")

    event.listen(session, "before_commit", fail_commit, once=True)

    with pytest.raises(AlertScopeError, match="ALERT_SCOPE_PERSIST_FAILED"):
        AlertService(session, operational_products=("ag",)).set_product_enabled(
            "htdy_original_15m", "ag", True
        )

    assert session.in_transaction() is False


def test_scope_rejects_non_operational_symbol_and_unknown_rule(session: Session) -> None:
    from app.alerts.service import (
        AlertRuleNotFoundError,
        AlertScopeError,
        AlertService,
    )

    service = AlertService(session, operational_products=("ag",))

    with pytest.raises(AlertScopeError, match="ALERT_SYMBOL_NOT_OPERATIONAL"):
        service.set_product_enabled("htdy_original_15m", "jm", True)
    with pytest.raises(AlertRuleNotFoundError, match="ALERT_RULE_NOT_FOUND"):
        service.set_product_enabled("not_a_rule", "ag", True)


def test_product_rules_returns_disabled_rule_without_hiding_scope(session: Session) -> None:
    from app.alerts.service import AlertService

    rule = session.scalar(select(AlertRule))
    assert rule is not None
    rule.enabled = False
    rule.scope_products = ["ag"]
    session.commit()

    states = AlertService(session, operational_products=("ag",)).product_rules("ag")

    assert len(states) == 1
    assert states[0].rule_code == "htdy_original_15m"
    assert states[0].enabled_for_product is True


def test_create_event_normalizes_observation_order_and_deduplicates(session: Session) -> None:
    from app.alerts.service import AlertEventCreate, AlertService

    rule = session.scalar(select(AlertRule))
    assert rule is not None
    service = AlertService(session, operational_products=("ag",))
    bar_end = datetime(2026, 8, 13, 2, 45, tzinfo=UTC)
    request = AlertEventCreate(
        rule_id=rule.id,
        symbol="AG",
        contract="ag2610",
        frequency="15m",
        bar_end=bar_end,
        observation_types=("sell", "buy"),
        detected_at=bar_end + timedelta(seconds=1),
        notified_at=bar_end + timedelta(seconds=2),
    )

    created = service.create_event(request)
    duplicate = service.create_event(request)

    assert created is not None
    assert created.symbol == "ag"
    assert created.contract == "AG2610"
    assert created.observation_types == ["buy", "sell"]
    assert duplicate is None
    assert len(session.scalars(select(AlertEvent)).all()) == 1


def test_duplicate_event_with_changed_contract_or_observation_fails_closed(
    session: Session,
) -> None:
    from app.alerts.service import (
        AlertConsistencyError,
        AlertEventCreate,
        AlertService,
    )

    rule = session.scalar(select(AlertRule))
    assert rule is not None
    service = AlertService(session, operational_products=("ag",))
    bar_end = datetime(2026, 8, 13, 2, 45, tzinfo=UTC)
    base = dict(
        rule_id=rule.id,
        symbol="ag",
        frequency="15m",
        bar_end=bar_end,
        detected_at=bar_end,
        notified_at=bar_end,
    )
    service.create_event(
        AlertEventCreate(contract="AG2610", observation_types=("buy",), **base)
    )

    with pytest.raises(AlertConsistencyError, match="ALERT_EVENT_CONSISTENCY_ERROR"):
        service.create_event(
            AlertEventCreate(contract="AG2611", observation_types=("buy",), **base)
        )
    with pytest.raises(AlertConsistencyError, match="ALERT_EVENT_CONSISTENCY_ERROR"):
        service.create_event(
            AlertEventCreate(contract="AG2610", observation_types=("sell",), **base)
        )


def test_event_range_is_symbol_rule_filtered_and_ordered(session: Session) -> None:
    from app.alerts.service import AlertEventCreate, AlertService

    rule = session.scalar(select(AlertRule))
    assert rule is not None
    service = AlertService(session, operational_products=("ag", "jm"))
    start = datetime(2026, 8, 13, 1, 0, tzinfo=UTC)
    for offset, symbol in ((45, "ag"), (15, "ag"), (30, "jm")):
        bar_end = start + timedelta(minutes=offset)
        service.create_event(
            AlertEventCreate(
                rule_id=rule.id,
                symbol=symbol,
                contract=f"{symbol.upper()}2610",
                frequency="15m",
                bar_end=bar_end,
                observation_types=("buy",),
                detected_at=bar_end,
                notified_at=bar_end,
            )
        )

    events = service.list_events(
        symbol="AG",
        rule_code="htdy_original_15m",
        start=start,
        end=start + timedelta(hours=1),
    )

    assert [event.bar_end.replace(tzinfo=UTC) for event in events] == [
        start + timedelta(minutes=15),
        start + timedelta(minutes=45),
    ]
