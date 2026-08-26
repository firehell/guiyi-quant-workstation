from __future__ import annotations

from dataclasses import replace
from datetime import UTC, timedelta
from decimal import Decimal

import pytest

from app.market_data.subing_strategy.engine import (
    SubingStrategyPendingAction,
)
from app.market_data.subing_strategy.machine import (
    SubingStrategyInterval,
    SubingStrategyMachineError,
    SubingStrategySourceIdentity,
    initial_subing_strategy_machine,
    step_subing_strategy_machine,
)
from app.market_data.subing_strategy.stream_contracts import (
    AuthoritativeSegmentTerminal,
    Completed1mBar,
    Completed5mBar,
    Completed15mBar,
)
from research.test_subing_strategy_engine import (
    CONTRACT,
    POLICY,
    SEGMENT_START,
    _bar,
    _candidate,
    _context,
)
from app.market_data.domain import CanonicalBar
from app.market_data.subing_calibration import load_subing_calibration
from app.market_data.subing_lifecycle_policy import load_subing_lifecycle_policy
from app.market_data.subing_research import SubingDirection
from app.market_data.subing_strategy.contracts import (
    SubingStrategyActionKind,
    SubingStrategyDirection,
)


def _minute(
    interval_end,
    *,
    minute: int = 1,
    price: str = "100.5",
) -> CanonicalBar:
    bar_end = interval_end - timedelta(minutes=15 - minute)
    value = Decimal(price)
    return CanonicalBar(
        bar_end=bar_end,
        trading_day=SEGMENT_START,
        open=value,
        high=value + Decimal("1"),
        low=value - Decimal("1"),
        close=value,
        volume=Decimal("10"),
        turnover=None,
        open_interest=Decimal("100"),
    )


def _machine(*, pending: bool = False):
    decision = _bar(1)
    effective = _bar(2, open_price="100.5")
    first = _minute(effective.bar_end)
    state = initial_subing_strategy_machine(
        symbol="jm",
        contract=CONTRACT,
        segment_start_trading_day=SEGMENT_START,
        calibration=load_subing_calibration(),
        lifecycle_policy=load_subing_lifecycle_policy(),
        strategy_policy=POLICY,
        direction_contexts={
            SEGMENT_START: _context(
                decision,
                SubingStrategyDirection.LONG_ONLY,
            )
        },
        intervals=(
            SubingStrategyInterval(
                effective_bar_end=effective.bar_end,
                first_1m_bar_end=first.bar_end,
                expected_open=effective.open,
            ),
        ),
    )
    if pending:
        candidate = _candidate(decision, direction=SubingDirection.LONG)
        state = replace(
            state,
            pending_action=SubingStrategyPendingAction(
                kind=SubingStrategyActionKind.OPEN_LONG,
                decision_at=decision.bar_end,
                candidate=candidate,
                direction_context=_context(
                    decision,
                    SubingStrategyDirection.LONG_ONLY,
                ),
                episode_id=None,
                opportunity_id=candidate.opportunity_id,
                reason_codes=(),
            ),
        )
    return state, first, effective


def _identity(
    *,
    contract: str = CONTRACT,
    segment_start=SEGMENT_START,
) -> SubingStrategySourceIdentity:
    return SubingStrategySourceIdentity(
        symbol="jm",
        contract=contract,
        segment_start_trading_day=segment_start,
    )


def _step(state, event, *, identity: SubingStrategySourceIdentity | None = None):
    return step_subing_strategy_machine(
        state,
        event,
        source_identity=identity or _identity(),
    )


def test_pending_open_applies_on_exact_first_completed_1m() -> None:
    state, first, effective = _machine(pending=True)

    state, output = _step(state, Completed1mBar(first))

    action = output.actions[0]
    assert action.reference_price == Decimal("100.5")
    assert action.effective_open_at == first.bar_end - timedelta(minutes=1)
    assert action.effective_bar_end == effective.bar_end
    assert state.pending_action is None


