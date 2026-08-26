from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Callable, cast

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.alerts.models import AlertEvent, AlertRule
from app.market_data.domain import BarFrequency, CanonicalBar
from app.market_data.subing_lifecycle import ConfirmationSource
from app.market_data.subing_strategy.contracts import (
    SubingStrategyAction,
    SubingStrategyActionKind,
    SubingStrategyEpisode,
    SubingStrategyFillBasis,
    subing_strategy_action_id,
    subing_strategy_episode_id,
)
from app.market_data.subing_structure import (
    ConfirmedPivot,
    PivotKind,
    _canonical_pivot_id,
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
                scope_product_frequencies={symbol: ["15m"] for symbol in htdy_scope},
            ),
            AlertRule(
                rule_code="subing_strategy_v1",
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
        action_id=None,
        strategy_payload=None,
        detected_at=bar_end + timedelta(seconds=1),
        notification_attempted_at=bar_end + timedelta(seconds=2),
    )


def strategy_action(
    *,
    kind: SubingStrategyActionKind = SubingStrategyActionKind.OPEN_LONG,
    reference_price: Decimal = Decimal("100.00"),
    decision_at: datetime = BAR_END,
    effective_bar_end: datetime = BAR_END + timedelta(minutes=15),
    episode_id: str | None = None,
    trading_day: date = TRADING_DAY,
    segment_start_trading_day: date = TRADING_DAY,
    reason_codes: tuple[str, ...] | None = None,
    bound_reference_pivot: ConfirmedPivot | None = None,
) -> SubingStrategyAction:
    identity = {
        "strategy_id": "subing_strategy_v1",
        "formula_version": "subing_strategy_15m_v1",
        "symbol": "jm",
        "contract": "JM2609",
        "segment_start_trading_day": segment_start_trading_day.isoformat(),
        "opportunity_id": "subing-opportunity:test",
        "kind": kind.value,
        "decision_at": decision_at.isoformat(),
        "effective_bar_end": effective_bar_end.isoformat(),
        "fill_basis": SubingStrategyFillBasis.NEXT_BAR_OPEN.value,
    }
    is_open = kind in {
        SubingStrategyActionKind.OPEN_LONG,
        SubingStrategyActionKind.OPEN_SHORT,
    }
    return SubingStrategyAction(
        action_id=subing_strategy_action_id(identity),
        episode_id=(
            episode_id
            or (
                subing_strategy_episode_id(identity)
                if is_open
                else "subing-episode:test"
            )
        ),
        strategy_id="subing_strategy_v1",
        formula_version="subing_strategy_15m_v1",
        kind=kind,
        symbol="jm",
        contract="JM2609",
        trading_day=trading_day,
        segment_start_trading_day=segment_start_trading_day,
        opportunity_id="subing-opportunity:test",
        decision_at=decision_at,
        effective_open_at=effective_bar_end - timedelta(minutes=15),
        effective_bar_end=effective_bar_end,
        reference_price=reference_price,
        fill_basis=SubingStrategyFillBasis.NEXT_BAR_OPEN,
        confirmation_source=(ConfirmationSource.FORMAL_V1 if is_open else None),
        reason_codes=(() if is_open else (reason_codes or ("EMA21_BREACH_LONG",))),
        direction_context_source_day=(trading_day if is_open else None),
        direction_context_target_day=(trading_day if is_open else None),
        bound_reference_pivot=bound_reference_pivot,
    )


