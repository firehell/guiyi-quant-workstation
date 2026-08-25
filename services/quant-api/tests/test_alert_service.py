from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import cast

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.alerts.models import AlertEvent, AlertRule


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
    with Session(engine) as session:
        seed_v2_rules(session, htdy_scope=["jm"], subing_scope=[])
        yield session
    engine.dispose()


def seed_v2_rules(
    session: Session,
    *,
    htdy_scope: list[str],
    subing_scope: list[str],
) -> None:
    session.add_all(
        [
            AlertRule(
                rule_code="htdy_original_15m",
                enabled=True,
                scope_products=[],
                scope_product_frequencies={
                    symbol: ["15m"] for symbol in htdy_scope
                },
            ),
            AlertRule(
                rule_code="subing_entry_signal_v1",
                enabled=True,
                scope_products=subing_scope,
                scope_product_frequencies={},
            ),
        ]
    )
    session.commit()


def seed_rule(session: Session, rule_code: str) -> AlertRule:
    rule = session.scalar(select(AlertRule).where(AlertRule.rule_code == rule_code))
    assert rule is not None
    return rule


def event_request(
    rule_id: int,
    *,
    symbol: str = "jm",
    contract: str = "JM2609",
    trading_day: date = TRADING_DAY,
    frequency: str = "15m",
    bar_end: datetime = BAR_END,
    result_codes: tuple[str, ...] = ("sell", "buy"),
    lower_tf_confirmation: bool = False,
):
    from app.alerts.service import AlertEventCreate

    return AlertEventCreate(
        rule_id=rule_id,
        symbol=symbol,
        contract=contract,
        trading_day=trading_day,
        frequency=frequency,
        bar_end=bar_end,
        result_codes=result_codes,
        lower_tf_confirmation=lower_tf_confirmation,
        detected_at=bar_end + timedelta(seconds=1),
        notification_attempted_at=bar_end + timedelta(seconds=2),
    )


