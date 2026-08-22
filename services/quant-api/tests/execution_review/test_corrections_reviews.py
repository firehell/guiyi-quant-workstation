from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution_review.models import (
    TradeDecision,
    TradeEpisode,
    TradeExecution,
    TradeReview,
)
from app.execution_review.errors import ExecutionReviewDomainError
from app.execution_review.service import (
    DecisionUpdateCommand,
    DispositionCorrectionCommand,
    ExecutionCommand,
    ExecutionUpdateCommand,
    NotExecutedCommand,
    TimelineExecutionCommand,
)


from execution_review.helpers import (
    _count,
    _event,
    _executed,
    _review_command,
    _service,
    _utc,
)


BAR_END = datetime(2026, 8, 15, 1, 0, tzinfo=UTC)
SERVER_NOW = BAR_END + timedelta(minutes=20)
QUANT_API_ROOT = Path(__file__).resolve().parents[1]

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

    with pytest.raises(
        ExecutionReviewDomainError, match="^DECISION_CORRECTION_CONFLICT$"
    ):
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
