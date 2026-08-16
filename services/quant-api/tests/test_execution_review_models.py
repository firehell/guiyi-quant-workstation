from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import CheckConstraint, Index, UniqueConstraint, create_engine, event
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.alerts.models import AlertEvent, AlertRule
from app.db.base import Base
from app.execution_review.models import (
    TradeDecision,
    TradeEpisode,
    TradeExecution,
    TradeReview,
)


NOW = datetime(2026, 8, 15, 1, 0, tzinfo=UTC)


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection: object, _: object) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")  # type: ignore[attr-defined]

    Base.metadata.create_all(engine)
    with Session(engine) as value:
        yield value
    engine.dispose()


def test_execution_review_models_expose_only_the_four_application_tables() -> None:
    assert TradeDecision.__table__.name == "trade_decisions"
    assert TradeEpisode.__table__.name == "trade_episodes"
    assert TradeExecution.__table__.name == "trade_executions"
    assert TradeReview.__table__.name == "trade_reviews"
    assert {column.name for column in TradeDecision.__table__.columns} == {
        "id",
        "alert_event_id",
        "disposition",
        "first_viewed_at",
        "decided_at",
        "primary_not_execute_reason",
        "secondary_not_execute_reasons",
        "decision_note",
        "execution_reason_tags",
        "planned_stop_price",
        "stop_basis",
        "created_at",
        "updated_at",
    }
    assert {column.name for column in TradeEpisode.__table__.columns} == {
        "id",
        "origin_decision_id",
        "symbol",
        "contract",
        "direction",
        "opened_at",
        "closed_at",
        "close_reason",
        "roll_reference_exit_price",
        "roll_reference_bar_end",
        "contract_multiplier_snapshot",
        "multiplier_policy_id",
        "created_at",
        "updated_at",
    }
    assert {column.name for column in TradeExecution.__table__.columns} == {
        "id",
        "episode_id",
        "trigger_decision_id",
        "sequence_no",
        "execution_type",
        "executed_at",
        "price",
        "quantity",
        "note",
        "created_at",
        "updated_at",
    }
    assert {column.name for column in TradeReview.__table__.columns} == {
        "id",
        "episode_id",
        "signal_execution_adherence",
        "entry_tags",
        "holding_tags",
        "exit_tags",
        "market_context_tags",
        "psychology_tags",
        "summary",
        "submitted_at",
        "created_at",
        "updated_at",
    }


def test_models_use_array_json_variants_timezone_and_named_constraints() -> None:
    assert isinstance(TradeDecision.__table__.c.secondary_not_execute_reasons.type, ARRAY)
    assert isinstance(TradeDecision.__table__.c.execution_reason_tags.type, ARRAY)
    assert isinstance(TradeReview.__table__.c.entry_tags.type, ARRAY)
    timestamp_columns = (
        TradeDecision.__table__.c.first_viewed_at,
        TradeDecision.__table__.c.decided_at,
        TradeEpisode.__table__.c.opened_at,
        TradeEpisode.__table__.c.closed_at,
        TradeEpisode.__table__.c.roll_reference_bar_end,
        TradeExecution.__table__.c.executed_at,
        TradeReview.__table__.c.submitted_at,
    )
    assert all(column.type.timezone is True for column in timestamp_columns)
    assert _unique_columns(
        TradeExecution.__table__, "uq_trade_executions_episode_sequence"
    ) == ("episode_id", "sequence_no")
    assert _unique_columns(
        TradeExecution.__table__, "uq_trade_executions_trigger_decision"
    ) == ("trigger_decision_id",)
    assert _index_columns(
        TradeEpisode.__table__, "uq_trade_episodes_symbol_open"
    ) == ("symbol",)
    assert _check_names(TradeEpisode.__table__) == {
        "ck_trade_episodes_direction",
        "ck_trade_episodes_lifecycle",
        "ck_trade_episodes_closed_at",
        "ck_trade_episodes_multiplier_positive",
        "ck_trade_episodes_multiplier_lineage",
    }