def widen_htdy_test_frequencies(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.alerts.service as service_module

    original_definition = service_module._definition
    htdy_definition = replace(
        original_definition("htdy_original_15m"),
        input_frequencies=("1m", "5m", "15m", "30m", "60m", "1d", "1w"),
    )

    def definition(rule_code: str):
        if rule_code == "htdy_original_15m":
            return htdy_definition
        return original_definition(rule_code)

    monkeypatch.setattr(service_module, "_definition", definition)


def test_product_rules_exposes_registry_metadata_and_independent_scopes(
    session: Session,
) -> None:
    from app.alerts.service import AlertService

    states = AlertService(session, operational_products=("jm",)).product_rules("jm")

    assert [
        (
            state.rule_code,
            state.display_name,
            state.kind,
            state.input_frequencies,
            state.enabled_frequencies,
            state.enabled_for_product,
        )
        for state in states
    ] == [
        (
            "htdy_original_15m",
            "火天大有",
            "indicator_observation",
            ("15m",),
            ("15m",),
            True,
        ),
        (
            "subing_entry_signal_v1",
            "苏冰入场信号",
            "formal_signal",
            ("5m", "15m"),
            (),
            False,
        ),
    ]


def test_product_rules_rejects_database_rule_missing_from_registry(
    session: Session,
) -> None:
    from app.alerts.service import AlertRuleNotFoundError, AlertService

    session.add(
        AlertRule(
            rule_code="unknown_rule",
            enabled=True,
            scope_products=[],
            scope_product_frequencies={},
        )
    )
    session.commit()

    with pytest.raises(AlertRuleNotFoundError, match="ALERT_RULE_NOT_FOUND"):
        AlertService(session, operational_products=("jm",)).product_rules("jm")


def test_scope_add_normalizes_and_remove_is_idempotent(session: Session) -> None:
    from app.alerts.service import AlertService

    service = AlertService(session, operational_products=("ag", "jm"))

    enabled = service.set_product_enabled("subing_entry_signal_v1", " AG ", True)
    assert enabled.enabled_for_product is True
    assert seed_rule(session, "subing_entry_signal_v1").scope_products == ["ag"]

    disabled = service.set_product_enabled("subing_entry_signal_v1", "ag", False)
    disabled_again = service.set_product_enabled("subing_entry_signal_v1", "ag", False)
    assert disabled.enabled_for_product is False
    assert disabled_again.enabled_for_product is False
    assert seed_rule(session, "subing_entry_signal_v1").scope_products == []


def test_htdy_frequency_scope_mutations_are_normalized_and_idempotent(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.alerts.service import AlertService

    widen_htdy_test_frequencies(monkeypatch)
    htdy = seed_rule(session, "htdy_original_15m")
    htdy.scope_product_frequencies = {"rb": ["60m"]}
    session.commit()
    service = AlertService(session, operational_products=("jm", "rb"))

    enabled_15m = service.set_product_frequency_enabled(
        "htdy_original_15m", " JM ", "15m", True
    )
    enabled_5m = service.set_product_frequency_enabled(
        "htdy_original_15m", "jm", " 5m ", True
    )
    enabled_5m_again = service.set_product_frequency_enabled(
        "htdy_original_15m", "jm", "5m", True
    )
    disabled_5m = service.set_product_frequency_enabled(
        "htdy_original_15m", "jm", "5m", False
    )
    disabled_5m_again = service.set_product_frequency_enabled(
        "htdy_original_15m", "jm", "5m", False
    )

    assert enabled_15m.enabled_frequencies == ("15m",)
    assert enabled_5m.enabled_frequencies == ("5m", "15m")
    assert enabled_5m_again.enabled_frequencies == ("5m", "15m")
    assert disabled_5m.enabled_frequencies == ("15m",)
    assert disabled_5m_again.enabled_frequencies == ("15m",)
    assert seed_rule(session, "htdy_original_15m").scope_product_frequencies == {
        "jm": ["15m"],
        "rb": ["60m"],
    }

    disabled_last = service.set_product_frequency_enabled(
        "htdy_original_15m", "jm", "15m", False
    )
    disabled_last_again = service.set_product_frequency_enabled(
        "htdy_original_15m", "jm", "15m", False
    )

    assert disabled_last.enabled_frequencies == ()
    assert disabled_last.enabled_for_product is False
    assert disabled_last_again.enabled_frequencies == ()
    assert seed_rule(session, "htdy_original_15m").scope_product_frequencies == {
        "rb": ["60m"]
    }


def test_scope_setters_reject_the_wrong_rule_mode(session: Session) -> None:
    from app.alerts.service import AlertScopeError, AlertService

    service = AlertService(session, operational_products=("jm",))

    with pytest.raises(AlertScopeError, match="^ALERT_SCOPE_MODE_INVALID$"):
        service.set_product_enabled("htdy_original_15m", "jm", True)
    with pytest.raises(AlertScopeError, match="^ALERT_SCOPE_MODE_INVALID$"):
        service.set_product_frequency_enabled(
            "subing_entry_signal_v1", "jm", "15m", True
        )


def test_htdy_frequency_scope_rejects_non_input_frequency(session: Session) -> None:
    from app.alerts.service import AlertScopeError, AlertService

    with pytest.raises(AlertScopeError, match="^ALERT_SCOPE_FREQUENCY_INVALID$"):
        AlertService(
            session, operational_products=("jm",)
        ).set_product_frequency_enabled("htdy_original_15m", "jm", "5m", True)


def test_scope_authorities_fail_closed_instead_of_unioning_stores(
    session: Session,
) -> None:
    from app.alerts.service import AlertScopeError, AlertService

    service = AlertService(session, operational_products=("jm",))
    htdy = seed_rule(session, "htdy_original_15m")
    htdy.scope_products = ["jm"]
    session.commit()

    with pytest.raises(AlertScopeError, match="^ALERT_SCOPE_STATE_INVALID$"):
        service.product_rules("jm")

    htdy.scope_products = []
    subing = seed_rule(session, "subing_entry_signal_v1")
    subing.scope_product_frequencies = {"jm": ["15m"]}
    session.commit()

    with pytest.raises(AlertScopeError, match="^ALERT_SCOPE_STATE_INVALID$"):
        service.set_product_enabled("subing_entry_signal_v1", "jm", True)


@pytest.mark.parametrize(
    "stored_scope",
    [
        [],
        {"JM": ["15m"]},
        {"ag": ["15m"]},
        {"jm": "15m"},
        {"jm": []},
        {"jm": ["60m"]},
    ],
)
def test_htdy_frequency_scope_rejects_invalid_stored_json(
    session: Session,
    stored_scope: object,
) -> None:
    from app.alerts.service import AlertScopeError, AlertService

    htdy = seed_rule(session, "htdy_original_15m")
    htdy.scope_product_frequencies = cast(dict[str, list[str]], stored_scope)
    session.commit()

    with pytest.raises(AlertScopeError, match="^ALERT_SCOPE_STATE_INVALID$"):
        AlertService(session, operational_products=("jm",)).product_rules("jm")


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
            "subing_entry_signal_v1", "ag", True
        )
    finally:
        event.remove(session, "do_orm_execute", capture_statement)

    assert any(
        getattr(statement, "_for_update_arg", None) is not None
        for statement in statements
    )


def test_frequency_scope_update_locks_rule_row_before_replacing_map(
    session: Session,
) -> None:
    from app.alerts.service import AlertService

    statements: list[object] = []

    def capture_statement(execute_state: object) -> None:
        statement = execute_state.statement  # type: ignore[attr-defined]
        if getattr(execute_state, "is_select", False):
            statements.append(statement)

    event.listen(session, "do_orm_execute", capture_statement)
    try:
        AlertService(session, operational_products=("jm",)).set_product_frequency_enabled(
            "htdy_original_15m", "jm", "15m", True
        )
    finally:
        event.remove(session, "do_orm_execute", capture_statement)

    assert any(
        getattr(statement, "_for_update_arg", None) is not None
        for statement in statements
    )


def test_scope_commit_failure_rolls_back_and_returns_stable_error(
    session: Session,
) -> None:
    from app.alerts.service import AlertScopeError, AlertService

    def fail_commit(_: Session) -> None:
        raise SQLAlchemyError("database detail must not escape")

    event.listen(session, "before_commit", fail_commit, once=True)

    with pytest.raises(AlertScopeError, match="ALERT_SCOPE_PERSIST_FAILED"):
        AlertService(session, operational_products=("jm",)).set_product_enabled(
            "subing_entry_signal_v1", "jm", True
        )

    assert session.in_transaction() is False


def test_frequency_scope_commit_failure_returns_stable_error(
    session: Session,
) -> None:
    from app.alerts.service import AlertScopeError, AlertService

    def fail_commit(_: Session) -> None:
        raise SQLAlchemyError("database detail must not escape")

    event.listen(session, "before_commit", fail_commit, once=True)

    with pytest.raises(AlertScopeError, match="^ALERT_SCOPE_PERSIST_FAILED$"):
        AlertService(
            session, operational_products=("jm",)
        ).set_product_frequency_enabled("htdy_original_15m", "jm", "15m", True)

    assert session.in_transaction() is False


def test_rule_allows_event_uses_only_the_rule_specific_scope_authority(
    session: Session,
) -> None:
    from app.alerts.service import AlertService

    service = AlertService(session, operational_products=("jm",))
    htdy = seed_rule(session, "htdy_original_15m")
    subing = seed_rule(session, "subing_entry_signal_v1")
    subing.scope_products = ["jm"]
    session.commit()

    assert service.rule_allows_event(htdy, symbol=" JM ", frequency="15m") is True
    assert service.rule_allows_event(htdy, symbol="jm", frequency="5m") is False
    assert service.rule_allows_event(subing, symbol="jm", frequency="5m") is True
    assert service.rule_allows_event(subing, symbol="jm", frequency="15m") is True
    assert service.rule_allows_event(subing, symbol="jm", frequency="60m") is False


def test_scope_rejects_non_operational_symbol_and_unknown_rule(
    session: Session,
) -> None:
    from app.alerts.service import (
        AlertRuleNotFoundError,
        AlertScopeError,
        AlertService,
    )

    service = AlertService(session, operational_products=("jm",))

    with pytest.raises(AlertScopeError, match="ALERT_SYMBOL_NOT_OPERATIONAL"):
        service.set_product_enabled("subing_entry_signal_v1", "ag", True)
    with pytest.raises(AlertRuleNotFoundError, match="ALERT_RULE_NOT_FOUND"):
        service.set_product_enabled("not_a_rule", "jm", True)


def test_create_event_normalizes_result_order_and_duplicate_identity_is_idempotent(
    session: Session,
) -> None:
    from app.alerts.service import AlertService

    rule = seed_rule(session, "subing_entry_signal_v1")
    request = event_request(rule.id)
    service = AlertService(session, operational_products=("jm",))

    created = service.create_event(request)
    duplicate = service.create_event(request)

    assert created is not None
    assert created.symbol == "jm"
    assert created.contract == "JM2609"
    assert created.trading_day == TRADING_DAY
    assert created.frequency == "15m"
    assert created.result_codes == ["buy", "sell"]
    assert created.lower_tf_confirmation is False
    assert created.detected_at == (BAR_END + timedelta(seconds=1)).replace(
        tzinfo=None
    )
    assert created.notification_attempted_at == (
        BAR_END + timedelta(seconds=2)
    ).replace(tzinfo=None)
    assert duplicate is None
    assert len(session.scalars(select(AlertEvent)).all()) == 1


@pytest.mark.parametrize(
    ("changed_field", "changed_value"),
    [
        ("contract", "JM2610"),
        ("frequency", "5m"),
        ("trading_day", date(2026, 8, 14)),
        ("result_codes", ("sell",)),
        ("lower_tf_confirmation", True),
    ],
)
def test_duplicate_event_with_changed_result_attributes_fails_closed(
    session: Session,
    changed_field: str,
    changed_value: object,
) -> None:
    from app.alerts.service import AlertConsistencyError, AlertService

    rule = seed_rule(session, "subing_entry_signal_v1")
    service = AlertService(session, operational_products=("jm",))
    request = event_request(rule.id)
    service.create_event(request)

    with pytest.raises(AlertConsistencyError, match="ALERT_EVENT_CONSISTENCY_ERROR"):
        service.create_event(replace(request, **{changed_field: changed_value}))


def test_htdy_same_time_cross_frequency_events_coexist_and_same_frequency_is_idempotent(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.alerts.service import AlertService

    widen_htdy_test_frequencies(monkeypatch)
    htdy = seed_rule(session, "htdy_original_15m")
    service = AlertService(session, operational_products=("jm",))
    request_15m = event_request(htdy.id, frequency="15m")
    request_60m = event_request(htdy.id, frequency="60m")

    created_60m = service.create_event(request_60m)
    created_15m = service.create_event(request_15m)
    duplicate_15m = service.create_event(request_15m)

    assert created_15m is not None
    assert created_60m is not None
    assert duplicate_15m is None
    assert [
        item.frequency
        for item in session.scalars(
            select(AlertEvent).where(AlertEvent.rule_id == htdy.id)
        ).all()
    ] == ["15m", "60m"]


def test_create_event_requires_registry_frequency_and_trading_day(
    session: Session,
) -> None:
    from app.alerts.service import AlertConsistencyError, AlertScopeError, AlertService

    htdy = seed_rule(session, "htdy_original_15m")
    service = AlertService(session, operational_products=("jm",))

    with pytest.raises(AlertConsistencyError, match="ALERT_EVENT_CONSISTENCY_ERROR"):
        service.create_event(event_request(htdy.id, frequency="5m"))
    with pytest.raises(AlertScopeError, match="ALERT_TRADING_DAY_REQUIRED"):
        service.create_event(event_request(htdy.id, trading_day=cast(date, None)))


def test_current_formal_signal_events_filters_rule_and_day_and_orders_descending(
    session: Session,
) -> None:
    from app.alerts.service import AlertService

    htdy = seed_rule(session, "htdy_original_15m")
    subing = seed_rule(session, "subing_entry_signal_v1")
    service = AlertService(session, operational_products=("jm", "rb"))
    service.create_event(
        event_request(htdy.id, bar_end=BAR_END + timedelta(minutes=30))
    )
    service.create_event(
        event_request(subing.id, bar_end=BAR_END + timedelta(minutes=15))
    )
    service.create_event(
        event_request(subing.id, bar_end=BAR_END + timedelta(minutes=45))
    )
    service.create_event(
        event_request(
            subing.id,
            trading_day=date(2026, 8, 14),
            bar_end=BAR_END + timedelta(minutes=60),
        )
    )

    events = service.list_current_formal_signal_events(trading_day=TRADING_DAY)

    assert [item.bar_end.replace(tzinfo=UTC) for item in events] == [
        BAR_END + timedelta(minutes=45),
        BAR_END + timedelta(minutes=15),
    ]
    assert {item.rule_id for item in events} == {subing.id}


def test_current_product_events_filters_symbol_and_day_and_orders_descending(
    session: Session,
) -> None:
    from app.alerts.service import AlertService

    htdy = seed_rule(session, "htdy_original_15m")
    subing = seed_rule(session, "subing_entry_signal_v1")
    service = AlertService(session, operational_products=("jm", "rb"))
    service.create_event(
        event_request(htdy.id, bar_end=BAR_END + timedelta(minutes=15))
    )
    service.create_event(
        event_request(subing.id, bar_end=BAR_END + timedelta(minutes=45))
    )
    service.create_event(
        event_request(
            subing.id,
            symbol="rb",
            contract="RB2610",
            bar_end=BAR_END + timedelta(minutes=60),
        )
    )
    service.create_event(
        event_request(
            subing.id,
            trading_day=date(2026, 8, 14),
            bar_end=BAR_END + timedelta(minutes=75),
        )
    )

    events = service.list_current_product_events(symbol=" JM ", trading_day=TRADING_DAY)

    assert [item.bar_end.replace(tzinfo=UTC) for item in events] == [
        BAR_END + timedelta(minutes=45),
        BAR_END + timedelta(minutes=15),
    ]
    assert {item.symbol for item in events} == {"jm"}


def test_current_product_events_excludes_database_rules_missing_from_registry(
    session: Session,
) -> None:
    from app.alerts.service import AlertService

    htdy = seed_rule(session, "htdy_original_15m")
    subing = seed_rule(session, "subing_entry_signal_v1")
    rogue = AlertRule(
        rule_code="rogue_rule",
        enabled=True,
        scope_products=["jm"],
        scope_product_frequencies={},
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
            bar_end=BAR_END + timedelta(minutes=60),
            result_codes=["buy"],
            lower_tf_confirmation=False,
            detected_at=BAR_END + timedelta(minutes=60, seconds=1),
            notification_attempted_at=BAR_END + timedelta(minutes=60, seconds=2),
        )
    )
    session.commit()
    service = AlertService(session, operational_products=("jm",))
    service.create_event(
        event_request(htdy.id, bar_end=BAR_END + timedelta(minutes=15))
    )
    service.create_event(
        event_request(subing.id, bar_end=BAR_END + timedelta(minutes=45))
    )

    events = service.list_current_product_events(
        symbol="jm",
        trading_day=TRADING_DAY,
    )

    assert [item.rule.rule_code for item in events] == [
        "subing_entry_signal_v1",
        "htdy_original_15m",
    ]
    assert [item.bar_end.replace(tzinfo=UTC) for item in events] == [
        BAR_END + timedelta(minutes=45),
        BAR_END + timedelta(minutes=15),
    ]


def test_current_day_reads_exclude_legacy_null_trading_day(session: Session) -> None:
    from app.alerts.service import AlertService

    subing = seed_rule(session, "subing_entry_signal_v1")
    session.add(
        AlertEvent(
            rule_id=subing.id,
            symbol="jm",
            contract="JM2609",
            trading_day=None,
            frequency="15m",
            bar_end=BAR_END,
            result_codes=["buy"],
            lower_tf_confirmation=False,
            detected_at=BAR_END,
            notification_attempted_at=BAR_END,
        )
    )
    session.commit()
    service = AlertService(session, operational_products=("jm",))

    assert service.list_current_formal_signal_events(trading_day=TRADING_DAY) == ()
    assert (
        service.list_current_product_events(symbol="jm", trading_day=TRADING_DAY) == ()
    )