def strategy_request(
    rule_id: int,
    *,
    action: SubingStrategyAction | None = None,
    episode: SubingStrategyEpisode | None = None,
):
    from app.alerts.service import AlertEventCreate
    from app.alerts.strategy_payload import serialize_subing_strategy_payload

    resolved = action or strategy_action()
    return AlertEventCreate(
        rule_id=rule_id,
        symbol=resolved.symbol,
        contract=resolved.contract,
        trading_day=resolved.trading_day,
        frequency="15m",
        bar_end=resolved.decision_at,
        result_codes=(resolved.kind.value,),
        action_id=resolved.action_id,
        strategy_payload=serialize_subing_strategy_payload(resolved, episode=episode),
        detected_at=resolved.decision_at + timedelta(seconds=1),
        notification_attempted_at=resolved.decision_at + timedelta(seconds=2),
    )


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
            ("1m", "5m", "15m", "30m", "60m", "1d", "1w"),
            ("15m",),
            True,
        ),
        (
            "subing_strategy_v1",
            "苏冰策略",
            "strategy_action",
            ("1m", "5m", "15m"),
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

    enabled = service.set_product_enabled("subing_strategy_v1", " AG ", True)
    assert enabled.enabled_for_product is True
    assert seed_rule(session, "subing_strategy_v1").scope_products == ["ag"]

    disabled = service.set_product_enabled("subing_strategy_v1", "ag", False)
    disabled_again = service.set_product_enabled("subing_strategy_v1", "ag", False)
    assert disabled.enabled_for_product is False
    assert disabled_again.enabled_for_product is False
    assert seed_rule(session, "subing_strategy_v1").scope_products == []


def test_htdy_frequency_scope_mutations_are_normalized_and_idempotent(
    session: Session,
) -> None:
    from app.alerts.service import AlertService

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
        service.set_product_frequency_enabled("subing_strategy_v1", "jm", "15m", True)


def test_htdy_frequency_scope_rejects_non_input_frequency(session: Session) -> None:
    from app.alerts.service import AlertScopeError, AlertService

    with pytest.raises(AlertScopeError, match="^ALERT_SCOPE_FREQUENCY_INVALID$"):
        AlertService(
            session, operational_products=("jm",)
        ).set_product_frequency_enabled("htdy_original_15m", "jm", "4h", True)


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
    subing = seed_rule(session, "subing_strategy_v1")
    subing.scope_product_frequencies = {"jm": ["15m"]}
    session.commit()

    with pytest.raises(AlertScopeError, match="^ALERT_SCOPE_STATE_INVALID$"):
        service.set_product_enabled("subing_strategy_v1", "jm", True)


@pytest.mark.parametrize(
    "stored_scope",
    [
        [],
        {"JM": ["15m"]},
        {"ag": ["15m"]},
        {"jm": "15m"},
        {"jm": []},
        {"jm": ["4h"]},
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
            "subing_strategy_v1", "ag", True
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
        AlertService(
            session, operational_products=("jm",)
        ).set_product_frequency_enabled("htdy_original_15m", "jm", "15m", True)
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
            "subing_strategy_v1", "jm", True
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
    subing = seed_rule(session, "subing_strategy_v1")
    subing.scope_products = ["jm"]
    session.commit()

    assert service.rule_allows_event(htdy, symbol=" JM ", frequency="15m") is True
    assert service.rule_allows_event(htdy, symbol="jm", frequency="5m") is False
    assert service.rule_allows_event(subing, symbol="jm", frequency="1m") is False
    assert service.rule_allows_event(subing, symbol="jm", frequency="5m") is False
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
        service.set_product_enabled("subing_strategy_v1", "ag", True)
    with pytest.raises(AlertRuleNotFoundError, match="ALERT_RULE_NOT_FOUND"):
        service.set_product_enabled("not_a_rule", "jm", True)


def test_create_htdy_event_normalizes_result_order_and_duplicate_is_idempotent(
    session: Session,
) -> None:
    from app.alerts.service import AlertService

    rule = seed_rule(session, "htdy_original_15m")
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
    assert created.action_id is None
    assert created.strategy_payload is None
    assert created.detected_at == (BAR_END + timedelta(seconds=1)).replace(tzinfo=None)
    assert created.notification_attempted_at == (
        BAR_END + timedelta(seconds=2)
    ).replace(tzinfo=None)
    assert duplicate is None
    assert len(session.scalars(select(AlertEvent)).all()) == 1


@pytest.mark.parametrize(
    ("changed_field", "changed_value"),
    [
        ("contract", "JM2610"),
        ("trading_day", date(2026, 8, 14)),
        ("result_codes", ("sell",)),
        ("action_id", "subing-action:not-allowed"),
        ("strategy_payload", {"kind": "open_long"}),
    ],
)
def test_duplicate_htdy_event_with_changed_facts_fails_closed(
    session: Session,
    changed_field: str,
    changed_value: object,
) -> None:
    from app.alerts.service import AlertConsistencyError, AlertService

    rule = seed_rule(session, "htdy_original_15m")
    service = AlertService(session, operational_products=("jm",))
    request = event_request(rule.id)
    service.create_event(request)

    with pytest.raises(AlertConsistencyError, match="ALERT_EVENT_CONSISTENCY_ERROR"):
        service.create_event(replace(request, **{changed_field: changed_value}))


def test_strategy_payload_round_trips_exact_open_contract() -> None:
    from app.alerts.strategy_payload import (
        parse_subing_strategy_payload,
        serialize_subing_strategy_payload,
    )

    payload = serialize_subing_strategy_payload(strategy_action())

    assert payload.to_json() == {
        "schema_version": 1,
        "strategy_id": "subing_strategy_v1",
        "formula_version": "subing_strategy_15m_v1",
        "action_id": strategy_action().action_id,
        "episode_id": strategy_action().episode_id,
        "kind": "open_long",
        "symbol": "jm",
        "contract": "JM2609",
        "trading_day": "2026-08-15",
        "segment_start_trading_day": "2026-08-15",
        "opportunity_id": "subing-opportunity:test",
        "decision_at": "2026-08-14T13:15:00+00:00",
        "effective_open_at": "2026-08-14T13:15:00+00:00",
        "effective_bar_end": "2026-08-14T13:30:00+00:00",
        "reference_price": "100",
        "fill_basis": "next_bar_open",
        "confirmation_source": "formal_v1",
        "reason_codes": [],
        "direction_context_source_day": "2026-08-15",
        "direction_context_target_day": "2026-08-15",
        "bound_reference_pivot": None,
        "entry": None,
        "holding_bar_count": None,
        "reference_change_percent": None,
    }
    assert parse_subing_strategy_payload(payload.to_json()) == payload


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: {**value, "unexpected": True},
        lambda value: {key: item for key, item in value.items() if key != "kind"},
        lambda value: {**value, "reference_price": 100.0},
        lambda value: {
            **value,
            "effective_bar_end": "2026-08-14T21:30:00+08:00",
        },
    ],
)
def test_strategy_payload_rejects_non_exact_json(
    mutation: Callable[[dict[str, object]], dict[str, object]],
) -> None:
    from app.alerts.strategy_payload import (
        StrategyPayloadError,
        parse_subing_strategy_payload,
        serialize_subing_strategy_payload,
    )

    raw = serialize_subing_strategy_payload(strategy_action()).to_json()
    changed = mutation(raw)

    with pytest.raises(StrategyPayloadError, match="SUBING_STRATEGY_PAYLOAD_INVALID"):
        parse_subing_strategy_payload(changed)


def _bar(bar_end: datetime, close: str) -> CanonicalBar:
    price = Decimal(close)
    return CanonicalBar(
        bar_end=bar_end,
        trading_day=TRADING_DAY,
        open=price,
        high=price,
        low=price,
        close=price,
        volume=Decimal("1"),
        turnover=None,
        open_interest=None,
    )


def closed_strategy_episode(
    *,
    reason_codes: tuple[str, ...] = ("EMA21_BREACH_LONG",),
) -> tuple[SubingStrategyAction, SubingStrategyEpisode]:
    entry = strategy_action()
    exit_action = strategy_action(
        kind=SubingStrategyActionKind.CLOSE_LONG,
        reference_price=Decimal("105"),
        decision_at=BAR_END + timedelta(minutes=30),
        effective_bar_end=BAR_END + timedelta(minutes=45),
        episode_id=entry.episode_id,
        reason_codes=reason_codes,
    )
    episode = SubingStrategyEpisode.from_actions(
        entry_action=entry,
        exit_action=exit_action,
        completed_15m_bars=(
            _bar(BAR_END + timedelta(minutes=15), "100"),
            _bar(BAR_END + timedelta(minutes=30), "104"),
            _bar(BAR_END + timedelta(minutes=45), "105"),
        ),
        latest_reference_price=None,
    )
    return exit_action, episode


def closed_short_strategy_episode(
    *, reason_codes: tuple[str, ...]
) -> tuple[SubingStrategyAction, SubingStrategyEpisode]:
    entry = strategy_action(kind=SubingStrategyActionKind.OPEN_SHORT)
    exit_action = strategy_action(
        kind=SubingStrategyActionKind.CLOSE_SHORT,
        reference_price=Decimal("95"),
        decision_at=BAR_END + timedelta(minutes=30),
        effective_bar_end=BAR_END + timedelta(minutes=45),
        episode_id=entry.episode_id,
        reason_codes=reason_codes,
    )
    episode = SubingStrategyEpisode.from_actions(
        entry_action=entry,
        exit_action=exit_action,
        completed_15m_bars=(
            _bar(BAR_END + timedelta(minutes=15), "100"),
            _bar(BAR_END + timedelta(minutes=30), "96"),
            _bar(BAR_END + timedelta(minutes=45), "95"),
        ),
        latest_reference_price=None,
    )
    return exit_action, episode


def test_strategy_payload_close_uses_episode_facts_without_recomputation() -> None:
    from app.alerts.strategy_payload import serialize_subing_strategy_payload

    action, episode = closed_strategy_episode()
    raw = serialize_subing_strategy_payload(action, episode=episode).to_json()

    assert raw["entry"] == {
        "action_id": episode.entry_action.action_id,
        "kind": "open_long",
        "effective_bar_end": "2026-08-14T13:30:00+00:00",
        "reference_price": "100",
        "confirmation_source": "formal_v1",
    }
    assert raw["holding_bar_count"] == 2
    assert raw["reference_change_percent"] == "5"
    assert raw["reason_codes"] == ["EMA21_BREACH_LONG"]


def test_close_payload_rejects_exit_that_changes_entry_bound_pivot() -> None:
    from app.alerts.strategy_payload import (
        StrategyPayloadError,
        serialize_subing_strategy_payload,
    )

    entry = strategy_action(bound_reference_pivot=_pivot("JM2609"))
    exit_action = strategy_action(
        kind=SubingStrategyActionKind.CLOSE_LONG,
        reference_price=Decimal("105"),
        decision_at=BAR_END + timedelta(minutes=30),
        effective_bar_end=BAR_END + timedelta(minutes=45),
        episode_id=entry.episode_id,
        bound_reference_pivot=None,
    )
    episode = SubingStrategyEpisode.from_actions(
        entry_action=entry,
        exit_action=exit_action,
        completed_15m_bars=(
            _bar(BAR_END + timedelta(minutes=15), "100"),
            _bar(BAR_END + timedelta(minutes=30), "104"),
            _bar(BAR_END + timedelta(minutes=45), "105"),
        ),
        latest_reference_price=None,
    )

    with pytest.raises(StrategyPayloadError, match="SUBING_STRATEGY_PAYLOAD_INVALID"):
        serialize_subing_strategy_payload(exit_action, episode=episode)


def _pivot(
    contract: str,
    *,
    kind: PivotKind = PivotKind.LOW,
) -> ConfirmedPivot:
    pivot_time = BAR_END - timedelta(minutes=30)
    return ConfirmedPivot(
        pivot_id=_canonical_pivot_id(
            contract=contract,
            segment_start_trading_day=TRADING_DAY,
            source_timeframe=BarFrequency.M5,
            kind=kind,
            pivot_time=pivot_time,
        ),
        kind=kind,
        source_timeframe=BarFrequency.M5,
        pivot_time=pivot_time,
        confirmed_at=BAR_END - timedelta(minutes=15),
        price=Decimal("98"),
        contract=contract,
        segment_start_trading_day=TRADING_DAY,
    )


@pytest.mark.parametrize(
    ("kind", "wrong_pivot_kind"),
    (
        (SubingStrategyActionKind.OPEN_LONG, PivotKind.HIGH),
        (SubingStrategyActionKind.OPEN_SHORT, PivotKind.LOW),
    ),
)
def test_open_payload_rejects_bound_pivot_from_opposite_position_side(
    kind: SubingStrategyActionKind,
    wrong_pivot_kind: PivotKind,
) -> None:
    from app.alerts.strategy_payload import (
        StrategyPayloadError,
        parse_subing_strategy_payload,
        serialize_subing_strategy_payload,
    )

    expected_pivot_kind = (
        PivotKind.LOW if kind is SubingStrategyActionKind.OPEN_LONG else PivotKind.HIGH
    )
    accepted = serialize_subing_strategy_payload(
        strategy_action(
            kind=kind,
            bound_reference_pivot=_pivot("JM2609", kind=expected_pivot_kind),
        )
    ).to_json()
    donor_kind = (
        SubingStrategyActionKind.OPEN_SHORT
        if kind is SubingStrategyActionKind.OPEN_LONG
        else SubingStrategyActionKind.OPEN_LONG
    )
    wrong_pivot = serialize_subing_strategy_payload(
        strategy_action(
            kind=donor_kind,
            bound_reference_pivot=_pivot("JM2609", kind=wrong_pivot_kind),
        )
    ).to_json()["bound_reference_pivot"]

    with pytest.raises(StrategyPayloadError, match="SUBING_STRATEGY_PAYLOAD_INVALID"):
        parse_subing_strategy_payload(
            {**accepted, "bound_reference_pivot": wrong_pivot}
        )


def test_serializer_rejects_core_open_action_with_opposite_side_pivot() -> None:
    from app.alerts.strategy_payload import (
        StrategyPayloadError,
        serialize_subing_strategy_payload,
    )

    action = strategy_action(
        kind=SubingStrategyActionKind.OPEN_LONG,
        bound_reference_pivot=_pivot("JM2609", kind=PivotKind.HIGH),
    )

    with pytest.raises(StrategyPayloadError, match="SUBING_STRATEGY_PAYLOAD_INVALID"):
        serialize_subing_strategy_payload(action)


@pytest.mark.parametrize(
    ("entry_kind", "close_kind", "wrong_pivot_kind", "reason_codes"),
    (
        (
            SubingStrategyActionKind.OPEN_LONG,
            SubingStrategyActionKind.CLOSE_LONG,
            PivotKind.HIGH,
            ("EMA21_BREACH_LONG",),
        ),
        (
            SubingStrategyActionKind.OPEN_SHORT,
            SubingStrategyActionKind.CLOSE_SHORT,
            PivotKind.LOW,
            ("EMA21_BREACH_SHORT",),
        ),
    ),
)
def test_close_payload_rejects_inherited_pivot_from_opposite_position_side(
    entry_kind: SubingStrategyActionKind,
    close_kind: SubingStrategyActionKind,
    wrong_pivot_kind: PivotKind,
    reason_codes: tuple[str, ...],
) -> None:
    from app.alerts.strategy_payload import (
        StrategyPayloadError,
        serialize_subing_strategy_payload,
    )

    pivot = _pivot("JM2609", kind=wrong_pivot_kind)
    entry = strategy_action(kind=entry_kind, bound_reference_pivot=pivot)
    exit_action = strategy_action(
        kind=close_kind,
        reference_price=Decimal("95"),
        decision_at=BAR_END + timedelta(minutes=30),
        effective_bar_end=BAR_END + timedelta(minutes=45),
        episode_id=entry.episode_id,
        reason_codes=reason_codes,
        bound_reference_pivot=pivot,
    )
    episode = SubingStrategyEpisode.from_actions(
        entry_action=entry,
        exit_action=exit_action,
        completed_15m_bars=(
            _bar(BAR_END + timedelta(minutes=15), "100"),
            _bar(BAR_END + timedelta(minutes=30), "96"),
            _bar(BAR_END + timedelta(minutes=45), "95"),
        ),
        latest_reference_price=None,
    )

    with pytest.raises(StrategyPayloadError, match="SUBING_STRATEGY_PAYLOAD_INVALID"):
        serialize_subing_strategy_payload(exit_action, episode=episode)


def test_payload_rejects_valid_pivot_from_another_contract() -> None:
    from app.alerts.strategy_payload import (
        StrategyPayloadError,
        parse_subing_strategy_payload,
        serialize_subing_strategy_payload,
    )

    raw = serialize_subing_strategy_payload(
        strategy_action(bound_reference_pivot=_pivot("JM2609"))
    ).to_json()
    pivot = _pivot("RB2610")
    other_pivot = {
        "pivot_id": pivot.pivot_id,
        "kind": "low",
        "source_timeframe": "5m",
        "pivot_time": "2026-08-14T12:45:00+00:00",
        "confirmed_at": "2026-08-14T13:00:00+00:00",
        "price": "98",
        "contract": "RB2610",
        "segment_start_trading_day": "2026-08-15",
    }

    with pytest.raises(StrategyPayloadError, match="SUBING_STRATEGY_PAYLOAD_INVALID"):
        parse_subing_strategy_payload({**raw, "bound_reference_pivot": other_pivot})


def test_close_short_payload_accepts_only_short_direction_reasons() -> None:
    from app.alerts.strategy_payload import (
        StrategyPayloadError,
        serialize_subing_strategy_payload,
    )

    accepted_action, accepted_episode = closed_short_strategy_episode(
        reason_codes=("EMA21_BREACH_SHORT", "MACD_LOW_GOLDEN_CROSS")
    )
    payload = serialize_subing_strategy_payload(
        accepted_action, episode=accepted_episode
    )
    assert payload.kind is SubingStrategyActionKind.CLOSE_SHORT
    assert payload.reason_codes == (
        "EMA21_BREACH_SHORT",
        "MACD_LOW_GOLDEN_CROSS",
    )

    wrong_action, wrong_episode = closed_short_strategy_episode(
        reason_codes=("EMA21_BREACH_LONG",)
    )
    with pytest.raises(StrategyPayloadError, match="SUBING_STRATEGY_PAYLOAD_INVALID"):
        serialize_subing_strategy_payload(wrong_action, episode=wrong_episode)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: {
            **raw,
            "entry": {**raw["entry"], "action_id": "not-an-action-id"},
        },
        lambda raw: {**raw, "reason_codes": ["UNKNOWN_EXIT_REASON"]},
    ],
)
def test_close_payload_rejects_untrusted_entry_ids_and_reason_codes(
    mutate: Callable[[dict[str, object]], dict[str, object]],
) -> None:
    from app.alerts.strategy_payload import (
        StrategyPayloadError,
        parse_subing_strategy_payload,
        serialize_subing_strategy_payload,
    )

    action, episode = closed_strategy_episode()
    raw = serialize_subing_strategy_payload(action, episode=episode).to_json()

    with pytest.raises(StrategyPayloadError, match="SUBING_STRATEGY_PAYLOAD_INVALID"):
        parse_subing_strategy_payload(mutate(raw))


