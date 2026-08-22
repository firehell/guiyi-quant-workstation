from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Barrier, Event

import pytest
from sqlalchemy import event as sqlalchemy_event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.execution_review.models import (
    TradeDecision,
    TradeEpisode,
    TradeExecution,
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
    _query_service,
    _race_open_events,
    _service,
    _utc,
)


BAR_END = datetime(2026, 8, 15, 1, 0, tzinfo=UTC)
SERVER_NOW = BAR_END + timedelta(minutes=20)
QUANT_API_ROOT = Path(__file__).resolve().parents[1]

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
            event_id for event_id, code in results if code == "OPEN_EPISODE_CONFLICT"
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
        results = (
            execution_future.result(timeout=15),
            decision_future.result(timeout=15),
        )

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
                states = _query_service(local_session).event_states((event_id,))
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
                    for item in _query_service(local_session).list_items(state="done")
                )
            stats = _query_service(local_session).stats()
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

            detail = _query_service(local_session).episode_detail(episode_id)
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
