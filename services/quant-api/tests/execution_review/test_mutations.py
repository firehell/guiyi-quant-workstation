from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.execution_review.models import (
    TradeDecision,
    TradeEpisode,
    TradeExecution,
    TradeReview,
)
from app.execution_review.errors import ExecutionReviewDomainError
from app.execution_review import composition as execution_review_composition
from app.execution_review.reconciler import RollReconcileResult
from app.execution_review.service import (
    ExecutedCommand,
    ExecutionCommand,
    ExecutionReviewService,
    NotExecutedCommand,
)


from execution_review.helpers import (
    _count,
    _event,
    _executed,
    _integrity_error,
    _service,
    _utc,
)


BAR_END = datetime(2026, 8, 15, 1, 0, tzinfo=UTC)
SERVER_NOW = BAR_END + timedelta(minutes=20)
QUANT_API_ROOT = Path(__file__).resolve().parents[1]

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
            calls.append(symbol) or RollReconcileResult("NOOP", symbol)
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
            calls.append(symbol) or RollReconcileResult("NOOP", symbol)
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


def test_roll_gate_reader_accepts_only_exact_private_enabled_marker(tmp_path: Path) -> None:
    from app.execution_review.roll_gate import execution_review_roll_marker_state

    assert execution_review_roll_marker_state(tmp_path) == "disabled"
    marker = tmp_path / ".run/execution-review-roll-enabled"
    marker.parent.mkdir()
    marker.parent.chmod(0o700)
    marker.write_bytes(b"enabled\n")
    marker.chmod(0o600)
    assert execution_review_roll_marker_state(tmp_path) == "enabled"

    marker.write_bytes(b"disabled\n")
    assert execution_review_roll_marker_state(tmp_path) == "invalid"
    marker.write_bytes(b"enabled\n")
    marker.chmod(0o644)
    assert execution_review_roll_marker_state(tmp_path) == "invalid"


def test_roll_gate_reader_rejects_unsafe_parent_owner_and_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.execution_review import roll_gate

    marker = tmp_path / ".run/execution-review-roll-enabled"
    marker.parent.mkdir(mode=0o700)
    marker.write_bytes(b"enabled\n")
    marker.chmod(0o600)

    marker.parent.chmod(0o755)
    assert roll_gate.execution_review_roll_marker_state(tmp_path) == "invalid"
    marker.parent.chmod(0o700)

    monkeypatch.setattr(roll_gate.os, "getuid", lambda: marker.stat().st_uid + 1)
    assert roll_gate.execution_review_roll_marker_state(tmp_path) == "invalid"
    monkeypatch.undo()

    target = tmp_path / "enabled-target"
    marker.replace(target)
    marker.symlink_to(target)
    assert roll_gate.execution_review_roll_marker_state(tmp_path) == "invalid"


def test_roll_gate_reader_rejects_inode_replacement_during_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.execution_review import roll_gate

    marker = tmp_path / ".run/execution-review-roll-enabled"
    marker.parent.mkdir(mode=0o700)
    marker.write_bytes(b"enabled\n")
    marker.chmod(0o600)
    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"enabled\n")
    replacement.chmod(0o600)
    real_open = roll_gate.os.open

    def replace_then_open(
        path: Path | str,
        flags: int,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if path == "execution-review-roll-enabled":
            replacement.replace(marker)
        return real_open(path, flags, dir_fd=dir_fd)

    monkeypatch.setattr(roll_gate.os, "open", replace_then_open)
    assert roll_gate.execution_review_roll_marker_state(tmp_path) == "invalid"


@pytest.mark.parametrize("gate_state", ("disabled", "invalid"))
def test_composition_roll_gate_blocks_defensive_reconcile_without_market_data(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    gate_state: str,
) -> None:
    _service(session).record_executed(_event(session).id, _executed())
    later = _event(session, bar_end=BAR_END + timedelta(minutes=10))

    def fail_dependency(*_args: object, **_kwargs: object) -> object:
        pytest.fail("roll market data and reconciler must not be constructed")

    monkeypatch.setattr(
        execution_review_composition,
        "build_market_data_service",
        fail_dependency,
    )
    monkeypatch.setattr(
        execution_review_composition,
        "ExecutionReviewRollReconciler",
        fail_dependency,
    )
    service = execution_review_composition.build_execution_review_service(
        session,
        clock=lambda: SERVER_NOW,
        execution_review_roll_marker_state=lambda: gate_state,
    )

    with pytest.raises(
        ExecutionReviewDomainError,
        match="^ROLL_RECONCILIATION_REQUIRED$",
    ):
        service.record_executed(
            later.id,
            _executed(executed_at=BAR_END + timedelta(minutes=13)),
        )


def test_composition_enabled_roll_gate_preserves_defensive_reconcile(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _service(session).record_executed(_event(session).id, _executed())
    later = _event(session, bar_end=BAR_END + timedelta(minutes=10))
    events: list[object] = []
    market_data = object()

    class Reconciler:
        def __init__(self, reconcile_session: Session, *, market_data: object) -> None:
            events.extend((reconcile_session, market_data))

        def reconcile_symbol(self, symbol: str) -> RollReconcileResult:
            events.append(symbol)
            return RollReconcileResult("NOOP", symbol)

    monkeypatch.setattr(
        execution_review_composition,
        "build_market_data_service",
        lambda _session: market_data,
    )
    monkeypatch.setattr(
        execution_review_composition,
        "ExecutionReviewRollReconciler",
        Reconciler,
    )
    service = execution_review_composition.build_execution_review_service(
        session,
        clock=lambda: SERVER_NOW,
        reconcile_session_factory=lambda: Session(session.get_bind()),
        execution_review_roll_marker_state=lambda: "enabled",
    )

    result = service.record_executed(
        later.id,
        _executed(executed_at=BAR_END + timedelta(minutes=13)),
    )

    assert result.execution.execution_type == "ADD"
    assert events[1:] == [market_data, "jm"]


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

    with pytest.raises(
        ExecutionReviewDomainError, match="^EXECUTION_TIME_BEFORE_SIGNAL$"
    ):
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
    mapped = ExecutionReviewService._integrity_error(_integrity_error(constraint_name))

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