def test_close_payload_requires_entry_and_episode_to_share_identity_digest() -> None:
    from app.alerts.strategy_payload import (
        StrategyPayloadError,
        parse_subing_strategy_payload,
        serialize_subing_strategy_payload,
    )

    action, episode = closed_strategy_episode()
    raw = serialize_subing_strategy_payload(action, episode=episode).to_json()
    entry = cast(dict[str, object], raw["entry"])
    mismatched_entry = {
        **entry,
        "action_id": f"subing-action:{'0' * 64}",
    }

    with pytest.raises(StrategyPayloadError, match="SUBING_STRATEGY_PAYLOAD_INVALID"):
        parse_subing_strategy_payload({**raw, "entry": mismatched_entry})


def test_close_payload_rejects_noncanonical_policy_reason_order() -> None:
    from app.alerts.strategy_payload import (
        StrategyPayloadError,
        parse_subing_strategy_payload,
        serialize_subing_strategy_payload,
    )

    action, episode = closed_strategy_episode(
        reason_codes=("EMA21_BREACH_LONG", "MACD_HIGH_DEAD_CROSS")
    )
    raw = serialize_subing_strategy_payload(action, episode=episode).to_json()

    with pytest.raises(StrategyPayloadError, match="SUBING_STRATEGY_PAYLOAD_INVALID"):
        parse_subing_strategy_payload(
            {
                **raw,
                "reason_codes": ["MACD_HIGH_DEAD_CROSS", "EMA21_BREACH_LONG"],
            }
        )


