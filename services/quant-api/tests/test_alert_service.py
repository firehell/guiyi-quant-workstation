from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.alerts.models import AlertEvent, AlertRule
from app.alerts.service import (
    AlertConsistencyError,
    AlertEventCreate,
    AlertRuleNotFoundError,
    AlertScopeError,
    AlertService,
)


TRADING_DAY = date(2026, 8, 15)
BAR_END = datetime(2026, 8, 14, 13, 15, tzinfo=UTC)


@pytest.fixture
def session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    AlertRule.__table__.create(engine)
    AlertEvent.__table__.create(engine)
    with Session(engine) as value:
        value.add(AlertRule(
            rule_code="htdy_original_15m",
            enabled=True,
            scope_product_frequencies={"jm": ["15m"]},
        ))
        value.commit()
        yield value
    engine.dispose()


def test_product_rules_exposes_only_htdy_frequency_scope(session: Session) -> None:
    state = AlertService(session, operational_products=("jm",)).product_rules(" JM ")[0]
    assert state.rule_code == "htdy_original_15m"
    assert state.kind == "indicator_observation"
    assert state.enabled_frequencies == ("15m",)
    assert state.enabled_for_product is True


def test_frequency_scope_mutation_is_normalized_and_idempotent(session: Session) -> None:
    service = AlertService(session, operational_products=("jm",))
    enabled = service.set_product_frequency_enabled(
        "htdy_original_15m", " JM ", "5m", True
    )
    assert enabled.enabled_frequencies == ("5m", "15m")
    disabled = service.set_product_frequency_enabled(
        "htdy_original_15m", "jm", "5m", False
    )
    assert disabled.enabled_frequencies == ("15m",)


@pytest.mark.parametrize("frequency", ["", "4h"])
def test_frequency_scope_rejects_noncanonical_frequency(
    session: Session, frequency: str
) -> None:
    with pytest.raises(AlertScopeError, match="ALERT_SCOPE_FREQUENCY_INVALID"):
        AlertService(session, operational_products=("jm",)).set_product_frequency_enabled(
            "htdy_original_15m", "jm", frequency, True
        )


def test_scope_and_rule_fail_closed(session: Session) -> None:
    service = AlertService(session, operational_products=("jm",))
    with pytest.raises(AlertScopeError, match="ALERT_SYMBOL_NOT_OPERATIONAL"):
        service.product_rules("ag")
    with pytest.raises(AlertRuleNotFoundError):
        service.set_product_frequency_enabled("future_rule", "jm", "15m", True)


def test_create_event_normalizes_codes_and_is_idempotent(session: Session) -> None:
    service = AlertService(session, operational_products=("jm",))
    rule = session.scalar(select(AlertRule))
    assert rule is not None
    created = service.create_event(request(rule.id, result_codes=("sell", "buy")))
    assert created is not None
    assert created.result_codes == ["buy", "sell"]
    assert service.create_event(request(rule.id, result_codes=("buy", "sell"))) is None
    assert session.query(AlertEvent).count() == 1


def test_changed_duplicate_facts_fail_closed(session: Session) -> None:
    service = AlertService(session, operational_products=("jm",))
    rule = session.scalar(select(AlertRule))
    assert rule is not None
    assert service.create_event(request(rule.id)) is not None
    with pytest.raises(AlertConsistencyError):
        service.create_event(request(rule.id, contract="JM2611"))


def test_subing_exact_event_requires_matching_duplicate_facts(session: Session) -> None:
    rule = AlertRule(
        rule_code="subing_ths_alert_15m_v1",
        enabled=True,
        scope_product_frequencies={"jm": ["15m"]},
    )
    session.add(rule)
    session.commit()
    service = AlertService(session, operational_products=("jm",))
    assert service.create_event(request(rule.id, result_codes=("buy",))) is not None
    assert service.create_event(request(rule.id, result_codes=("buy",))) is None
    with pytest.raises(AlertConsistencyError):
        service.create_event(request(rule.id, result_codes=("sell",)))


def test_first_seen_duplicate_freezes_original_facts(session: Session) -> None:
    service = AlertService(session, operational_products=("jm",))
    rule = session.scalar(select(AlertRule))
    assert rule is not None
    assert service.create_first_seen_observation_event(request(rule.id)) is not None
    assert service.create_first_seen_observation_event(
        request(rule.id, contract="JM2611", result_codes=("sell",))
    ) is None
    stored = session.scalar(select(AlertEvent))
    assert stored is not None
    assert stored.contract == "JM2609"
    assert stored.result_codes == ["buy"]