def test_new_day_unavailable_context_cancels_open_but_does_not_block_close() -> None:
    state, first, effective = _machine(pending=True)
    next_day = SEGMENT_START + timedelta(days=1)
    next_effective = replace(
        effective,
        bar_end=effective.bar_end + timedelta(days=1),
        trading_day=next_day,
    )
    next_first = replace(
        first,
        bar_end=first.bar_end + timedelta(days=1),
        trading_day=next_day,
    )
    unavailable = replace(
        _context(next_effective, SubingStrategyDirection.UNAVAILABLE),
        source_trading_day=None,
        reason_codes=("SUBING_DAILY_WATCH_NOT_GENERATED",),
        daily_bar_end=None,
        hourly_bar_end=None,
        physical_contract=None,
    )
    next_interval = SubingStrategyInterval(
        effective_bar_end=next_effective.bar_end,
        first_1m_bar_end=next_first.bar_end,
        expected_open=next_effective.open,
    )
    state = replace(
        state,
        direction_contexts=(*state.direction_contexts, (next_day, unavailable)),
        intervals=(next_interval,),
    )

    state, output = _step(state, Completed1mBar(next_first))

    assert output.actions == ()
    assert output.cancellations[0].reason_code == "DIRECTION_CONTEXT_BLOCKS_ENTRY"
    assert state.pending_action is None

    holding, first, effective = _machine(pending=True)
    holding, _ = _step(holding, Completed1mBar(first))
    assert holding.position is not None
    pending_close = SubingStrategyPendingAction(
        kind=SubingStrategyActionKind.CLOSE_LONG,
        decision_at=effective.bar_end,
        candidate=None,
        direction_context=None,
        episode_id=holding.position.entry_action.episode_id,
        opportunity_id=holding.position.entry_action.opportunity_id,
        reason_codes=("EMA21_BREACH_LONG",),
    )
    holding = replace(
        holding,
        direction_contexts=(*holding.direction_contexts, (next_day, unavailable)),
        intervals=(*holding.intervals, next_interval),
        pending_action=pending_close,
    )

    holding, output = _step(holding, Completed1mBar(next_first))

    assert output.actions[0].kind is SubingStrategyActionKind.CLOSE_LONG
    assert holding.position is None


def test_later_1m_cannot_substitute_for_missing_first_bar() -> None:
    state, first, _ = _machine(pending=True)
    later = replace(first, bar_end=first.bar_end + timedelta(minutes=1))

    state, output = _step(state, Completed1mBar(later))

    assert output.actions == ()
    assert output.cancellations[0].reason_code == "NEXT_BAR_OPEN_UNAVAILABLE"
    assert state.pending_action is None


def test_equal_boundary_message_order_is_invariant() -> None:
    state, _, effective = _machine()
    completed_5m = Completed5mBar(effective)
    completed_15m = Completed15mBar(effective)

    first, first_output = _step(state, completed_15m)
    first, second_output = _step(first, completed_5m)
    second, third_output = _step(state, completed_5m)
    second, fourth_output = _step(second, completed_15m)

    assert first == second
    assert first_output.actions == second_output.actions == ()
    assert third_output.actions == fourth_output.actions == ()


def test_missing_equal_boundary_companion_fails_closed_at_next_boundary() -> None:
    state, _, effective = _machine()
    state, output = _step(state, Completed15mBar(effective))
    later = replace(effective, bar_end=effective.bar_end + timedelta(minutes=5))

    assert output.actions == ()
    with pytest.raises(SubingStrategyMachineError, match="BOUNDARY_COMPANION_MISSING"):
        _step(state, Completed5mBar(later))


def test_duplicate_is_idempotent_and_conflicting_duplicate_fails_closed() -> None:
    state, first, _ = _machine()
    state, _ = _step(state, Completed1mBar(first))

    duplicate, output = _step(state, Completed1mBar(first))

    assert duplicate == state
    assert output.state_changed is False
    conflicting = replace(first, open=first.open + Decimal("1"))
    with pytest.raises(SubingStrategyMachineError, match="CONFLICTING_DUPLICATE"):
        _step(state, Completed1mBar(conflicting))


def test_stale_completed_bar_is_rejected() -> None:
    state, first, _ = _machine()
    later = replace(first, bar_end=first.bar_end + timedelta(minutes=1))
    state, _ = _step(state, Completed1mBar(later))

    with pytest.raises(SubingStrategyMachineError, match="STALE_INPUT"):
        _step(state, Completed1mBar(first))


@pytest.mark.parametrize(
    "identity",
    (
        _identity(contract="JM2609"),
        _identity(segment_start=SEGMENT_START + timedelta(days=1)),
    ),
)
def test_completed_bar_rejects_other_contract_or_segment_source(
    identity: SubingStrategySourceIdentity,
) -> None:
    state, first, _ = _machine()

    with pytest.raises(SubingStrategyMachineError, match="SOURCE_IDENTITY_MISMATCH"):
        _step(state, Completed1mBar(first), identity=identity)


def test_stream_inputs_require_utc_aware_times() -> None:
    state, first, _ = _machine()
    assert first.bar_end.tzinfo is UTC
    assert state.factor_5m.last_bar_end is None


def test_terminal_close_uses_completed_15m_close_without_open_timestamp() -> None:
    state, first, effective = _machine(pending=True)
    state, _ = _step(state, Completed1mBar(first))
    state, _ = _step(state, Completed15mBar(effective))
    state, _ = _step(state, Completed5mBar(effective))

    state, output = _step(
        state,
        AuthoritativeSegmentTerminal(
            symbol="jm",
            contract=CONTRACT,
            segment_start_trading_day=SEGMENT_START,
            terminal_bar=effective,
        ),
    )

    close = output.actions[0]
    assert close.kind is SubingStrategyActionKind.CLOSE_LONG
    assert close.reference_price == effective.close
    assert close.effective_open_at is None
    assert state.position is None