def test_create_strategy_event_is_action_id_idempotent_and_conflict_safe(
    session: Session,
) -> None:
    from app.alerts.service import AlertConsistencyError, AlertService

    rule = seed_rule(session, "subing_strategy_v1")
    action = strategy_action()
    service = AlertService(session, operational_products=("jm",))
    request = strategy_request(rule.id, action=action)

    created = service.create_event(request)
    duplicate = service.create_event(request)

    assert created is not None
    assert created.action_id == action.action_id
    assert created.result_codes == ["open_long"]
    assert created.strategy_payload == request.strategy_payload.to_json()
    assert duplicate is None

    changed_action = strategy_action(reference_price=Decimal("101"))
    assert changed_action.action_id == action.action_id
    with pytest.raises(AlertConsistencyError, match="ALERT_EVENT_CONSISTENCY_ERROR"):
        service.create_event(strategy_request(rule.id, action=changed_action))


def test_strategy_action_id_owned_by_another_rule_is_a_conflict(
    session: Session,
) -> None:
    from app.alerts.service import AlertConsistencyError, AlertService

    strategy_rule = seed_rule(session, "subing_strategy_v1")
    rogue_rule = AlertRule(
        rule_code="rogue_rule",
        enabled=False,
        scope_products=[],
        scope_product_frequencies={},
    )
    session.add(rogue_rule)
    session.flush()
    request = strategy_request(strategy_rule.id)
    assert request.strategy_payload is not None
    session.add(
        AlertEvent(
            rule_id=rogue_rule.id,
            symbol=request.symbol,
            contract=request.contract,
            trading_day=request.trading_day,
            frequency=request.frequency,
            bar_end=request.bar_end,
            result_codes=list(request.result_codes),
            action_id=request.action_id,
            strategy_payload=request.strategy_payload.to_json(),
            detected_at=request.detected_at,
            notification_attempted_at=request.notification_attempted_at,
        )
    )
    session.commit()

    with pytest.raises(AlertConsistencyError, match="ALERT_EVENT_CONSISTENCY_ERROR"):
        AlertService(session, operational_products=("jm",)).create_event(request)