def test_first_seen_duplicate_rejects_a_corrupt_stored_event(session: Session) -> None:
    service = AlertService(session, operational_products=("jm",))
    rule = session.scalar(select(AlertRule))
    assert rule is not None
    assert service.create_first_seen_observation_event(request(rule.id)) is not None
    stored = session.scalar(select(AlertEvent))
    assert stored is not None
    stored.contract = "CORRUPT"
    session.commit()

    with pytest.raises(AlertConsistencyError):
        service.create_first_seen_observation_event(request(rule.id))


@pytest.mark.parametrize("result_codes", [(), ("hold",), ("buy", "buy")])
def test_result_codes_are_strict(session: Session, result_codes: tuple[str, ...]) -> None:
    rule = session.scalar(select(AlertRule))
    assert rule is not None
    with pytest.raises(AlertScopeError, match="ALERT_RESULT_CODES_INVALID"):
        AlertService(session, operational_products=("jm",)).create_event(
            request(rule.id, result_codes=result_codes)
        )


def test_current_events_are_product_and_trading_day_scoped(session: Session) -> None:
    service = AlertService(session, operational_products=("jm",))
    rule = session.scalar(select(AlertRule))
    assert rule is not None
    assert service.create_event(request(rule.id)) is not None
    assert len(service.list_current_product_events(
        symbol="jm", trading_day=TRADING_DAY
    )) == 1
    assert service.list_current_product_events(
        symbol="jm", trading_day=date(2026, 8, 16)
    ) == ()


def test_global_current_events_keep_unknown_rules_for_api_fail_closed_validation(session: Session) -> None:
    service = AlertService(session, operational_products=("jm",))
    active_rule = session.scalar(select(AlertRule).where(AlertRule.rule_code == "htdy_original_15m"))
    assert active_rule is not None
    legacy_rule = AlertRule(
        rule_code="retired_rule",
        enabled=True,
        scope_product_frequencies={},
    )
    session.add(legacy_rule)
    session.flush()
    session.add_all(
        [
            AlertEvent(
                rule_id=active_rule.id,
                symbol="jm",
                contract="JM2609",
                trading_day=TRADING_DAY,
                frequency="15m",
                bar_end=BAR_END,
                result_codes=["buy"],
                detected_at=BAR_END + timedelta(seconds=5),
                notification_attempted_at=None,
            ),
            AlertEvent(
                rule_id=active_rule.id,
                symbol="jm",
                contract="JM2609",
                trading_day=TRADING_DAY,
                frequency="5m",
                bar_end=BAR_END + timedelta(minutes=5),
                result_codes=["sell"],
                detected_at=BAR_END + timedelta(seconds=5),
                notification_attempted_at=None,
            ),
            AlertEvent(
                rule_id=active_rule.id,
                symbol="jm",
                contract="JM2609",
                trading_day=TRADING_DAY,
                frequency="30m",
                bar_end=BAR_END + timedelta(minutes=10),
                result_codes=["buy"],
                detected_at=BAR_END + timedelta(seconds=10),
                notification_attempted_at=None,
            ),
            AlertEvent(
                rule_id=legacy_rule.id,
                symbol="jm",
                contract="JM2609",
                trading_day=TRADING_DAY,
                frequency="60m",
                bar_end=BAR_END + timedelta(minutes=15),
                result_codes=["buy"],
                detected_at=BAR_END + timedelta(seconds=20),
                notification_attempted_at=None,
            ),
            AlertEvent(
                rule_id=active_rule.id,
                symbol="jm",
                contract="JM2609",
                trading_day=date(2026, 8, 14),
                frequency="1m",
                bar_end=BAR_END + timedelta(minutes=20),
                result_codes=["buy"],
                detected_at=BAR_END + timedelta(seconds=30),
                notification_attempted_at=None,
            ),
        ]
    )
    session.commit()

    events = service.list_current_events(trading_day=TRADING_DAY, limit=2)

    assert [event.frequency for event in events] == ["60m", "30m"]


def request(
    rule_id: int,
    *,
    contract: str = "JM2609",
    result_codes: tuple[str, ...] = ("buy",),
) -> AlertEventCreate:
    return AlertEventCreate(
        rule_id=rule_id,
        symbol="jm",
        contract=contract,
        trading_day=TRADING_DAY,
        frequency="15m",
        bar_end=BAR_END,
        result_codes=result_codes,
        detected_at=BAR_END + timedelta(seconds=1),
        notification_attempted_at=BAR_END + timedelta(seconds=2),
    )
