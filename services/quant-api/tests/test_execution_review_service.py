from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import os
from pathlib import Path
from threading import Barrier, Event

import pytest
from alembic import command as alembic_command
from alembic.config import Config
from sqlalchemy import create_engine, event as sqlalchemy_event, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.alerts.models import AlertEvent, AlertRule
from app.db.base import Base
from app.db.migration_test_guard import (
    MigrationTestDatabaseSafetyError,
    probe_database_identity,
    require_isolated_migration_database_url,
)
from app.execution_review.models import (
    TradeDecision,
    TradeEpisode,
    TradeExecution,
    TradeReview,
)
from app.execution_review.reconciler import RollReconcileResult
from app.execution_review.service import (
    ExecutedCommand,
    DecisionUpdateCommand,
    DispositionCorrectionCommand,
    ExecutionCommand,
    ExecutionUpdateCommand,
    ExecutionReviewDomainError,
    ExecutionReviewService,
    NotExecutedCommand,
    ReviewCommand,
    TimelineExecutionCommand,
)


BAR_END = datetime(2026, 8, 15, 1, 0, tzinfo=UTC)
SERVER_NOW = BAR_END + timedelta(minutes=20)
QUANT_API_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as value:
        yield value
    engine.dispose()


@pytest.fixture
def postgres_engine(monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    if not os.getenv("GUIYI_ISOLATED_MIGRATION_DATABASE_URL", "").strip():
        pytest.fail("GUIYI_ISOLATED_MIGRATION_DATABASE_URL is required")
    try:
        url = require_isolated_migration_database_url(
            os.environ,
            identity_probe=probe_database_identity,
        )
    except MigrationTestDatabaseSafetyError as exc:
        pytest.fail(str(exc))
    monkeypatch.setenv("DATABASE_URL", url)
    engine = create_engine(url, pool_pre_ping=True)
    config = Config()
    config.set_main_option("script_location", str(QUANT_API_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", url)
    _reset_postgres(engine)
    alembic_command.upgrade(config, "20260815_0039")
    try:
        yield engine
    finally:
        _reset_postgres(engine)
        engine.dispose()


def test_not_executed_creates_one_decision_with_server_time(
    session: Session,
) -> None:
    event = _event(session)
    service = _service(session)

    decision = service.record_not_executed(
        event.id,
        NotExecutedCommand(primary_reason="TOO_LATE"),
    )

    assert decision.alert_event_id == event.id
    assert decision.disposition == "NOT_EXECUTED"
    assert _utc(decision.decided_at) == SERVER_NOW
    assert decision.primary_not_execute_reason == "TOO_LATE"
    assert decision.secondary_not_execute_reasons == []
    assert decision.execution_reason_tags == []
    assert _count(session, TradeDecision) == 1
    assert _count(session, TradeEpisode) == 0
    assert _count(session, TradeExecution) == 0
    assert _count(session, TradeReview) == 0


def test_successful_mutation_does_not_depend_on_post_commit_refresh(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = _event(session)

    def fail_refresh(*_: object, **__: object) -> None:
        raise SQLAlchemyError("database unavailable after commit")

    monkeypatch.setattr(session, "refresh", fail_refresh)
    decision = _service(session).record_not_executed(
        event.id,
        NotExecutedCommand(primary_reason="TOO_LATE"),
    )

    assert decision.disposition == "NOT_EXECUTED"
    with Session(session.get_bind()) as check:
        assert _count(check, TradeDecision) == 1


def test_duplicate_processed_event_does_not_call_defensive_reconcile(
    session: Session,
) -> None:
    event = _event(session)
    _service(session).record_executed(event.id, _executed())
    calls: list[str] = []
    service = ExecutionReviewService(
        session,
        multipliers={"jm": Decimal("60")},
        clock=lambda: SERVER_NOW,
        reconcile_symbol=lambda symbol: (
            calls.append(symbol)
            or RollReconcileResult("NOOP", symbol)
        ),
    )

    with pytest.raises(ExecutionReviewDomainError, match="^DECISION_ALREADY_EXISTS$"):
        service.record_executed(event.id, _executed())

    assert calls == []


def test_record_executed_without_open_episode_does_not_call_reconciler(
    session: Session,
) -> None:
    event = _event(session)
    calls: list[str] = []
    service = ExecutionReviewService(
        session,
        multipliers={"jm": Decimal("60")},
        clock=lambda: SERVER_NOW,
        reconcile_symbol=lambda symbol: (
            calls.append(symbol)
            or RollReconcileResult("NOOP", symbol)
        ),
    )

    result = service.record_executed(event.id, _executed())

    assert result.execution.execution_type == "OPEN"
    assert calls == []


def test_defensive_reconcile_required_blocks_new_decision_and_execution(
    session: Session,
) -> None:
    _service(session).record_executed(_event(session).id, _executed())
    next_event = _event(
        session,
        bar_end=BAR_END + timedelta(minutes=10),
    )
    calls: list[str] = []
    service = ExecutionReviewService(
        session,
        multipliers={"jm": Decimal("60")},
        clock=lambda: SERVER_NOW,
        reconcile_symbol=lambda symbol: (
            calls.append(symbol)
            or RollReconcileResult(
                "ROLL_RECONCILIATION_REQUIRED",
                symbol,
            )
        ),
    )

    with pytest.raises(
        ExecutionReviewDomainError,
        match="^ROLL_RECONCILIATION_REQUIRED$",
    ):
        service.record_executed(
            next_event.id,
            _executed(executed_at=BAR_END + timedelta(minutes=13)),
        )

    assert calls == ["jm"]
    assert _count(session, TradeDecision) == 1
    assert _count(session, TradeExecution) == 1


def test_defensive_reconcile_reloads_closed_old_contract_before_new_event(
    session: Session,
) -> None:
    old = _service(session).record_executed(_event(session).id, _executed())
    next_event = _event(
        session,
        contract="JM2701",
        bar_end=BAR_END + timedelta(minutes=10),
    )
    calls: list[str] = []

    def reconcile(symbol: str) -> RollReconcileResult:
        calls.append(symbol)
        episode = session.get(TradeEpisode, old.episode.id)
        assert episode is not None
        episode.closed_at = BAR_END + timedelta(minutes=8)
        episode.close_reason = "DOMINANT_ROLL"
        episode.roll_reference_exit_price = Decimal("1258")
        episode.roll_reference_bar_end = BAR_END + timedelta(minutes=8)
        session.commit()
        return RollReconcileResult("DOMINANT_ROLL", symbol, episode.id)

    service = ExecutionReviewService(
        session,
        multipliers={"jm": Decimal("60")},
        clock=lambda: SERVER_NOW,
        reconcile_symbol=reconcile,
    )

    result = service.record_executed(
        next_event.id,
        _executed(executed_at=BAR_END + timedelta(minutes=13)),
    )

    assert calls == ["jm"]
    assert result.execution.execution_type == "OPEN"
    assert result.episode.contract == "JM2701"
    old_episode = session.get(TradeEpisode, old.episode.id)
    assert old_episode is not None
    assert old_episode.close_reason == "DOMINANT_ROLL"


def test_not_executed_uses_explicit_decided_at_and_allows_late_first_view(
    session: Session,
) -> None:
    event = _event(session)
    decided_at = BAR_END + timedelta(minutes=5)
    first_viewed_at = BAR_END + timedelta(hours=2)

    decision = _service(session).record_not_executed(
        event.id,
        NotExecutedCommand(
            primary_reason="WORK_MISSED",
            decided_at=decided_at,
            first_viewed_at=first_viewed_at,
        ),
    )

    assert _utc(decision.decided_at) == decided_at
    assert _utc(decision.first_viewed_at) == first_viewed_at


@pytest.mark.parametrize(
    ("event_changes", "code"),
    [
        ({"rule_code": "htdy_original_15m"}, "EVENT_NOT_EXECUTION_REVIEW_ELIGIBLE"),
        ({"result_codes": []}, "EVENT_DIRECTION_INVALID"),
        ({"result_codes": ["buy", "sell"]}, "EVENT_DIRECTION_INVALID"),
        ({"result_codes": ["hold"]}, "EVENT_DIRECTION_INVALID"),
        ({"trading_day": None}, "EVENT_NOT_EXECUTION_REVIEW_ELIGIBLE"),
        ({"contract": ""}, "EVENT_NOT_EXECUTION_REVIEW_ELIGIBLE"),
        ({"frequency": "1m"}, "EVENT_NOT_EXECUTION_REVIEW_ELIGIBLE"),
    ],
)
def test_ineligible_events_fail_closed_without_writes(
    session: Session,
    event_changes: dict[str, object],
    code: str,
) -> None:
    event = _event(session, **event_changes)

    with pytest.raises(ExecutionReviewDomainError, match=f"^{code}$"):
        _service(session).record_not_executed(
            event.id,
            NotExecutedCommand(primary_reason="TOO_LATE"),
        )

    assert _count(session, TradeDecision) == 0


def test_not_executed_rejects_decision_before_signal(session: Session) -> None:
    event = _event(session)

    with pytest.raises(
        ExecutionReviewDomainError,
        match="^DECISION_TIME_BEFORE_SIGNAL$",
    ):
        _service(session).record_not_executed(
            event.id,
            NotExecutedCommand(
                primary_reason="TOO_LATE",
                decided_at=BAR_END - timedelta(seconds=1),
            ),
        )

    assert _count(session, TradeDecision) == 0


def test_not_executed_validates_frozen_reason_contract(session: Session) -> None:
    event = _event(session)

    with pytest.raises(ExecutionReviewDomainError, match="^OTHER_NOTE_REQUIRED$"):
        _service(session).record_not_executed(
            event.id,
            NotExecutedCommand(primary_reason="OTHER"),
        )

    assert _count(session, TradeDecision) == 0


def test_missing_event_is_stable_not_found(session: Session) -> None:
    with pytest.raises(
        ExecutionReviewDomainError,
        match="^EXECUTION_REVIEW_EVENT_NOT_FOUND$",
    ):
        _service(session).record_not_executed(
            999,
            NotExecutedCommand(primary_reason="TOO_LATE"),
        )


def test_second_decision_for_event_is_conflict(session: Session) -> None:
    event = _event(session)
    service = _service(session)
    service.record_not_executed(
        event.id,
        NotExecutedCommand(primary_reason="TOO_LATE"),
    )

    with pytest.raises(ExecutionReviewDomainError, match="^DECISION_ALREADY_EXISTS$"):
        service.record_not_executed(
            event.id,
            NotExecutedCommand(primary_reason="WORK_MISSED"),
        )

    assert _count(session, TradeDecision) == 1


def test_executed_creates_decision_episode_and_open_atomically(
    session: Session,
) -> None:
    event = _event(session, result_codes=["sell"])

    result = _service(session).record_executed(
        event.id,
        ExecutedCommand(
            executed_at=BAR_END + timedelta(minutes=3),
            price=Decimal("1268.5"),
            quantity=2,
            execution_reason_tags=("KEY_LEVEL_BREAKOUT",),
            first_viewed_at=BAR_END + timedelta(hours=1),
        ),
    )

    assert result.decision.disposition == "EXECUTED"
    assert _utc(result.decision.decided_at) == BAR_END + timedelta(minutes=3)
    assert result.episode.direction == "SHORT"
    assert result.episode.symbol == "jm"
    assert result.episode.contract == "JM2609"
    assert result.episode.contract_multiplier_snapshot == Decimal("60")
    assert result.episode.multiplier_policy_id == "product_trade_multipliers_v1"
    assert result.execution.sequence_no == 1
    assert result.execution.execution_type == "OPEN"
    assert result.execution.trigger_decision_id == result.decision.id
    assert result.position.remaining_quantity == 2
    assert _count(session, TradeDecision) == 1
    assert _count(session, TradeEpisode) == 1
    assert _count(session, TradeExecution) == 1


def test_executed_time_contract_is_fail_closed(session: Session) -> None:
    event = _event(session)

    with pytest.raises(ExecutionReviewDomainError, match="^EXECUTION_TIME_BEFORE_SIGNAL$"):
        _service(session).record_executed(
            event.id,
            _executed(executed_at=BAR_END - timedelta(seconds=1)),
        )
    assert _count(session, TradeDecision) == 0

    with pytest.raises(ExecutionReviewDomainError, match="^DECISION_AFTER_EXECUTION$"):
        _service(session).record_executed(
            event.id,
            _executed(
                executed_at=BAR_END + timedelta(minutes=2),
                decided_at=BAR_END + timedelta(minutes=3),
            ),
        )
    assert _count(session, TradeDecision) == 0


def test_executed_validates_reasons_stop_and_decimal_inputs(session: Session) -> None:
    event = _event(session)

    with pytest.raises(ExecutionReviewDomainError, match="^EXECUTION_REASON_REQUIRED$"):
        _service(session).record_executed(
            event.id,
            _executed(execution_reason_tags=()),
        )
    assert _count(session, TradeDecision) == 0

    with pytest.raises(ExecutionReviewDomainError, match="^STOP_BASIS_REQUIRED$"):
        _service(session).record_executed(
            event.id,
            _executed(planned_stop_price=Decimal("1200")),
        )
    assert _count(session, TradeDecision) == 0

    with pytest.raises(ExecutionReviewDomainError, match="^PRICE_INVALID$"):
        _service(session).record_executed(
            event.id,
            _executed(price=Decimal("NaN")),
        )
    assert _count(session, TradeDecision) == 0


def test_missing_multiplier_does_not_block_execution_facts(session: Session) -> None:
    event = _event(session, symbol="zz", contract="ZZ2609")

    result = _service(session).record_executed(event.id, _executed())

    assert result.episode.contract_multiplier_snapshot is None
    assert result.episode.multiplier_policy_id is None
    assert result.position.realized_gross_pnl is None


def test_same_contract_and_direction_event_creates_decision_and_add(
    session: Session,
) -> None:
    first = _event(session, bar_end=BAR_END)
    service = _service(session)
    opened = service.record_executed(first.id, _executed(quantity=2))
    second = _event(
        session,
        bar_end=BAR_END + timedelta(minutes=15),
        result_codes=["sell"],
    )

    added = service.record_executed(
        second.id,
        _executed(
            executed_at=BAR_END + timedelta(minutes=18),
            price=Decimal("1250"),
            quantity=1,
        ),
    )

    assert added.episode.id == opened.episode.id
    assert added.execution.execution_type == "ADD"
    assert added.execution.sequence_no == 2
    assert added.execution.trigger_decision_id == added.decision.id
    assert added.position.remaining_quantity == 3
    assert added.position.average_cost == Decimal("1262.333333333333333333333333")
    assert _count(session, TradeDecision) == 2
    assert _count(session, TradeEpisode) == 1
    assert _count(session, TradeExecution) == 2


@pytest.mark.parametrize(
    ("second_changes", "code"),
    [
        ({"result_codes": ["buy"]}, "OPPOSITE_EPISODE_OPEN"),
        ({"contract": "JM2701"}, "OPEN_EPISODE_CONFLICT"),
        (
            {"contract": "JM2701", "result_codes": ["buy"]},
            "OPEN_EPISODE_CONFLICT",
        ),
    ],
)
def test_existing_episode_conflicts_are_stable_and_atomic(
    session: Session,
    second_changes: dict[str, object],
    code: str,
) -> None:
    first = _event(session, bar_end=BAR_END)
    service = _service(session)
    service.record_executed(first.id, _executed())
    second = _event(
        session,
        bar_end=BAR_END + timedelta(minutes=15),
        **second_changes,
    )

    with pytest.raises(ExecutionReviewDomainError, match=f"^{code}$"):
        service.record_executed(
            second.id,
            _executed(executed_at=BAR_END + timedelta(minutes=18)),
        )

    assert _count(session, TradeDecision) == 1
    assert _count(session, TradeEpisode) == 1
    assert _count(session, TradeExecution) == 1


def test_manual_executions_get_server_sequence_and_close_episode(
    session: Session,
) -> None:
    event = _event(session)
    service = _service(session)
    opened = service.record_executed(event.id, _executed(quantity=2))

    added = service.append_execution(
        opened.episode.id,
        ExecutionCommand(
            execution_type="ADD",
            executed_at=BAR_END + timedelta(minutes=5),
            price=Decimal("1250"),
            quantity=2,
        ),
    )
    reduced = service.append_execution(
        opened.episode.id,
        ExecutionCommand(
            execution_type="REDUCE",
            executed_at=BAR_END + timedelta(minutes=6),
            price=Decimal("1240"),
            quantity=1,
        ),
    )
    closed = service.append_execution(
        opened.episode.id,
        ExecutionCommand(
            execution_type="CLOSE",
            executed_at=BAR_END + timedelta(minutes=7),
            price=Decimal("1230"),
            quantity=3,
        ),
    )

    assert [added.execution.sequence_no, reduced.execution.sequence_no] == [2, 3]
    assert added.execution.trigger_decision_id is None
    assert reduced.execution.trigger_decision_id is None
    assert closed.execution.sequence_no == 4
    assert closed.execution.trigger_decision_id is None
    assert closed.position.remaining_quantity == 0
    assert closed.episode.close_reason == "EXECUTION_NET_ZERO"
    assert _utc(closed.episode.closed_at) == BAR_END + timedelta(minutes=7)
    assert [
        row.sequence_no
        for row in session.scalars(
            select(TradeExecution)
            .where(TradeExecution.episode_id == opened.episode.id)
            .order_by(TradeExecution.sequence_no)
        )
    ] == [1, 2, 3, 4]


@pytest.mark.parametrize(
    ("command", "code"),
    [
        (
            ExecutionCommand(
                execution_type="OPEN",
                executed_at=BAR_END + timedelta(minutes=4),
                price=Decimal("1260"),
                quantity=1,
            ),
            "MANUAL_OPEN_NOT_ALLOWED",
        ),
        (
            ExecutionCommand(
                execution_type="REDUCE",
                executed_at=BAR_END + timedelta(minutes=4),
                price=Decimal("1260"),
                quantity=2,
            ),
            "REDUCE_QUANTITY_INVALID",
        ),
        (
            ExecutionCommand(
                execution_type="CLOSE",
                executed_at=BAR_END + timedelta(minutes=4),
                price=Decimal("1260"),
                quantity=1,
            ),
            "CLOSE_QUANTITY_INVALID",
        ),
    ],
)
def test_manual_execution_rejects_open_reverse_and_inexact_close(
    session: Session,
    command: ExecutionCommand,
    code: str,
) -> None:
    opened = _service(session).record_executed(
        _event(session).id,
        _executed(quantity=2),
    )

    with pytest.raises(ExecutionReviewDomainError, match=f"^{code}$"):
        _service(session).append_execution(opened.episode.id, command)

    assert _count(session, TradeExecution) == 1


def test_closed_episode_rejects_follow_up_execution(session: Session) -> None:
    service = _service(session)
    opened = service.record_executed(_event(session).id, _executed(quantity=1))
    service.append_execution(
        opened.episode.id,
        ExecutionCommand(
            execution_type="CLOSE",
            executed_at=BAR_END + timedelta(minutes=4),
            price=Decimal("1260"),
            quantity=1,
        ),
    )

    with pytest.raises(ExecutionReviewDomainError, match="^EPISODE_ALREADY_CLOSED$"):
        service.append_execution(
            opened.episode.id,
            ExecutionCommand(
                execution_type="ADD",
                executed_at=BAR_END + timedelta(minutes=5),
                price=Decimal("1250"),
                quantity=1,
            ),
        )

    assert _count(session, TradeExecution) == 2


def test_manual_close_cannot_precede_episode_open(session: Session) -> None:
    service = _service(session)
    opened = service.record_executed(_event(session).id, _executed(quantity=1))

    with pytest.raises(
        ExecutionReviewDomainError,
        match="^EXECUTION_REVIEW_TIME_INVALID$",
    ):
        service.append_execution(
            opened.episode.id,
            ExecutionCommand(
                execution_type="CLOSE",
                executed_at=BAR_END + timedelta(minutes=2),
                price=Decimal("1260"),
                quantity=1,
            ),
        )

    assert _count(session, TradeExecution) == 1


def test_simple_execution_correction_updates_only_mutable_fact_fields(
    session: Session,
) -> None:
    service = _service(session)
    opened = service.record_executed(_event(session).id, _executed(quantity=2))
    corrected_at = BAR_END + timedelta(minutes=4)

    result = service.update_execution(
        opened.execution.id,
        ExecutionUpdateCommand(
            executed_at=corrected_at,
            price=Decimal("1270.25"),
            note="corrected fill",
        ),
    )

    assert result.execution.id == opened.execution.id
    assert result.execution.sequence_no == 1
    assert result.execution.execution_type == "OPEN"
    assert result.execution.quantity == 2
    assert result.execution.trigger_decision_id == opened.decision.id
    assert result.execution.price == Decimal("1270.25")
    assert result.execution.note == "corrected fill"
    assert _utc(result.episode.opened_at) == corrected_at


def test_invalid_simple_execution_correction_rolls_back(session: Session) -> None:
    service = _service(session)
    opened = service.record_executed(_event(session).id, _executed(quantity=2))

    with pytest.raises(ExecutionReviewDomainError, match="^PRICE_INVALID$"):
        service.update_execution(
            opened.execution.id,
            ExecutionUpdateCommand(
                executed_at=BAR_END + timedelta(minutes=4),
                price=Decimal("0"),
                note="invalid",
            ),
        )

    unchanged = session.get(TradeExecution, opened.execution.id)
    assert unchanged is not None
    assert unchanged.price == Decimal("1268.5")
    assert unchanged.note is None


def test_triggered_execution_correction_cannot_precede_decision(
    session: Session,
) -> None:
    service = _service(session)
    opened = service.record_executed(
        _event(session).id,
        _executed(
            decided_at=BAR_END + timedelta(minutes=2),
            executed_at=BAR_END + timedelta(minutes=3),
        ),
    )

    with pytest.raises(ExecutionReviewDomainError, match="^DECISION_AFTER_EXECUTION$"):
        service.update_execution(
            opened.execution.id,
            ExecutionUpdateCommand(
                executed_at=BAR_END + timedelta(minutes=1),
                price=Decimal("1268.5"),
            ),
        )

    unchanged = session.get(TradeExecution, opened.execution.id)
    assert unchanged is not None
    assert _utc(unchanged.executed_at) == BAR_END + timedelta(minutes=3)


def test_open_correction_cannot_move_after_episode_close(session: Session) -> None:
    service = _service(session)
    opened = service.record_executed(_event(session).id, _executed(quantity=1))
    service.append_execution(
        opened.episode.id,
        ExecutionCommand(
            execution_type="CLOSE",
            executed_at=BAR_END + timedelta(minutes=5),
            price=Decimal("1260"),
            quantity=1,
        ),
    )

    with pytest.raises(
        ExecutionReviewDomainError,
        match="^EXECUTION_REVIEW_TIME_INVALID$",
    ):
        service.update_execution(
            opened.execution.id,
            ExecutionUpdateCommand(
                executed_at=BAR_END + timedelta(minutes=6),
                price=Decimal("1268.5"),
            ),
        )

    unchanged = session.get(TradeEpisode, opened.episode.id)
    assert unchanged is not None
    assert _utc(unchanged.opened_at) == BAR_END + timedelta(minutes=3)


def test_timeline_replacement_renumbers_and_preserves_trigger_lineage(
    session: Session,
) -> None:
    service = _service(session)
    first = service.record_executed(_event(session, bar_end=BAR_END).id, _executed())
    second = service.record_executed(
        _event(session, bar_end=BAR_END + timedelta(minutes=15)).id,
        _executed(
            executed_at=BAR_END + timedelta(minutes=18),
            quantity=1,
        ),
    )

    result = service.replace_execution_timeline(
        first.episode.id,
        (
            TimelineExecutionCommand(
                execution_id=first.execution.id,
                execution_type="OPEN",
                executed_at=BAR_END + timedelta(minutes=3),
                price=Decimal("1268.5"),
                quantity=2,
            ),
            TimelineExecutionCommand(
                execution_id=second.execution.id,
                execution_type="ADD",
                executed_at=BAR_END + timedelta(minutes=18),
                price=Decimal("1260"),
                quantity=1,
            ),
            TimelineExecutionCommand(
                execution_id=None,
                execution_type="REDUCE",
                executed_at=BAR_END + timedelta(minutes=20),
                price=Decimal("1250"),
                quantity=1,
            ),
            TimelineExecutionCommand(
                execution_id=None,
                execution_type="CLOSE",
                executed_at=BAR_END + timedelta(minutes=21),
                price=Decimal("1240"),
                quantity=2,
            ),
        ),
    )

    rows = session.scalars(
        select(TradeExecution)
        .where(TradeExecution.episode_id == first.episode.id)
        .order_by(TradeExecution.sequence_no)
    ).all()
    assert [row.sequence_no for row in rows] == [1, 2, 3, 4]
    assert [row.trigger_decision_id for row in rows] == [
        first.decision.id,
        second.decision.id,
        None,
        None,
    ]
    assert result.position.remaining_quantity == 0
    assert result.episode.close_reason == "EXECUTION_NET_ZERO"


def test_timeline_close_cannot_precede_rebuilt_open(session: Session) -> None:
    service = _service(session)
    opened = service.record_executed(_event(session).id, _executed(quantity=1))

    with pytest.raises(
        ExecutionReviewDomainError,
        match="^EXECUTION_REVIEW_TIME_INVALID$",
    ):
        service.replace_execution_timeline(
            opened.episode.id,
            (
                TimelineExecutionCommand(
                    execution_id=opened.execution.id,
                    execution_type="OPEN",
                    executed_at=BAR_END + timedelta(minutes=6),
                    price=Decimal("1268.5"),
                    quantity=1,
                ),
                TimelineExecutionCommand(
                    execution_id=None,
                    execution_type="CLOSE",
                    executed_at=BAR_END + timedelta(minutes=5),
                    price=Decimal("1260"),
                    quantity=1,
                ),
            ),
        )

    assert _count(session, TradeExecution) == 1


@pytest.mark.parametrize("mutation", ["omit_trigger", "change_trigger_type"])
def test_timeline_replacement_rejects_lineage_corruption_atomically(
    session: Session,
    mutation: str,
) -> None:
    service = _service(session)
    first = service.record_executed(_event(session, bar_end=BAR_END).id, _executed())
    second = service.record_executed(
        _event(session, bar_end=BAR_END + timedelta(minutes=15)).id,
        _executed(executed_at=BAR_END + timedelta(minutes=18)),
    )
    commands = [
        TimelineExecutionCommand(
            execution_id=first.execution.id,
            execution_type="OPEN",
            executed_at=BAR_END + timedelta(minutes=3),
            price=Decimal("1268.5"),
            quantity=2,
        ),
        TimelineExecutionCommand(
            execution_id=second.execution.id,
            execution_type="ADD",
            executed_at=BAR_END + timedelta(minutes=18),
            price=Decimal("1268.5"),
            quantity=2,
        ),
    ]
    if mutation == "omit_trigger":
        commands.pop()
    else:
        commands[1] = TimelineExecutionCommand(
            execution_id=second.execution.id,
            execution_type="REDUCE",
            executed_at=BAR_END + timedelta(minutes=18),
            price=Decimal("1268.5"),
            quantity=1,
        )

    with pytest.raises(ExecutionReviewDomainError, match="^EXECUTION_LINEAGE_INVALID$"):
        service.replace_execution_timeline(first.episode.id, tuple(commands))

    rows = session.scalars(
        select(TradeExecution)
        .where(TradeExecution.episode_id == first.episode.id)
        .order_by(TradeExecution.sequence_no)
    ).all()
    assert [(row.id, row.sequence_no, row.execution_type) for row in rows] == [
        (first.execution.id, 1, "OPEN"),
        (second.execution.id, 2, "ADD"),
    ]


def test_invalid_timeline_replacement_rolls_back_all_rows(session: Session) -> None:
    service = _service(session)
    first = service.record_executed(_event(session).id, _executed(quantity=2))

    with pytest.raises(ExecutionReviewDomainError, match="^CLOSE_QUANTITY_INVALID$"):
        service.replace_execution_timeline(
            first.episode.id,
            (
                TimelineExecutionCommand(
                    execution_id=first.execution.id,
                    execution_type="OPEN",
                    executed_at=BAR_END + timedelta(minutes=3),
                    price=Decimal("1268.5"),
                    quantity=2,
                ),
                TimelineExecutionCommand(
                    execution_id=None,
                    execution_type="CLOSE",
                    executed_at=BAR_END + timedelta(minutes=5),
                    price=Decimal("1260"),
                    quantity=1,
                ),
            ),
        )

    rows = session.scalars(
        select(TradeExecution).where(TradeExecution.episode_id == first.episode.id)
    ).all()
    assert [(row.id, row.sequence_no, row.execution_type) for row in rows] == [
        (first.execution.id, 1, "OPEN")
    ]


def test_timeline_correction_cannot_move_trigger_before_decision(
    session: Session,
) -> None:
    service = _service(session)
    opened = service.record_executed(
        _event(session).id,
        _executed(
            decided_at=BAR_END + timedelta(minutes=2),
            executed_at=BAR_END + timedelta(minutes=3),
        ),
    )

    with pytest.raises(ExecutionReviewDomainError, match="^DECISION_AFTER_EXECUTION$"):
        service.replace_execution_timeline(
            opened.episode.id,
            (
                TimelineExecutionCommand(
                    execution_id=opened.execution.id,
                    execution_type="OPEN",
                    executed_at=BAR_END + timedelta(minutes=1),
                    price=Decimal("1268.5"),
                    quantity=2,
                ),
            ),
        )


def test_update_not_executed_validates_complete_cross_fields(session: Session) -> None:
    service = _service(session)
    decision = service.record_not_executed(
        _event(session).id,
        NotExecutedCommand(primary_reason="TOO_LATE"),
    )

    with pytest.raises(ExecutionReviewDomainError, match="^DECISION_FIELDS_INVALID$"):
        service.update_decision(
            decision.id,
            DecisionUpdateCommand(
                first_viewed_at=None,
                decided_at=SERVER_NOW,
                primary_not_execute_reason="TOO_LATE",
                secondary_not_execute_reasons=(),
                note=None,
                execution_reason_tags=("KEY_LEVEL_BREAKOUT",),
                planned_stop_price=None,
                stop_basis=None,
            ),
        )

    updated = service.update_decision(
        decision.id,
        DecisionUpdateCommand(
            first_viewed_at=SERVER_NOW + timedelta(hours=1),
            decided_at=SERVER_NOW,
            primary_not_execute_reason="WORK_MISSED",
            secondary_not_execute_reasons=("TOO_LATE",),
            note="desk work",
            execution_reason_tags=(),
            planned_stop_price=None,
            stop_basis=None,
        ),
    )
    assert updated.disposition == "NOT_EXECUTED"
    assert updated.primary_not_execute_reason == "WORK_MISSED"


def test_update_executed_validates_complete_cross_fields(session: Session) -> None:
    service = _service(session)
    result = service.record_executed(_event(session).id, _executed())

    with pytest.raises(ExecutionReviewDomainError, match="^DECISION_FIELDS_INVALID$"):
        service.update_decision(
            result.decision.id,
            DecisionUpdateCommand(
                first_viewed_at=None,
                decided_at=BAR_END + timedelta(minutes=3),
                primary_not_execute_reason="TOO_LATE",
                secondary_not_execute_reasons=(),
                note=None,
                execution_reason_tags=("KEY_LEVEL_BREAKOUT",),
                planned_stop_price=None,
                stop_basis=None,
            ),
        )

    updated = service.update_decision(
        result.decision.id,
        DecisionUpdateCommand(
            first_viewed_at=SERVER_NOW + timedelta(hours=1),
            decided_at=BAR_END + timedelta(minutes=2),
            primary_not_execute_reason=None,
            secondary_not_execute_reasons=(),
            note="confirmed",
            execution_reason_tags=("PULLBACK_RECONFIRMED",),
            planned_stop_price=Decimal("1300"),
            stop_basis="EMA",
        ),
    )
    assert updated.disposition == "EXECUTED"
    assert updated.execution_reason_tags == ["PULLBACK_RECONFIRMED"]


def test_correct_not_executed_to_executed_reuses_decision_atomically(
    session: Session,
) -> None:
    service = _service(session)
    decision = service.record_not_executed(
        _event(session).id,
        NotExecutedCommand(primary_reason="TOO_LATE"),
    )

    corrected = service.correct_disposition(
        decision.id,
        DispositionCorrectionCommand(
            target_disposition="EXECUTED",
            executed_at=BAR_END + timedelta(minutes=5),
            price=Decimal("1260"),
            quantity=2,
            execution_reason_tags=("KEY_LEVEL_BREAKOUT",),
        ),
    )

    assert corrected.decision.id == decision.id
    assert corrected.decision.disposition == "EXECUTED"
    assert corrected.execution is not None
    assert corrected.execution.execution_type == "OPEN"
    assert corrected.execution.trigger_decision_id == decision.id
    assert _count(session, TradeDecision) == 1
    assert _count(session, TradeEpisode) == 1
    assert _count(session, TradeExecution) == 1


def test_correct_later_executed_to_not_executed_removes_add_and_renumbers(
    session: Session,
) -> None:
    service = _service(session)
    first = service.record_executed(_event(session, bar_end=BAR_END).id, _executed())
    later = service.record_executed(
        _event(session, bar_end=BAR_END + timedelta(minutes=15)).id,
        _executed(executed_at=BAR_END + timedelta(minutes=18), quantity=1),
    )
    manual = service.append_execution(
        first.episode.id,
        ExecutionCommand(
            execution_type="ADD",
            executed_at=BAR_END + timedelta(minutes=20),
            price=Decimal("1250"),
            quantity=1,
        ),
    )

    corrected = service.correct_disposition(
        later.decision.id,
        DispositionCorrectionCommand(
            target_disposition="NOT_EXECUTED",
            primary_reason="TOO_LATE",
        ),
    )

    rows = session.scalars(
        select(TradeExecution)
        .where(TradeExecution.episode_id == first.episode.id)
        .order_by(TradeExecution.sequence_no)
    ).all()
    assert corrected.decision.disposition == "NOT_EXECUTED"
    assert [(row.id, row.sequence_no, row.trigger_decision_id) for row in rows] == [
        (first.execution.id, 1, first.decision.id),
        (manual.execution.id, 2, None),
    ]


def test_correct_origin_executed_to_not_executed_requires_sole_open(
    session: Session,
) -> None:
    service = _service(session)
    opened = service.record_executed(_event(session).id, _executed())
    service.append_execution(
        opened.episode.id,
        ExecutionCommand(
            execution_type="ADD",
            executed_at=BAR_END + timedelta(minutes=5),
            price=Decimal("1260"),
            quantity=1,
        ),
    )

    with pytest.raises(ExecutionReviewDomainError, match="^DECISION_CORRECTION_CONFLICT$"):
        service.correct_disposition(
            opened.decision.id,
            DispositionCorrectionCommand(
                target_disposition="NOT_EXECUTED",
                primary_reason="TOO_LATE",
            ),
        )

    assert session.get(TradeDecision, opened.decision.id).disposition == "EXECUTED"  # type: ignore[union-attr]
    assert _count(session, TradeEpisode) == 1
    assert _count(session, TradeExecution) == 2


def test_correct_sole_origin_to_not_executed_removes_episode(session: Session) -> None:
    service = _service(session)
    opened = service.record_executed(_event(session).id, _executed())

    corrected = service.correct_disposition(
        opened.decision.id,
        DispositionCorrectionCommand(
            target_disposition="NOT_EXECUTED",
            primary_reason="WORK_MISSED",
        ),
    )

    assert corrected.decision.id == opened.decision.id
    assert corrected.decision.disposition == "NOT_EXECUTED"
    assert corrected.episode is None
    assert corrected.execution is None
    assert _count(session, TradeDecision) == 1
    assert _count(session, TradeEpisode) == 0
    assert _count(session, TradeExecution) == 0


def test_review_requires_closed_episode_and_all_five_groups(
    session: Session,
) -> None:
    service = _service(session)
    opened = service.record_executed(_event(session).id, _executed(quantity=1))

    with pytest.raises(ExecutionReviewDomainError, match="^EPISODE_REVIEW_NOT_READY$"):
        service.submit_review(opened.episode.id, _review_command())

    service.append_execution(
        opened.episode.id,
        ExecutionCommand(
            execution_type="CLOSE",
            executed_at=BAR_END + timedelta(minutes=5),
            price=Decimal("1260"),
            quantity=1,
        ),
    )
    with pytest.raises(ExecutionReviewDomainError, match="^REVIEW_TAG_REQUIRED$"):
        service.submit_review(
            opened.episode.id,
            _review_command(entry_tags=()),
        )

    assert _count(session, TradeReview) == 0


def test_submit_and_update_review_use_server_clock_contract(session: Session) -> None:
    service = _service(session)
    opened = service.record_executed(_event(session).id, _executed(quantity=1))
    service.append_execution(
        opened.episode.id,
        ExecutionCommand(
            execution_type="CLOSE",
            executed_at=BAR_END + timedelta(minutes=5),
            price=Decimal("1260"),
            quantity=1,
        ),
    )

    review = service.submit_review(opened.episode.id, _review_command())
    assert _utc(review.submitted_at) == SERVER_NOW
    submitted_at = review.submitted_at

    later = SERVER_NOW + timedelta(hours=2)
    updated = _service(session, now=later).update_review(
        review.id,
        _review_command(summary="updated"),
    )
    assert _utc(updated.submitted_at) == _utc(submitted_at)
    assert _utc(updated.updated_at) == later
    assert updated.summary == "updated"


def test_second_review_is_conflict(session: Session) -> None:
    service = _service(session)
    opened = service.record_executed(_event(session).id, _executed(quantity=1))
    service.append_execution(
        opened.episode.id,
        ExecutionCommand(
            execution_type="CLOSE",
            executed_at=BAR_END + timedelta(minutes=5),
            price=Decimal("1260"),
            quantity=1,
        ),
    )
    service.submit_review(opened.episode.id, _review_command())

    with pytest.raises(ExecutionReviewDomainError, match="^REVIEW_ALREADY_EXISTS$"):
        service.submit_review(opened.episode.id, _review_command())

    assert _count(session, TradeReview) == 1


def test_reviewed_episode_cannot_be_reopened_by_timeline_correction(
    session: Session,
) -> None:
    service = _service(session)
    opened = service.record_executed(_event(session).id, _executed(quantity=1))
    closed = service.append_execution(
        opened.episode.id,
        ExecutionCommand(
            execution_type="CLOSE",
            executed_at=BAR_END + timedelta(minutes=5),
            price=Decimal("1260"),
            quantity=1,
        ),
    )
    review = service.submit_review(opened.episode.id, _review_command())

    with pytest.raises(ExecutionReviewDomainError, match="^REVIEW_LINEAGE_CONFLICT$"):
        service.replace_execution_timeline(
            opened.episode.id,
            (
                TimelineExecutionCommand(
                    execution_id=opened.execution.id,
                    execution_type="OPEN",
                    executed_at=BAR_END + timedelta(minutes=3),
                    price=Decimal("1268.5"),
                    quantity=1,
                ),
            ),
        )

    unchanged = session.get(TradeEpisode, opened.episode.id)
    assert unchanged is not None
    assert unchanged.close_reason == "EXECUTION_NET_ZERO"
    assert unchanged.closed_at is not None
    assert session.get(TradeExecution, closed.execution.id) is not None
    assert session.get(TradeReview, review.id) is not None


def test_real_close_timeline_replaces_dominant_roll_estimate(
    session: Session,
) -> None:
    service = _service(session)
    opened = service.record_executed(_event(session).id, _executed(quantity=2))
    episode = session.get(TradeEpisode, opened.episode.id)
    assert episode is not None
    episode.closed_at = BAR_END + timedelta(minutes=30)
    episode.close_reason = "DOMINANT_ROLL"
    episode.roll_reference_exit_price = Decimal("1258")
    episode.roll_reference_bar_end = BAR_END + timedelta(minutes=30)
    session.commit()

    result = service.replace_execution_timeline(
        episode.id,
        (
            TimelineExecutionCommand(
                execution_id=opened.execution.id,
                execution_type="OPEN",
                executed_at=opened.execution.executed_at,
                price=opened.execution.price,
                quantity=2,
            ),
            TimelineExecutionCommand(
                execution_id=None,
                execution_type="CLOSE",
                executed_at=BAR_END + timedelta(minutes=40),
                price=Decimal("1250"),
                quantity=2,
            ),
        ),
    )

    assert result.position.remaining_quantity == 0
    assert result.episode.close_reason == "EXECUTION_NET_ZERO"
    assert _utc(result.episode.closed_at) == BAR_END + timedelta(minutes=40)
    assert result.episode.roll_reference_exit_price is None
    assert result.episode.roll_reference_bar_end is None
    assert result.executions[0].id == opened.execution.id
    assert result.executions[0].trigger_decision_id == opened.decision.id
    assert result.executions[-1].execution_type == "CLOSE"
    assert result.executions[-1].trigger_decision_id is None


def test_dominant_roll_timeline_correction_cannot_reopen_episode(
    session: Session,
) -> None:
    service = _service(session)
    opened = service.record_executed(_event(session).id, _executed(quantity=2))
    episode = session.get(TradeEpisode, opened.episode.id)
    assert episode is not None
    episode.closed_at = BAR_END + timedelta(minutes=30)
    episode.close_reason = "DOMINANT_ROLL"
    episode.roll_reference_exit_price = Decimal("1258")
    episode.roll_reference_bar_end = BAR_END + timedelta(minutes=30)
    session.commit()

    with pytest.raises(
        ExecutionReviewDomainError,
        match="^EXECUTION_CORRECTION_CONFLICT$",
    ):
        service.replace_execution_timeline(
            episode.id,
            (
                TimelineExecutionCommand(
                    execution_id=opened.execution.id,
                    execution_type="OPEN",
                    executed_at=opened.execution.executed_at,
                    price=opened.execution.price,
                    quantity=2,
                ),
            ),
        )

    unchanged = session.get(TradeEpisode, episode.id)
    assert unchanged is not None
    assert unchanged.close_reason == "DOMINANT_ROLL"
    assert unchanged.roll_reference_exit_price == Decimal("1258")


def test_read_models_classify_pending_open_pending_review_and_done(
    session: Session,
) -> None:
    service = _service(session)
    pending = _event(session, symbol="p", contract="P2609", bar_end=BAR_END)
    not_event = _event(
        session,
        symbol="n",
        contract="N2609",
        bar_end=BAR_END + timedelta(minutes=1),
    )
    not_decision = service.record_not_executed(
        not_event.id,
        NotExecutedCommand(primary_reason="TOO_LATE"),
    )
    open_result = service.record_executed(
        _event(
            session,
            symbol="o",
            contract="O2609",
            bar_end=BAR_END + timedelta(minutes=2),
        ).id,
        _executed(executed_at=BAR_END + timedelta(minutes=5)),
    )
    pending_review = service.record_executed(
        _event(
            session,
            symbol="r",
            contract="R2609",
            bar_end=BAR_END + timedelta(minutes=3),
        ).id,
        _executed(executed_at=BAR_END + timedelta(minutes=6), quantity=1),
    )
    service.append_execution(
        pending_review.episode.id,
        ExecutionCommand(
            execution_type="CLOSE",
            executed_at=BAR_END + timedelta(minutes=7),
            price=Decimal("1260"),
            quantity=1,
        ),
    )
    done = service.record_executed(
        _event(
            session,
            symbol="d",
            contract="D2609",
            bar_end=BAR_END + timedelta(minutes=4),
        ).id,
        _executed(executed_at=BAR_END + timedelta(minutes=7), quantity=1),
    )
    service.append_execution(
        done.episode.id,
        ExecutionCommand(
            execution_type="CLOSE",
            executed_at=BAR_END + timedelta(minutes=8),
            price=Decimal("1260"),
            quantity=1,
        ),
    )
    service.submit_review(
        done.episode.id,
        _review_command(
            entry_tags=("TOO_LATE",),
            holding_tags=("COULD_NOT_HOLD",),
            exit_tags=("STOP_DELAYED",),
            psychology_tags=("HESITATION",),
        ),
    )

    items = tuple(
        item
        for state in ("pending_decision", "open", "pending_review", "done")
        for item in service.list_items(state=state)
    )
    assert {(item.item_kind, item.state, item.event_id) for item in items} == {
        ("decision", "pending_decision", pending.id),
        ("decision", "done", not_event.id),
        ("episode", "open", open_result.decision.alert_event_id),
        ("episode", "pending_review", pending_review.decision.alert_event_id),
        ("episode", "done", done.decision.alert_event_id),
    }
    done_items = service.list_items(state="done")
    assert {(item.item_kind, item.decision_id, item.episode_id) for item in done_items} == {
        ("decision", not_decision.id, None),
        ("episode", done.decision.id, done.episode.id),
    }
    requested_event_ids = (
        pending.id,
        not_event.id,
        open_result.decision.alert_event_id,
        pending_review.decision.alert_event_id,
        done.decision.alert_event_id,
    )
    event_states = {
        row.event_id: row.state
        for row in service.event_states(requested_event_ids)
    }
    assert event_states == {
        pending.id: "pending_decision",
        not_event.id: "done",
        open_result.decision.alert_event_id: "open",
        pending_review.decision.alert_event_id: "pending_review",
        done.decision.alert_event_id: "done",
    }

    assert [item.event_id for item in service.list_items(
        state="pending_decision",
        symbol=" P ",
        direction="SHORT",
        frequency="15m",
        start_trading_day=date(2099, 1, 1),
        end_trading_day=date(2099, 1, 2),
    )] == [pending.id]
    assert [item.episode_id for item in service.list_items(
        state="open",
        symbol="o",
        direction="SHORT",
        frequency="15m",
        start_trading_day=date(2099, 1, 1),
        end_trading_day=date(2099, 1, 2),
    )] == [open_result.episode.id]
    assert [item.episode_id for item in service.list_items(
        state="pending_review",
        symbol="r",
        direction="SHORT",
        frequency="15m",
        start_trading_day=date(2099, 1, 1),
        end_trading_day=date(2099, 1, 2),
    )] == [pending_review.episode.id]
    assert [item.episode_id for item in service.list_items(
        state="done",
        symbol="d",
        direction="SHORT",
        frequency="15m",
        start_trading_day=date(2026, 8, 15),
        end_trading_day=date(2026, 8, 15),
    )] == [done.episode.id]


def test_event_states_are_bounded_ordered_and_deduplicated(
    session: Session,
) -> None:
    first = _event(session, symbol="a", contract="A2609")
    second = _event(
        session,
        symbol="b",
        contract="B2609",
        bar_end=BAR_END + timedelta(minutes=1),
    )
    unrequested = _event(
        session,
        symbol="c",
        contract="C2609",
        bar_end=BAR_END + timedelta(minutes=2),
    )

    states = _service(session).event_states((second.id, first.id, second.id))

    assert [row.event_id for row in states] == [second.id, first.id]
    assert unrequested.id not in {row.event_id for row in states}


def test_event_states_missing_id_fails_the_batch(session: Session) -> None:
    event = _event(session)

    with pytest.raises(
        ExecutionReviewDomainError,
        match="^EXECUTION_REVIEW_EVENT_NOT_FOUND$",
    ) as captured:
        _service(session).event_states((event.id, event.id + 1000))

    assert captured.value.status_code == 404


@pytest.mark.parametrize(
    ("event_changes", "code"),
    [
        ({"rule_code": "htdy_original_15m"}, "EVENT_NOT_EXECUTION_REVIEW_ELIGIBLE"),
        ({"result_codes": ["buy", "sell"]}, "EVENT_DIRECTION_INVALID"),
    ],
)
def test_event_states_reject_ineligible_or_invalid_direction(
    session: Session,
    event_changes: dict[str, object],
    code: str,
) -> None:
    event = _event(session, **event_changes)

    with pytest.raises(ExecutionReviewDomainError, match=f"^{code}$") as captured:
        _service(session).event_states((event.id,))

    assert captured.value.status_code == 422


def test_done_items_use_alert_trading_day_not_bar_end_natural_date(
    session: Session,
) -> None:
    event = _event(
        session,
        trading_day=date(2026, 8, 15),
        bar_end=datetime(2026, 8, 14, 17, 0, tzinfo=UTC),
    )
    _service(session).record_not_executed(
        event.id,
        NotExecutedCommand(primary_reason="TOO_LATE"),
    )

    matching = _service(session).list_items(
        state="done",
        start_trading_day=date(2026, 8, 15),
        end_trading_day=date(2026, 8, 15),
    )
    natural_date = _service(session).list_items(
        state="done",
        start_trading_day=date(2026, 8, 14),
        end_trading_day=date(2026, 8, 14),
    )

    assert [item.event_id for item in matching] == [event.id]
    assert natural_date == ()


def test_zero_stats_denominators_are_undefined(session: Session) -> None:
    empty = _service(session).stats()

    assert empty.opportunities.eligible_events == 0
    assert empty.opportunities.decision_completion_rate is None
    assert empty.opportunities.execution_rate is None

    _event(session)
    pending = _service(session).stats()

    assert pending.opportunities.eligible_events == 1
    assert pending.opportunities.processed_events == 0
    assert pending.opportunities.decision_completion_rate == Decimal("0")
    assert pending.opportunities.execution_rate is None


def test_episode_detail_returns_origin_event_and_only_trigger_decisions_in_order(
    session: Session,
) -> None:
    service = _service(session)
    notification_attempted_at = BAR_END + timedelta(seconds=5)
    origin_event = _event(
        session,
        lower_tf_confirmation=True,
        notification_attempted_at=notification_attempted_at,
    )
    opened = service.record_executed(origin_event.id, _executed(quantity=1))
    service.append_execution(
        opened.episode.id,
        ExecutionCommand(
            execution_type="ADD",
            executed_at=BAR_END + timedelta(minutes=4),
            price=Decimal("1267"),
            quantity=1,
        ),
    )
    later_one = service.record_executed(
        _event(session, bar_end=BAR_END + timedelta(minutes=5)).id,
        _executed(
            executed_at=BAR_END + timedelta(minutes=8),
            price=Decimal("1266"),
            quantity=1,
        ),
    )
    service.append_execution(
        opened.episode.id,
        ExecutionCommand(
            execution_type="ADD",
            executed_at=BAR_END + timedelta(minutes=9),
            price=Decimal("1265"),
            quantity=1,
        ),
    )
    later_two = service.record_executed(
        _event(session, bar_end=BAR_END + timedelta(minutes=10)).id,
        _executed(
            executed_at=BAR_END + timedelta(minutes=13),
            price=Decimal("1264"),
            quantity=1,
        ),
    )
    unrelated_not_executed = service.record_not_executed(
        _event(session, bar_end=BAR_END + timedelta(minutes=14)).id,
        NotExecutedCommand(primary_reason="TOO_LATE"),
    )
    unrelated_episode = service.record_executed(
        _event(
            session,
            symbol="a",
            contract="A2609",
            bar_end=BAR_END + timedelta(minutes=15),
        ).id,
        _executed(
            executed_at=BAR_END + timedelta(minutes=18),
            quantity=1,
        ),
    )

    detail = service.episode_detail(opened.episode.id)

    assert detail.origin_event.id == origin_event.id
    assert detail.origin_event.rule_code == "subing_entry_signal_v1"
    assert detail.origin_event.symbol == "jm"
    assert detail.origin_event.contract == "JM2609"
    assert detail.origin_event.trading_day == date(2026, 8, 15)
    assert detail.origin_event.frequency == "15m"
    assert detail.origin_event.bar_end == origin_event.bar_end
    assert detail.origin_event.result_codes == ("sell",)
    assert detail.origin_event.lower_tf_confirmation is True
    assert detail.origin_event.detected_at == origin_event.detected_at
    assert _utc(detail.origin_event.notification_attempted_at) == _utc(
        notification_attempted_at
    )
    assert [decision.id for decision in detail.decisions] == [
        opened.decision.id,
        later_one.decision.id,
        later_two.decision.id,
    ]
    assert [execution.trigger_decision_id for execution in detail.executions] == [
        opened.decision.id,
        None,
        later_one.decision.id,
        None,
        later_two.decision.id,
    ]
    assert unrelated_not_executed.id not in {row.id for row in detail.decisions}
    assert unrelated_episode.decision.id not in {row.id for row in detail.decisions}


def test_read_path_database_failure_is_stable_and_redacted(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_execute(*_: object, **__: object) -> object:
        raise SQLAlchemyError("sensitive SQL and connection details")

    monkeypatch.setattr(session, "execute", fail_execute)

    with pytest.raises(
        ExecutionReviewDomainError,
        match="^EXECUTION_REVIEW_PERSIST_FAILED$",
    ) as captured:
        _service(session).list_items(state="done")

    assert captured.value.status_code == 503
    assert "sensitive" not in str(captured.value).lower()


def test_stats_separate_opportunities_from_episode_states(session: Session) -> None:
    service = _service(session)
    _event(session, symbol="p", contract="P2609", bar_end=BAR_END)
    service.record_not_executed(
        _event(
            session,
            symbol="n",
            contract="N2609",
            bar_end=BAR_END + timedelta(minutes=1),
        ).id,
        NotExecutedCommand(primary_reason="TOO_LATE"),
    )
    open_result = service.record_executed(
        _event(
            session,
            symbol="o",
            contract="O2609",
            bar_end=BAR_END + timedelta(minutes=2),
        ).id,
        _executed(executed_at=BAR_END + timedelta(minutes=5)),
    )
    pending_review = service.record_executed(
        _event(
            session,
            symbol="r",
            contract="R2609",
            bar_end=BAR_END + timedelta(minutes=3),
        ).id,
        _executed(executed_at=BAR_END + timedelta(minutes=6), quantity=1),
    )
    done = service.record_executed(
        _event(
            session,
            symbol="d",
            contract="D2609",
            bar_end=BAR_END + timedelta(minutes=4),
        ).id,
        _executed(executed_at=BAR_END + timedelta(minutes=7), quantity=1),
    )
    for result, minute in ((pending_review, 8), (done, 9)):
        service.append_execution(
            result.episode.id,
            ExecutionCommand(
                execution_type="CLOSE",
                executed_at=BAR_END + timedelta(minutes=minute),
                price=Decimal("1260"),
                quantity=1,
            ),
        )
    service.submit_review(
        done.episode.id,
        _review_command(
            entry_tags=("TOO_LATE",),
            holding_tags=("COULD_NOT_HOLD",),
            exit_tags=("STOP_DELAYED",),
            psychology_tags=("HESITATION",),
        ),
    )
    old_bar_end = BAR_END - timedelta(days=1)
    service.record_executed(
        _event(
            session,
            symbol="x",
            contract="X2609",
            trading_day=date(2026, 8, 14),
            bar_end=old_bar_end,
        ).id,
        _executed(executed_at=old_bar_end + timedelta(minutes=3)),
    )
    old_done = service.record_executed(
        _event(
            session,
            symbol="y",
            contract="Y2609",
            trading_day=date(2026, 8, 14),
            bar_end=old_bar_end + timedelta(minutes=1),
        ).id,
        _executed(
            executed_at=old_bar_end + timedelta(minutes=4),
            quantity=1,
        ),
    )
    service.append_execution(
        old_done.episode.id,
        ExecutionCommand(
            execution_type="CLOSE",
            executed_at=old_bar_end + timedelta(minutes=5),
            price=Decimal("1260"),
            quantity=1,
        ),
    )
    service.submit_review(old_done.episode.id, _review_command())

    stats = service.stats(
        trading_day_from=date(2026, 8, 15),
        trading_day_to=date(2026, 8, 15),
    )

    assert stats.opportunities.eligible_events == 5
    assert stats.opportunities.processed_events == 4
    assert stats.opportunities.pending_events == 1
    assert stats.opportunities.executed_decisions == 3
    assert stats.opportunities.not_executed_decisions == 1
    assert stats.opportunities.decision_completion_rate == Decimal("0.8")
    assert stats.opportunities.execution_rate == Decimal("0.75")
    assert stats.opportunities.primary_reason_counts == {"TOO_LATE": 1}
    assert stats.episode_states.open_episodes == 2
    assert stats.episode_states.pending_review_episodes == 1
    assert stats.episode_states.done_episodes == 1
    assert stats.review_issue_top.entry == {"TOO_LATE": 1}
    assert stats.review_issue_top.holding == {"COULD_NOT_HOLD": 1}
    assert stats.review_issue_top.exit_risk == {"STOP_DELAYED": 1}
    assert stats.review_issue_top.psychology == {"HESITATION": 1}
    assert open_result.episode.id != done.episode.id

    filtered = service.stats(
        trading_day_from=date(2026, 8, 15),
        trading_day_to=date(2026, 8, 15),
        symbol="o",
        direction="SHORT",
        frequency="15m",
    )
    assert filtered.opportunities.eligible_events == 1
    assert filtered.opportunities.processed_events == 1
    assert filtered.episode_states.open_episodes == 1
    assert filtered.episode_states.pending_review_episodes == 0
    assert filtered.episode_states.done_episodes == 0
    assert filtered.review_issue_top.entry == {}


@pytest.mark.isolated_postgresql
def test_postgresql_open_episode_race_rolls_back_loser_without_automatic_add(
    postgres_engine: Engine,
) -> None:
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    with factory() as seed:
        first = _event(seed, bar_end=BAR_END)
        second = _event(seed, bar_end=BAR_END + timedelta(minutes=15))
        event_ids = (first.id, second.id)

    results = _race_open_events(factory, event_ids)

    assert sorted(code for _, code in results) == [
        "OPEN_EPISODE_CONFLICT",
        "created",
    ]
    with factory() as check:
        assert _count(check, TradeDecision) == 1
        assert _count(check, TradeEpisode) == 1
        assert _count(check, TradeExecution) == 1
        loser_id = next(
            event_id
            for event_id, code in results
            if code == "OPEN_EPISODE_CONFLICT"
        )
        resubmitted = _service(check).record_executed(
            loser_id,
            _executed(
                executed_at=BAR_END + timedelta(minutes=22),
                quantity=1,
            ),
        )
        assert resubmitted.execution.execution_type == "ADD"
        assert resubmitted.execution.sequence_no == 2
        assert _count(check, TradeDecision) == 2
        assert _count(check, TradeEpisode) == 1
        assert _count(check, TradeExecution) == 2


@pytest.mark.parametrize(
    ("second_changes", "expected_conflict"),
    [
        ({"result_codes": ["buy"]}, "OPPOSITE_EPISODE_OPEN"),
        ({"contract": "JM2701"}, "OPEN_EPISODE_CONFLICT"),
        (
            {"contract": "JM2701", "result_codes": ["buy"]},
            "OPEN_EPISODE_CONFLICT",
        ),
    ],
)
@pytest.mark.isolated_postgresql
def test_postgresql_open_race_reclassifies_winner_business_facts(
    postgres_engine: Engine,
    second_changes: dict[str, object],
    expected_conflict: str,
) -> None:
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    with factory() as seed:
        first = _event(seed, bar_end=BAR_END)
        second = _event(
            seed,
            bar_end=BAR_END + timedelta(minutes=15),
            **second_changes,
        )
        event_ids = (first.id, second.id)

    results = _race_open_events(factory, event_ids)

    assert sorted(code for _, code in results) == [
        expected_conflict,
        "created",
    ]
    with factory() as check:
        assert _count(check, TradeDecision) == 1
        assert _count(check, TradeEpisode) == 1
        assert _count(check, TradeExecution) == 1


@pytest.mark.isolated_postgresql
def test_postgresql_disposition_correction_open_race_reclassifies_winner(
    postgres_engine: Engine,
) -> None:
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    with factory() as seed:
        first = _service(seed).record_not_executed(
            _event(seed, bar_end=BAR_END).id,
            NotExecutedCommand(primary_reason="TOO_LATE"),
        )
        second = _service(seed).record_not_executed(
            _event(
                seed,
                bar_end=BAR_END + timedelta(minutes=15),
                result_codes=["buy"],
            ).id,
            NotExecutedCommand(primary_reason="TOO_LATE"),
        )
        decision_ids = (first.id, second.id)
    barrier = Barrier(2)

    def race(decision_id: int, minute: int) -> str:
        with factory() as local_session:
            intercepted = False

            @sqlalchemy_event.listens_for(
                local_session,
                "do_orm_execute",
                retval=True,
            )
            def synchronize_open_lookup(state: object):
                nonlocal intercepted
                statement = str(state.statement)  # type: ignore[attr-defined]
                if (
                    not intercepted
                    and "trade_episodes" in statement
                    and "closed_at IS NULL" in statement
                ):
                    intercepted = True
                    result = state.invoke_statement()  # type: ignore[attr-defined]
                    barrier.wait(timeout=10)
                    return result
                return state.invoke_statement()  # type: ignore[attr-defined]

            try:
                _service(local_session).correct_disposition(
                    decision_id,
                    DispositionCorrectionCommand(
                        target_disposition="EXECUTED",
                        executed_at=BAR_END + timedelta(minutes=minute),
                        price=Decimal("1260"),
                        quantity=1,
                        execution_reason_tags=("KEY_LEVEL_BREAKOUT",),
                    ),
                )
                return "created"
            except ExecutionReviewDomainError as exc:
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(race, decision_ids, (30, 31)))

    assert sorted(results) == ["OPPOSITE_EPISODE_OPEN", "created"]
    with factory() as check:
        assert _count(check, TradeDecision) == 2
        assert _count(check, TradeEpisode) == 1
        assert _count(check, TradeExecution) == 1


@pytest.mark.isolated_postgresql
def test_postgresql_episode_lock_serializes_concurrent_manual_appends(
    postgres_engine: Engine,
) -> None:
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    with factory() as seed:
        opened = _service(seed).record_executed(
            _event(seed).id,
            _executed(quantity=1),
        )
        episode_id = opened.episode.id
    barrier = Barrier(2)

    def append(minute: int) -> int:
        with factory() as local_session:
            barrier.wait(timeout=10)
            result = _service(local_session).append_execution(
                episode_id,
                ExecutionCommand(
                    execution_type="ADD",
                    executed_at=BAR_END + timedelta(minutes=minute),
                    price=Decimal("1260"),
                    quantity=1,
                ),
            )
            return result.execution.sequence_no

    with ThreadPoolExecutor(max_workers=2) as executor:
        sequences = tuple(executor.map(append, (5, 6)))

    assert sorted(sequences) == [2, 3]
    with factory() as check:
        rows = check.scalars(
            select(TradeExecution)
            .where(TradeExecution.episode_id == episode_id)
            .order_by(TradeExecution.sequence_no)
        ).all()
        assert [row.sequence_no for row in rows] == [1, 2, 3]


@pytest.mark.isolated_postgresql
def test_postgresql_decision_update_serializes_with_disposition_correction(
    postgres_engine: Engine,
) -> None:
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    with factory() as seed:
        opened = _service(seed).record_executed(_event(seed).id, _executed())
        decision_id = opened.decision.id
    update_selected = Event()
    correction_started = Event()
    correction_finished = Event()

    def update() -> None:
        with factory() as local_session:
            intercepted = False

            @sqlalchemy_event.listens_for(
                local_session,
                "do_orm_execute",
                retval=True,
            )
            def hold_after_decision_read(state: object):
                nonlocal intercepted
                statement = str(state.statement)  # type: ignore[attr-defined]
                if not intercepted and "FROM trade_decisions" in statement:
                    intercepted = True
                    result = state.invoke_statement()  # type: ignore[attr-defined]
                    update_selected.set()
                    if "FOR UPDATE" in statement:
                        assert correction_started.wait(timeout=10)
                    else:
                        assert correction_finished.wait(timeout=10)
                    return result
                return state.invoke_statement()  # type: ignore[attr-defined]

            _service(local_session).update_decision(
                decision_id,
                DecisionUpdateCommand(
                    first_viewed_at=None,
                    decided_at=BAR_END + timedelta(minutes=2),
                    primary_not_execute_reason=None,
                    secondary_not_execute_reasons=(),
                    note="updated",
                    execution_reason_tags=("PULLBACK_RECONFIRMED",),
                    planned_stop_price=Decimal("1300"),
                    stop_basis="EMA",
                ),
            )

    def correct() -> None:
        assert update_selected.wait(timeout=10)
        correction_started.set()
        try:
            with factory() as local_session:
                _service(local_session).correct_disposition(
                    decision_id,
                    DispositionCorrectionCommand(
                        target_disposition="NOT_EXECUTED",
                        primary_reason="TOO_LATE",
                    ),
                )
        finally:
            correction_finished.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        update_future = executor.submit(update)
        correction_future = executor.submit(correct)
        update_future.result(timeout=15)
        correction_future.result(timeout=15)

    with factory() as check:
        decision = check.get(TradeDecision, decision_id)
        assert decision is not None
        assert decision.disposition == "NOT_EXECUTED"
        assert decision.primary_not_execute_reason == "TOO_LATE"
        assert decision.secondary_not_execute_reasons == []
        assert decision.execution_reason_tags == []
        assert decision.planned_stop_price is None
        assert decision.stop_basis is None


@pytest.mark.isolated_postgresql
@pytest.mark.parametrize("correction_kind", ["execution", "timeline"])
def test_postgresql_causal_corrections_serialize_decision_and_execution(
    postgres_engine: Engine,
    correction_kind: str,
) -> None:
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    with factory() as seed:
        opened = _service(seed).record_executed(
            _event(seed).id,
            _executed(
                decided_at=BAR_END + timedelta(minutes=2),
                executed_at=BAR_END + timedelta(minutes=5),
                quantity=1,
            ),
        )
        decision_id = opened.decision.id
        execution_id = opened.execution.id
        episode_id = opened.episode.id
    causal_read = Event()
    decision_started = Event()
    decision_finished = Event()

    def correct_execution() -> str:
        with factory() as local_session:
            intercepted = False

            @sqlalchemy_event.listens_for(
                local_session,
                "do_orm_execute",
                retval=True,
            )
            def hold_after_decision_read(state: object):
                nonlocal intercepted
                statement = str(state.statement)  # type: ignore[attr-defined]
                if not intercepted and "trade_decisions" in statement:
                    intercepted = True
                    result = state.invoke_statement()  # type: ignore[attr-defined]
                    causal_read.set()
                    if "FOR UPDATE" in statement:
                        assert decision_started.wait(timeout=10)
                    else:
                        assert decision_finished.wait(timeout=10)
                    return result
                return state.invoke_statement()  # type: ignore[attr-defined]

            try:
                if correction_kind == "execution":
                    _service(local_session).update_execution(
                        execution_id,
                        ExecutionUpdateCommand(
                            executed_at=BAR_END + timedelta(minutes=3),
                            price=Decimal("1268.5"),
                        ),
                    )
                else:
                    _service(local_session).replace_execution_timeline(
                        episode_id,
                        (
                            TimelineExecutionCommand(
                                execution_id=execution_id,
                                execution_type="OPEN",
                                executed_at=BAR_END + timedelta(minutes=3),
                                price=Decimal("1268.5"),
                                quantity=1,
                            ),
                        ),
                    )
                return "updated"
            except ExecutionReviewDomainError as exc:
                return exc.code

    def correct_decision() -> str:
        assert causal_read.wait(timeout=10)
        decision_started.set()
        try:
            with factory() as local_session:
                try:
                    _service(local_session).update_decision(
                        decision_id,
                        DecisionUpdateCommand(
                            first_viewed_at=None,
                            decided_at=BAR_END + timedelta(minutes=4),
                            primary_not_execute_reason=None,
                            secondary_not_execute_reasons=(),
                            note=None,
                            execution_reason_tags=("KEY_LEVEL_BREAKOUT",),
                            planned_stop_price=None,
                            stop_basis=None,
                        ),
                    )
                    return "updated"
                except ExecutionReviewDomainError as exc:
                    return exc.code
        finally:
            decision_finished.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        execution_future = executor.submit(correct_execution)
        decision_future = executor.submit(correct_decision)
        results = (execution_future.result(timeout=15), decision_future.result(timeout=15))

    assert sorted(results) == ["DECISION_AFTER_EXECUTION", "updated"]
    with factory() as check:
        decision = check.get(TradeDecision, decision_id)
        execution = check.get(TradeExecution, execution_id)
        assert decision is not None
        assert execution is not None
        assert _utc(decision.decided_at) <= _utc(execution.executed_at)


@pytest.mark.isolated_postgresql
def test_postgresql_event_states_uses_one_consistent_statement_snapshot(
    postgres_engine: Engine,
) -> None:
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    with factory() as seed:
        event_id = _event(seed).id
    snapshot_read = Event()
    writer_finished = Event()

    def read_states() -> str:
        with factory() as local_session:
            intercepted = False

            @sqlalchemy_event.listens_for(
                local_session,
                "do_orm_execute",
                retval=True,
            )
            def pause_after_snapshot(state: object):
                nonlocal intercepted
                statement = str(state.statement)  # type: ignore[attr-defined]
                old_final_read = (
                    "FROM trade_reviews" in statement
                    and "trade_reviews.episode_id" in statement
                )
                new_single_read = (
                    "FROM alert_events" in statement
                    and "LEFT OUTER JOIN trade_decisions" in statement
                )
                if not intercepted and (old_final_read or new_single_read):
                    intercepted = True
                    result = state.invoke_statement()  # type: ignore[attr-defined]
                    snapshot_read.set()
                    assert writer_finished.wait(timeout=10)
                    return result
                return state.invoke_statement()  # type: ignore[attr-defined]

            try:
                states = _service(local_session).event_states((event_id,))
                return states[0].state
            except ExecutionReviewDomainError as exc:
                return exc.code

    def write_decision() -> None:
        assert snapshot_read.wait(timeout=10)
        try:
            with factory() as local_session:
                _service(local_session).record_executed(
                    event_id,
                    _executed(quantity=1),
                )
        finally:
            writer_finished.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        read_future = executor.submit(read_states)
        write_future = executor.submit(write_decision)
        state = read_future.result(timeout=15)
        write_future.result(timeout=15)

    assert state == "pending_decision"


@pytest.mark.isolated_postgresql
@pytest.mark.parametrize("read_kind", ["items", "stats"])
def test_postgresql_read_models_do_not_mix_disposition_correction_snapshots(
    postgres_engine: Engine,
    read_kind: str,
) -> None:
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    with factory() as seed:
        decision = _service(seed).record_not_executed(
            _event(seed).id,
            NotExecutedCommand(primary_reason="TOO_LATE"),
        )
        decision_id = decision.id
    snapshot_read = Event()
    writer_finished = Event()

    def read_model() -> object:
        with factory() as local_session:
            intercepted = False

            @sqlalchemy_event.listens_for(
                local_session,
                "do_orm_execute",
                retval=True,
            )
            def pause_after_snapshot(state: object):
                nonlocal intercepted
                statement = str(state.statement)  # type: ignore[attr-defined]
                old_decision_read = (
                    "FROM trade_decisions" in statement
                    and "alert_event_id IN" in statement
                )
                new_single_read = (
                    "FROM alert_events" in statement
                    and "LEFT OUTER JOIN trade_decisions" in statement
                    and "LEFT OUTER JOIN trade_episodes" in statement
                )
                if not intercepted and (old_decision_read or new_single_read):
                    intercepted = True
                    result = state.invoke_statement()  # type: ignore[attr-defined]
                    snapshot_read.set()
                    assert writer_finished.wait(timeout=10)
                    return result
                return state.invoke_statement()  # type: ignore[attr-defined]

            if read_kind == "items":
                return tuple(
                    (item.item_kind, item.state)
                    for item in _service(local_session).list_items(state="done")
                )
            stats = _service(local_session).stats()
            return (
                stats.opportunities.not_executed_decisions,
                stats.episode_states.open_episodes,
            )

    def correct_disposition() -> None:
        assert snapshot_read.wait(timeout=10)
        try:
            with factory() as local_session:
                _service(local_session).correct_disposition(
                    decision_id,
                    DispositionCorrectionCommand(
                        target_disposition="EXECUTED",
                        executed_at=BAR_END + timedelta(minutes=5),
                        price=Decimal("1260"),
                        quantity=1,
                        execution_reason_tags=("KEY_LEVEL_BREAKOUT",),
                    ),
                )
        finally:
            writer_finished.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        read_future = executor.submit(read_model)
        write_future = executor.submit(correct_disposition)
        observed = read_future.result(timeout=15)
        write_future.result(timeout=15)

    if read_kind == "items":
        assert observed == (("decision", "done"),)
    else:
        assert observed == (1, 0)


@pytest.mark.isolated_postgresql
def test_postgresql_episode_detail_uses_one_statement_snapshot(
    postgres_engine: Engine,
) -> None:
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    with factory() as seed:
        opened = _service(seed).record_executed(
            _event(seed).id,
            _executed(quantity=2),
        )
        episode_id = opened.episode.id
        origin_event_id = opened.decision.alert_event_id
        origin_decision_id = opened.decision.id
        later_event_id = _event(
            seed,
            bar_end=BAR_END + timedelta(minutes=5),
        ).id
    snapshot_read = Event()
    writer_finished = Event()

    def read_detail() -> tuple[int, int, tuple[int, ...], int]:
        with factory() as local_session:
            intercepted = False

            @sqlalchemy_event.listens_for(
                local_session,
                "do_orm_execute",
                retval=True,
            )
            def pause_after_snapshot(state: object):
                nonlocal intercepted
                statement = str(state.statement)  # type: ignore[attr-defined]
                old_execution_read = (
                    "FROM trade_executions" in statement
                    and "ORDER BY trade_executions.sequence_no" in statement
                )
                new_single_read = (
                    "FROM trade_episodes" in statement
                    and "LEFT OUTER JOIN trade_executions" in statement
                    and "LEFT OUTER JOIN trade_reviews" in statement
                )
                if not intercepted and (old_execution_read or new_single_read):
                    intercepted = True
                    result = state.invoke_statement()  # type: ignore[attr-defined]
                    snapshot_read.set()
                    assert writer_finished.wait(timeout=10)
                    return result
                return state.invoke_statement()  # type: ignore[attr-defined]

            detail = _service(local_session).episode_detail(episode_id)
            return (
                sum(row.quantity for row in detail.executions),
                detail.position.remaining_quantity,
                tuple(row.id for row in detail.decisions),
                detail.origin_event.id,
            )

    def append_signal_execution() -> None:
        assert snapshot_read.wait(timeout=10)
        try:
            with factory() as local_session:
                _service(local_session).record_executed(
                    later_event_id,
                    _executed(
                        executed_at=BAR_END + timedelta(minutes=8),
                        price=Decimal("1260"),
                        quantity=1,
                    ),
                )
        finally:
            writer_finished.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        read_future = executor.submit(read_detail)
        write_future = executor.submit(append_signal_execution)
        observed = read_future.result(timeout=15)
        write_future.result(timeout=15)

    assert observed == (2, 2, (origin_decision_id,), origin_event_id)


@pytest.mark.parametrize(
    ("constraint_name", "code"),
    [
        ("uq_trade_decisions_alert_event", "DECISION_ALREADY_EXISTS"),
        ("uq_trade_episodes_origin_decision", "DECISION_ALREADY_EXISTS"),
        ("uq_trade_episodes_symbol_open", "OPEN_EPISODE_CONFLICT"),
        ("uq_trade_executions_trigger_decision", "TRIGGER_DECISION_ALREADY_USED"),
        ("uq_trade_executions_episode_sequence", "EXECUTION_TOPOLOGY_INVALID"),
        ("uq_trade_reviews_episode", "REVIEW_ALREADY_EXISTS"),
    ],
)
def test_integrity_error_whitelist_maps_only_approved_constraints(
    constraint_name: str,
    code: str,
) -> None:
    mapped = ExecutionReviewService._integrity_error(
        _integrity_error(constraint_name)
    )

    assert mapped.code == code
    assert mapped.status_code == 409


def test_unknown_integrity_error_is_redacted_persistence_failure() -> None:
    mapped = ExecutionReviewService._integrity_error(
        _integrity_error("ck_sensitive_internal_constraint")
    )

    assert mapped.code == "EXECUTION_REVIEW_PERSIST_FAILED"
    assert mapped.status_code == 503
    assert str(mapped) == "EXECUTION_REVIEW_PERSIST_FAILED"
    assert "sensitive" not in str(mapped).lower()


def _service(session: Session, *, now: datetime = SERVER_NOW) -> ExecutionReviewService:
    return ExecutionReviewService(
        session,
        multipliers={"jm": Decimal("60")},
        clock=lambda: now,
    )


def _executed(**changes: object) -> ExecutedCommand:
    values: dict[str, object] = {
        "executed_at": BAR_END + timedelta(minutes=3),
        "price": Decimal("1268.5"),
        "quantity": 2,
        "execution_reason_tags": ("KEY_LEVEL_BREAKOUT",),
    }
    values.update(changes)
    return ExecutedCommand(**values)  # type: ignore[arg-type]


def _review_command(**changes: object) -> ReviewCommand:
    values: dict[str, object] = {
        "signal_execution_adherence": "ALIGNED",
        "entry_tags": ("REASONABLE",),
        "holding_tags": ("NORMAL",),
        "exit_tags": ("NORMAL",),
        "market_context_tags": ("TREND",),
        "psychology_tags": ("NONE",),
        "summary": "reviewed",
    }
    values.update(changes)
    return ReviewCommand(**values)  # type: ignore[arg-type]


def _event(session: Session, **changes: object) -> AlertEvent:
    rule_code = str(changes.pop("rule_code", "subing_entry_signal_v1"))
    result_codes = changes.pop("result_codes", ["sell"])
    trading_day = changes.pop("trading_day", date(2026, 8, 15))
    contract = changes.pop("contract", "JM2609")
    frequency = changes.pop("frequency", "15m")
    symbol = str(changes.pop("symbol", "jm"))
    bar_end = changes.pop("bar_end", BAR_END)
    lower_tf_confirmation = bool(changes.pop("lower_tf_confirmation", False))
    detected_at = changes.pop("detected_at", bar_end + timedelta(seconds=1))
    notification_attempted_at = changes.pop("notification_attempted_at", None)
    if changes:
        raise AssertionError(f"unknown event changes: {changes}")
    rule = session.scalar(
        select(AlertRule).where(AlertRule.rule_code == rule_code)
    )
    if rule is None:
        rule = AlertRule(
            rule_code=rule_code,
            enabled=True,
            scope_products=[symbol],
            created_at=BAR_END,
            updated_at=BAR_END,
        )
    event = AlertEvent(
        rule=rule,
        symbol=symbol,
        contract=contract,
        trading_day=trading_day,
        frequency=frequency,
        bar_end=bar_end,
        result_codes=result_codes,
        lower_tf_confirmation=lower_tf_confirmation,
        detected_at=detected_at,
        notification_attempted_at=notification_attempted_at,
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


def _count(session: Session, model: type[object]) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _reset_postgres(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))


def _race_open_events(
    factory: sessionmaker[Session],
    event_ids: tuple[int, int],
) -> tuple[tuple[int, str], ...]:
    barrier = Barrier(2)

    def race(event_id: int, minute: int) -> tuple[int, str]:
        with factory() as local_session:
            intercepted = False

            @sqlalchemy_event.listens_for(
                local_session,
                "do_orm_execute",
                retval=True,
            )
            def synchronize_open_lookup(state: object):
                nonlocal intercepted
                statement = str(state.statement)  # type: ignore[attr-defined]
                if (
                    not intercepted
                    and "trade_episodes" in statement
                    and "closed_at IS NULL" in statement
                ):
                    intercepted = True
                    result = state.invoke_statement()  # type: ignore[attr-defined]
                    barrier.wait(timeout=10)
                    return result
                return state.invoke_statement()  # type: ignore[attr-defined]

            try:
                _service(local_session).record_executed(
                    event_id,
                    _executed(
                        executed_at=BAR_END + timedelta(minutes=minute),
                        quantity=1,
                    ),
                )
                return event_id, "created"
            except ExecutionReviewDomainError as exc:
                return event_id, exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        return tuple(executor.map(race, event_ids, (20, 21)))


def _integrity_error(constraint_name: str) -> IntegrityError:
    diagnostics = type("Diagnostics", (), {"constraint_name": constraint_name})()
    original = type("Original", (Exception,), {"diag": diagnostics})(
        "sensitive SQL and values"
    )
    return IntegrityError("sensitive statement", {"secret": "value"}, original)