@pytest.mark.parametrize(
    "request_change",
    [
        {"frequency": "5m"},
        {"result_codes": ("buy",)},
        {"action_id": None},
        {"strategy_payload": None},
    ],
)
def test_strategy_event_rejects_rule_specific_contract_mismatch(
    session: Session,
    request_change: dict[str, object],
) -> None:
    from app.alerts.service import AlertConsistencyError, AlertService

    rule = seed_rule(session, "subing_strategy_v1")
    request = strategy_request(rule.id)

    with pytest.raises(AlertConsistencyError, match="ALERT_EVENT_CONSISTENCY_ERROR"):
        AlertService(session, operational_products=("jm",)).create_event(
            replace(request, **request_change)
        )


@pytest.mark.parametrize(
    "payload_change",
    [
        {"schema_version": 2},
        {"reason_codes": ("EMA21_BREACH_LONG",)},
    ],
)
def test_strategy_event_revalidates_typed_payload_before_persisting(
    session: Session,
    payload_change: dict[str, object],
) -> None:
    from app.alerts.service import AlertConsistencyError, AlertService

    rule = seed_rule(session, "subing_strategy_v1")
    request = strategy_request(rule.id)
    assert request.strategy_payload is not None
    bypassed = replace(request.strategy_payload, **payload_change)

    with pytest.raises(AlertConsistencyError, match="ALERT_EVENT_CONSISTENCY_ERROR"):
        AlertService(session, operational_products=("jm",)).create_event(
            replace(request, strategy_payload=bypassed)
        )

    assert (
        session.scalar(select(AlertEvent).where(AlertEvent.rule_id == rule.id)) is None
    )