def test_one_decision_per_alert_event(session: Session) -> None:
    event_row = _event(session, symbol="jm", contract="JM2609")
    session.add(_decision(event_row))
    session.commit()

    session.add(_decision(event_row, disposition="NOT_EXECUTED"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_one_origin_decision_per_episode_and_one_review_per_episode(
    session: Session,
) -> None:
    event_row = _event(session, symbol="jm", contract="JM2609")
    decision = _decision(event_row)
    session.add(decision)
    session.commit()
    episode = _episode(decision)
    session.add(episode)
    session.commit()

    session.add(_episode(decision, symbol="j", contract="J2609"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    session.add(_review(episode))
    session.commit()
    session.add(_review(episode))
    with pytest.raises(IntegrityError):
        session.commit()


def test_one_symbol_has_at_most_one_open_episode(session: Session) -> None:
    first = _decision(_event(session, symbol="jm", contract="JM2609"))
    second = _decision(_event(session, symbol="jm", contract="JM2701"))
    session.add_all((first, second))
    session.commit()
    session.add(_episode(first))
    session.commit()

    session.add(_episode(second))
    with pytest.raises(IntegrityError):
        session.commit()


def test_trigger_decision_is_unique_but_multiple_manual_executions_are_allowed(
    session: Session,
) -> None:
    origin = _decision(_event(session, symbol="jm", contract="JM2609"))
    trigger = _decision(_event(session, symbol="jm", contract="JM2609"))
    session.add_all((origin, trigger))
    session.commit()
    episode = _episode(origin)
    session.add(episode)
    session.commit()
    session.add_all(
        (
            _execution(episode, sequence_no=1, execution_type="OPEN", trigger=origin),
            _execution(episode, sequence_no=2, execution_type="ADD"),
            _execution(episode, sequence_no=3, execution_type="REDUCE"),
            _execution(episode, sequence_no=4, execution_type="ADD", trigger=trigger),
        )
    )
    session.commit()

    session.add(
        _execution(episode, sequence_no=5, execution_type="ADD", trigger=trigger)
    )
    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.parametrize(
    ("sequence_no", "execution_type"),
    [(0, "OPEN"), (2, "OPEN"), (1, "ADD")],
)
def test_execution_sequence_constraints_reject_invalid_rows(
    session: Session,
    sequence_no: int,
    execution_type: str,
) -> None:
    decision = _decision(_event(session, symbol="jm", contract="JM2609"))
    session.add(decision)
    session.commit()
    episode = _episode(decision)
    session.add(episode)
    session.commit()

    session.add(
        _execution(
            episode,
            sequence_no=sequence_no,
            execution_type=execution_type,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_episode_sequence_number_is_unique_inside_episode(session: Session) -> None:
    decision = _decision(_event(session, symbol="jm", contract="JM2609"))
    session.add(decision)
    session.commit()
    episode = _episode(decision)
    session.add(episode)
    session.commit()
    session.add(_execution(episode, sequence_no=1, execution_type="OPEN"))
    session.commit()

    session.add(_execution(episode, sequence_no=1, execution_type="OPEN"))
    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.parametrize(
    "changes",
    [
        {"closed_at": NOW + timedelta(hours=1), "close_reason": None},
        {"roll_reference_exit_price": Decimal("100")},
        {"closed_at": NOW + timedelta(hours=1), "close_reason": "DOMINANT_ROLL"},
        {
            "closed_at": NOW + timedelta(hours=1),
            "close_reason": "EXECUTION_NET_ZERO",
            "roll_reference_exit_price": Decimal("100"),
            "roll_reference_bar_end": NOW + timedelta(minutes=30),
        },
        {
            "closed_at": NOW - timedelta(minutes=1),
            "close_reason": "EXECUTION_NET_ZERO",
        },
    ],
)
def test_episode_lifecycle_constraints_reject_inconsistent_states(
    session: Session,
    changes: dict[str, object],
) -> None:
    decision = _decision(_event(session, symbol="jm", contract="JM2609"))
    session.add(decision)
    session.commit()
    values: dict[str, object] = {
        "origin_decision_id": decision.id,
        "symbol": "jm",
        "contract": "JM2609",
        "direction": "SHORT",
        "opened_at": NOW,
        "closed_at": None,
        "close_reason": None,
        "roll_reference_exit_price": None,
        "roll_reference_bar_end": None,
        "contract_multiplier_snapshot": None,
        "multiplier_policy_id": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(changes)

    with pytest.raises(IntegrityError):
        session.execute(TradeEpisode.__table__.insert().values(**values))
        session.commit()


def test_episode_lifecycle_accepts_open_roll_and_net_zero_states(session: Session) -> None:
    decisions = [
        _decision(_event(session, symbol=symbol, contract=contract))
        for symbol, contract in (("jm", "JM2609"), ("j", "J2609"), ("i", "I2609"))
    ]
    session.add_all(decisions)
    session.commit()
    session.add_all(
        (
            _episode(decisions[0]),
            _episode(
                decisions[1],
                symbol="j",
                contract="J2609",
                closed_at=NOW + timedelta(hours=1),
                close_reason="DOMINANT_ROLL",
                roll_reference_exit_price=Decimal("1500"),
                roll_reference_bar_end=NOW + timedelta(minutes=30),
            ),
            _episode(
                decisions[2],
                symbol="i",
                contract="I2609",
                closed_at=NOW + timedelta(hours=1),
                close_reason="EXECUTION_NET_ZERO",
            ),
        )
    )

    session.commit()


@pytest.mark.parametrize(
    ("snapshot", "policy_id"),
    [
        (Decimal("60"), None),
        (None, "product_trade_multipliers_v1"),
        (Decimal("60"), "unknown_policy"),
    ],
)
def test_episode_multiplier_snapshot_and_policy_are_both_present_or_both_absent(
    session: Session,
    snapshot: Decimal | None,
    policy_id: str | None,
) -> None:
    decision = _decision(_event(session, symbol="jm", contract="JM2609"))
    episode = _episode(decision)
    episode.contract_multiplier_snapshot = snapshot
    episode.multiplier_policy_id = policy_id
    session.add(episode)

    with pytest.raises(IntegrityError):
        session.commit()


def test_episode_multiplier_snapshot_and_policy_may_both_be_absent(
    session: Session,
) -> None:
    decision = _decision(_event(session, symbol="jm", contract="JM2609"))
    episode = _episode(decision)
    episode.contract_multiplier_snapshot = None
    episode.multiplier_policy_id = None
    session.add(episode)

    session.commit()


@pytest.mark.parametrize(
    ("model", "changes"),
    [
        ("decision", {"disposition": "PENDING"}),
        ("episode", {"direction": "FLAT"}),
        ("episode", {"contract_multiplier_snapshot": Decimal("0")}),
        ("execution", {"execution_type": "REVERSE"}),
        ("execution", {"price": Decimal("0")}),
        ("execution", {"quantity": 0}),
        ("review", {"signal_execution_adherence": "UNKNOWN"}),
    ],
)
def test_scalar_checks_reject_invalid_values(
    session: Session,
    model: str,
    changes: dict[str, object],
) -> None:
    decision = _decision(_event(session, symbol="jm", contract="JM2609"))
    session.add(decision)
    session.commit()
    episode = _episode(decision)
    if model in {"execution", "review"}:
        episode.closed_at = NOW + timedelta(hours=1) if model == "review" else None
        episode.close_reason = "EXECUTION_NET_ZERO" if model == "review" else None
    session.add(episode)
    session.commit()
    row: object
    if model == "decision":
        row = decision
    elif model == "episode":
        row = episode
    elif model == "execution":
        row = _execution(episode, sequence_no=1, execution_type="OPEN")
    else:
        row = _review(episode)
    for key, value in changes.items():
        setattr(row, key, value)
    session.add(row)

    with pytest.raises(IntegrityError):
        session.commit()


def _event(session: Session, *, symbol: str, contract: str) -> AlertEvent:
    rule = AlertRule(
        rule_code=f"subing_entry_signal_v1_{symbol}_{contract}_{id(session)}_{session.new.__len__()}",
        enabled=True,
        scope_products=[symbol],
    )
    event_row = AlertEvent(
        rule=rule,
        symbol=symbol,
        contract=contract,
        trading_day=date(2026, 8, 15),
        frequency="15m",
        bar_end=NOW,
        result_codes=["sell"],
        lower_tf_confirmation=False,
        detected_at=NOW,
    )
    session.add(event_row)
    return event_row


def _decision(
    event_row: AlertEvent,
    *,
    disposition: str = "EXECUTED",
) -> TradeDecision:
    return TradeDecision(
        alert_event=event_row,
        disposition=disposition,
        first_viewed_at=None,
        decided_at=NOW,
        primary_not_execute_reason=("TOO_LATE" if disposition == "NOT_EXECUTED" else None),
        secondary_not_execute_reasons=[],
        decision_note=None,
        execution_reason_tags=(
            ["LOCATION_ACCEPTABLE"] if disposition == "EXECUTED" else []
        ),
        planned_stop_price=None,
        stop_basis=None,
    )


def _episode(
    decision: TradeDecision,
    *,
    symbol: str = "jm",
    contract: str = "JM2609",
    closed_at: datetime | None = None,
    close_reason: str | None = None,
    roll_reference_exit_price: Decimal | None = None,
    roll_reference_bar_end: datetime | None = None,
) -> TradeEpisode:
    return TradeEpisode(
        origin_decision=decision,
        symbol=symbol,
        contract=contract,
        direction="SHORT",
        opened_at=NOW,
        closed_at=closed_at,
        close_reason=close_reason,
        roll_reference_exit_price=roll_reference_exit_price,
        roll_reference_bar_end=roll_reference_bar_end,
        contract_multiplier_snapshot=Decimal("60"),
        multiplier_policy_id="product_trade_multipliers_v1",
    )


def _execution(
    episode: TradeEpisode,
    *,
    sequence_no: int,
    execution_type: str,
    trigger: TradeDecision | None = None,
) -> TradeExecution:
    return TradeExecution(
        episode=episode,
        trigger_decision=trigger,
        sequence_no=sequence_no,
        execution_type=execution_type,
        executed_at=NOW,
        price=Decimal("100"),
        quantity=1,
        note=None,
    )


def _review(episode: TradeEpisode) -> TradeReview:
    return TradeReview(
        episode=episode,
        signal_execution_adherence="ALIGNED",
        entry_tags=["REASONABLE"],
        holding_tags=["NORMAL"],
        exit_tags=["NORMAL"],
        market_context_tags=["TREND"],
        psychology_tags=["NONE"],
        summary=None,
        submitted_at=NOW,
    )


def _check_names(table: object) -> set[str]:
    return {
        constraint.name
        for constraint in table.constraints  # type: ignore[attr-defined]
        if isinstance(constraint, CheckConstraint) and constraint.name is not None
    }


def _unique_columns(table: object, name: str) -> tuple[str, ...]:
    constraint = next(
        item
        for item in table.constraints  # type: ignore[attr-defined]
        if isinstance(item, UniqueConstraint) and item.name == name
    )
    return tuple(column.name for column in constraint.columns)


def _index_columns(table: object, name: str) -> tuple[str, ...]:
    index = next(
        item
        for item in table.indexes  # type: ignore[attr-defined]
        if isinstance(item, Index) and item.name == name
    )
    return tuple(column.name for column in index.columns)
