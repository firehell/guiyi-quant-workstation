from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.execution_review.errors import ExecutionReviewDomainError
from app.execution_review.service import (
    ExecutionCommand,
    NotExecutedCommand,
)


from execution_review.helpers import (
    _event,
    _executed,
    _query_service,
    _review_command,
    _service,
    _utc,
)


BAR_END = datetime(2026, 8, 15, 1, 0, tzinfo=UTC)
SERVER_NOW = BAR_END + timedelta(minutes=20)
QUANT_API_ROOT = Path(__file__).resolve().parents[1]

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
        for item in _query_service(session).list_items(state=state)
    )
    assert {(item.item_kind, item.state, item.event_id) for item in items} == {
        ("decision", "pending_decision", pending.id),
        ("decision", "done", not_event.id),
        ("episode", "open", open_result.decision.alert_event_id),
        ("episode", "pending_review", pending_review.decision.alert_event_id),
        ("episode", "done", done.decision.alert_event_id),
    }
    done_items = _query_service(session).list_items(state="done")
    assert {
        (item.item_kind, item.decision_id, item.episode_id) for item in done_items
    } == {
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
        for row in _query_service(session).event_states(requested_event_ids)
    }
    assert event_states == {
        pending.id: "pending_decision",
        not_event.id: "done",
        open_result.decision.alert_event_id: "open",
        pending_review.decision.alert_event_id: "pending_review",
        done.decision.alert_event_id: "done",
    }

    assert [
        item.event_id
        for item in _query_service(session).list_items(
            state="pending_decision",
            symbol=" P ",
            direction="SHORT",
            frequency="15m",
            start_trading_day=date(2099, 1, 1),
            end_trading_day=date(2099, 1, 2),
        )
    ] == [pending.id]
    assert [
        item.episode_id
        for item in _query_service(session).list_items(
            state="open",
            symbol="o",
            direction="SHORT",
            frequency="15m",
            start_trading_day=date(2099, 1, 1),
            end_trading_day=date(2099, 1, 2),
        )
    ] == [open_result.episode.id]
    assert [
        item.episode_id
        for item in _query_service(session).list_items(
            state="pending_review",
            symbol="r",
            direction="SHORT",
            frequency="15m",
            start_trading_day=date(2099, 1, 1),
            end_trading_day=date(2099, 1, 2),
        )
    ] == [pending_review.episode.id]
    assert [
        item.episode_id
        for item in _query_service(session).list_items(
            state="done",
            symbol="d",
            direction="SHORT",
            frequency="15m",
            start_trading_day=date(2026, 8, 15),
            end_trading_day=date(2026, 8, 15),
        )
    ] == [done.episode.id]


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

    states = _query_service(session).event_states((second.id, first.id, second.id))

    assert [row.event_id for row in states] == [second.id, first.id]
    assert unrequested.id not in {row.event_id for row in states}


def test_event_states_missing_id_fails_the_batch(session: Session) -> None:
    event = _event(session)

    with pytest.raises(
        ExecutionReviewDomainError,
        match="^EXECUTION_REVIEW_EVENT_NOT_FOUND$",
    ) as captured:
        _query_service(session).event_states((event.id, event.id + 1000))

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
        _query_service(session).event_states((event.id,))

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

    matching = _query_service(session).list_items(
        state="done",
        start_trading_day=date(2026, 8, 15),
        end_trading_day=date(2026, 8, 15),
    )
    natural_date = _query_service(session).list_items(
        state="done",
        start_trading_day=date(2026, 8, 14),
        end_trading_day=date(2026, 8, 14),
    )

    assert [item.event_id for item in matching] == [event.id]
    assert natural_date == ()


def test_zero_stats_denominators_are_undefined(session: Session) -> None:
    empty = _query_service(session).stats()

    assert empty.opportunities.eligible_events == 0
    assert empty.opportunities.decision_completion_rate is None
    assert empty.opportunities.execution_rate is None

    _event(session)
    pending = _query_service(session).stats()

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

    detail = _query_service(session).episode_detail(opened.episode.id)

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
        _query_service(session).list_items(state="done")

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

    stats = _query_service(session).stats(
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

    filtered = _query_service(session).stats(
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