def test_integrity_error_without_action_id_readback_is_persistence_failure(
    session: Session,
) -> None:
    from app.alerts.service import AlertEventPersistenceError, AlertService

    rule = seed_rule(session, "subing_strategy_v1")

    def fail_commit(_: Session) -> None:
        raise IntegrityError("INSERT", {}, RuntimeError("constraint detail"))

    event.listen(session, "before_commit", fail_commit, once=True)

    with pytest.raises(AlertEventPersistenceError, match="ALERT_EVENT_PERSIST_FAILED"):
        AlertService(session, operational_products=("jm",)).create_event(
            strategy_request(rule.id)
        )

    assert session.in_transaction() is False
    assert (
        session.scalar(select(AlertEvent).where(AlertEvent.rule_id == rule.id)) is None
    )


def test_sqlalchemy_error_is_stable_event_persistence_failure(
    session: Session,
) -> None:
    from app.alerts.service import AlertEventPersistenceError, AlertService

    rule = seed_rule(session, "subing_strategy_v1")

    def fail_commit(_: Session) -> None:
        raise SQLAlchemyError("schema drift detail")

    event.listen(session, "before_commit", fail_commit, once=True)

    with pytest.raises(AlertEventPersistenceError, match="ALERT_EVENT_PERSIST_FAILED"):
        AlertService(session, operational_products=("jm",)).create_event(
            strategy_request(rule.id)
        )

    assert session.in_transaction() is False


def test_htdy_same_time_cross_frequency_events_coexist_and_same_frequency_is_idempotent(
    session: Session,
) -> None:
    from app.alerts.service import AlertService

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
        service.create_event(event_request(htdy.id, frequency="4h"))
    with pytest.raises(AlertScopeError, match="ALERT_TRADING_DAY_REQUIRED"):
        service.create_event(event_request(htdy.id, trading_day=cast(date, None)))


def test_current_strategy_events_filter_rule_and_day_and_order_descending(
    session: Session,
) -> None:
    from app.alerts.service import AlertService

    htdy = seed_rule(session, "htdy_original_15m")
    subing = seed_rule(session, "subing_strategy_v1")
    service = AlertService(session, operational_products=("jm", "rb"))
    service.create_event(
        event_request(htdy.id, bar_end=BAR_END + timedelta(minutes=30))
    )
    service.create_event(
        strategy_request(
            subing.id,
            action=strategy_action(
                decision_at=BAR_END + timedelta(minutes=15),
                effective_bar_end=BAR_END + timedelta(minutes=30),
            ),
        )
    )
    service.create_event(
        strategy_request(
            subing.id,
            action=strategy_action(
                decision_at=BAR_END + timedelta(minutes=45),
                effective_bar_end=BAR_END + timedelta(minutes=60),
            ),
        )
    )
    service.create_event(
        strategy_request(
            subing.id,
            action=strategy_action(
                decision_at=BAR_END + timedelta(minutes=60),
                effective_bar_end=BAR_END + timedelta(minutes=75),
                trading_day=date(2026, 8, 14),
                segment_start_trading_day=date(2026, 8, 14),
            ),
        )
    )

    events = service.list_current_strategy_action_events(trading_day=TRADING_DAY)

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
    subing = seed_rule(session, "subing_strategy_v1")
    service = AlertService(session, operational_products=("jm", "rb"))
    service.create_event(
        event_request(htdy.id, bar_end=BAR_END + timedelta(minutes=15))
    )
    service.create_event(
        strategy_request(
            subing.id,
            action=strategy_action(
                decision_at=BAR_END + timedelta(minutes=45),
                effective_bar_end=BAR_END + timedelta(minutes=60),
            ),
        )
    )
    service.create_event(
        event_request(
            htdy.id,
            symbol="rb",
            contract="RB2610",
            bar_end=BAR_END + timedelta(minutes=60),
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
    subing = seed_rule(session, "subing_strategy_v1")
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
            action_id=None,
            strategy_payload=None,
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
        strategy_request(
            subing.id,
            action=strategy_action(
                decision_at=BAR_END + timedelta(minutes=45),
                effective_bar_end=BAR_END + timedelta(minutes=60),
            ),
        )
    )

    events = service.list_current_product_events(
        symbol="jm",
        trading_day=TRADING_DAY,
    )

    assert [item.rule.rule_code for item in events] == [
        "subing_strategy_v1",
        "htdy_original_15m",
    ]
    assert [item.bar_end.replace(tzinfo=UTC) for item in events] == [
        BAR_END + timedelta(minutes=45),
        BAR_END + timedelta(minutes=15),
    ]


def test_current_day_reads_exclude_legacy_null_trading_day(session: Session) -> None:
    from app.alerts.service import AlertService

    subing = seed_rule(session, "subing_strategy_v1")
    session.add(
        AlertEvent(
            rule_id=subing.id,
            symbol="jm",
            contract="JM2609",
            trading_day=None,
            frequency="15m",
            bar_end=BAR_END,
            result_codes=["open_long"],
            action_id="subing-action:legacy-null-day",
            strategy_payload={},
            detected_at=BAR_END,
            notification_attempted_at=BAR_END,
        )
    )
    session.commit()
    service = AlertService(session, operational_products=("jm",))

    assert service.list_current_strategy_action_events(trading_day=TRADING_DAY) == ()
    assert (
        service.list_current_product_events(symbol="jm", trading_day=TRADING_DAY) == ()
    )
