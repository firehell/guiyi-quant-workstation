from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.alerts.subing_strategy_runtime import (
    SubingStrategyRuntimeEvaluator,
    SubingStrategyRuntimeProductSourceError,
    SubingStrategyRuntimeResult,
)
from app.market_data.aggregation import SessionWindow, bucket_window_for_bar
from app.market_data.domain import BarFrequency, CanonicalBar
from app.market_data.subing_calibration import load_subing_calibration
from app.market_data.subing_lifecycle_policy import load_subing_lifecycle_policy
from app.market_data.subing_strategy.contracts import (
    SubingStrategyActionKind,
    SubingStrategyDirection,
)
from app.market_data.subing_strategy.machine import (
    SubingStrategyInterval,
    SubingStrategyMachineError,
    SubingStrategyMachineState,
    SubingStrategySourceIdentity,
    initial_subing_strategy_machine,
    step_subing_strategy_machine,
)
from app.market_data.subing_strategy.policy import load_subing_strategy_policy
from app.market_data.subing_strategy.stream_contracts import (
    AuthoritativeSegmentTerminal,
    Completed1mBar,
    Completed5mBar,
    Completed15mBar,
)
from research.subing_strategy_fixtures import recorded_strategy_stream
from research.test_subing_strategy_engine import _context


STARTED_AT = datetime(2026, 8, 3, 9, 59, 30, tzinfo=UTC)
READY_AT = datetime(2026, 8, 3, 10, 1, 30, tzinfo=UTC)
TRADING_DAY = date(2026, 8, 3)


RuntimeEvent = Completed1mBar | Completed5mBar | Completed15mBar


class _RestoreReader:
    def __init__(
        self,
        states: Mapping[str, SubingStrategyMachineState | Exception],
        *,
        rollovers: Mapping[str, SubingStrategyMachineState | Exception] | None = None,
    ) -> None:
        self.states = dict(states)
        self.rollovers = dict(rollovers or {})
        self.calls: list[tuple[str, datetime]] = []
        self.rollover_calls: list[
            tuple[
                str,
                date,
                SubingStrategySourceIdentity,
                AuthoritativeSegmentTerminal,
            ]
        ] = []

    def restore(
        self,
        *,
        symbol: str,
        started_at: datetime,
    ) -> SubingStrategyMachineState:
        self.calls.append((symbol, started_at))
        result = self.states[symbol]
        if isinstance(result, Exception):
            raise result
        return result

    def restore_rollover(
        self,
        *,
        symbol: str,
        trading_day: date,
        previous_identity: SubingStrategySourceIdentity,
        terminal: AuthoritativeSegmentTerminal,
    ) -> SubingStrategyMachineState:
        self.rollover_calls.append((symbol, trading_day, previous_identity, terminal))
        result = self.rollovers[symbol]
        if isinstance(result, Exception):
            raise result
        return result


class _CurrentReader:
    def __init__(
        self,
        *,
        streams: Mapping[
            str,
            Mapping[BarFrequency, tuple[CanonicalBar, ...]],
        ]
        | None = None,
        terminals: Mapping[
            tuple[str, date],
            AuthoritativeSegmentTerminal | None,
        ]
        | None = None,
        sessions: Mapping[str, tuple[SessionWindow, ...]] | None = None,
        completed_error: Exception | None = None,
        session_error: Exception | None = None,
        terminal_error: Exception | None = None,
    ) -> None:
        self.streams = {
            symbol: dict(stream) for symbol, stream in (streams or {}).items()
        }
        self.terminals = dict(terminals or {})
        self.sessions = dict(sessions or {})
        self.completed_error = completed_error
        self.session_error = session_error
        self.terminal_error = terminal_error
        self.catch_up_calls: list[
            tuple[
                str,
                SubingStrategySourceIdentity,
                datetime | None,
                datetime | None,
                datetime | None,
                datetime,
            ]
        ] = []
        self.terminal_calls: list[tuple[str, date, SubingStrategySourceIdentity]] = []

    def read_completed_bars(
        self,
        *,
        symbol: str,
        source_identity: SubingStrategySourceIdentity,
        after_1m: datetime | None,
        after_5m: datetime | None,
        after_15m: datetime | None,
        through: datetime,
    ) -> Mapping[BarFrequency, tuple[CanonicalBar, ...]]:
        self.catch_up_calls.append(
            (
                symbol,
                source_identity,
                after_1m,
                after_5m,
                after_15m,
                through,
            )
        )
        if self.completed_error is not None:
            raise self.completed_error
        return self.streams.get(symbol, {})

    def read_authoritative_terminal(
        self,
        *,
        symbol: str,
        trading_day: date,
        source_identity: SubingStrategySourceIdentity,
    ) -> AuthoritativeSegmentTerminal | None:
        self.terminal_calls.append((symbol, trading_day, source_identity))
        if self.terminal_error is not None:
            raise self.terminal_error
        terminal = self.terminals.get((symbol, trading_day))
        if terminal is None:
            return None
        if (
            terminal.symbol != source_identity.symbol
            or terminal.contract != source_identity.contract
            or terminal.segment_start_trading_day
            != source_identity.segment_start_trading_day
        ):
            return None
        return terminal

    def read_session_windows(
        self,
        *,
        symbol: str,
        trading_day: date,
        source_identity: SubingStrategySourceIdentity,
    ) -> tuple[SessionWindow, ...]:
        del source_identity
        if self.session_error is not None:
            raise self.session_error
        return self.sessions.get(
            symbol,
            (
                SessionWindow(
                    start=datetime.combine(trading_day, datetime.min.time(), UTC),
                    end=datetime.combine(
                        trading_day + timedelta(days=1),
                        datetime.min.time(),
                        UTC,
                    ),
                ),
            ),
        )


def _recorded_machine(
    *,
    symbol: str = "jm",
    event_count: int = 0,
) -> tuple[
    SubingStrategyMachineState,
    SubingStrategySourceIdentity,
    tuple[RuntimeEvent, ...],
]:
    recorded = recorded_strategy_stream(18, SubingStrategyDirection.LONG_ONLY)
    contract = f"{symbol.upper()}2701"
    context = replace(
        _context(recorded.bars_15m[0], SubingStrategyDirection.LONG_ONLY),
        symbol=symbol,
        physical_contract=contract,
    )
    intervals = tuple(
        SubingStrategyInterval(
            effective_bar_end=bar.bar_end,
            first_1m_bar_end=(
                bucket_window_for_bar(
                    recorded.sessions[0],
                    BarFrequency.M15,
                    bar.bar_end,
                ).start
                + timedelta(minutes=1)
            ),
            expected_open=bar.open,
        )
        for bar in recorded.bars_15m
    )
    state = initial_subing_strategy_machine(
        symbol=symbol,
        contract=contract,
        segment_start_trading_day=TRADING_DAY,
        calibration=load_subing_calibration(),
        lifecycle_policy=load_subing_lifecycle_policy(),
        strategy_policy=load_subing_strategy_policy(),
        direction_contexts={TRADING_DAY: context},
        intervals=intervals,
    )
    identity = SubingStrategySourceIdentity(
        symbol=symbol,
        contract=contract,
        segment_start_trading_day=TRADING_DAY,
    )
    events: list[RuntimeEvent] = [
        *(Completed1mBar(bar) for bar in recorded.bars_1m),
        *(Completed5mBar(bar) for bar in recorded.bars_5m),
        *(Completed15mBar(bar) for bar in recorded.bars_15m),
    ]
    events.sort(
        key=lambda event: (
            event.bar.bar_end,
            0
            if isinstance(event, Completed1mBar)
            else 1
            if isinstance(event, Completed5mBar)
            else 2,
        )
    )
    for event in events[:event_count]:
        state, _ = step_subing_strategy_machine(
            state,
            event,
            source_identity=identity,
        )
    return state, identity, tuple(events)


def _new_flat_segment() -> tuple[
    SubingStrategyMachineState,
    SubingStrategySourceIdentity,
    CanonicalBar,
]:
    recorded = recorded_strategy_stream(18, SubingStrategyDirection.LONG_ONLY)
    segment_start = TRADING_DAY + timedelta(days=1)
    contract = "JM2705"
    first_bar = replace(
        recorded.bars_1m[0],
        bar_end=recorded.bars_1m[0].bar_end + timedelta(days=1),
        trading_day=segment_start,
    )
    context = replace(
        _context(recorded.bars_15m[0], SubingStrategyDirection.LONG_ONLY),
        target_trading_day=segment_start,
        symbol="jm",
        physical_contract=contract,
    )
    state = initial_subing_strategy_machine(
        symbol="jm",
        contract=contract,
        segment_start_trading_day=segment_start,
        calibration=load_subing_calibration(),
        lifecycle_policy=load_subing_lifecycle_policy(),
        strategy_policy=load_subing_strategy_policy(),
        direction_contexts={segment_start: context},
        intervals=(),
    )
    return (
        state,
        SubingStrategySourceIdentity("jm", contract, segment_start),
        first_bar,
    )


def _ready_evaluator(
    state: SubingStrategyMachineState,
    *,
    current: _CurrentReader | None = None,
) -> tuple[SubingStrategyRuntimeEvaluator, SubingStrategySourceIdentity]:
    restore = _RestoreReader({state.symbol: state})
    evaluator = SubingStrategyRuntimeEvaluator(
        (state.symbol,),
        restore_reader=restore,
        current_reader=current or _CurrentReader(),
    )
    restored = evaluator.restore_all(started_at=STARTED_AT)
    assert restored[0].product_status.state == "warming"
    ready = evaluator.final_catch_up(ready_at=READY_AT)
    assert ready[0].product_status.state == "ready"
    return evaluator, SubingStrategySourceIdentity(
        symbol=state.symbol,
        contract=state.contract,
        segment_start_trading_day=state.segment_start_trading_day,
    )


def _result_for(
    results: tuple[SubingStrategyRuntimeResult, ...],
    symbol: str,
) -> SubingStrategyRuntimeResult:
    return next(result for result in results if result.product_status.symbol == symbol)


def _emitted_actions(
    result: SubingStrategyRuntimeResult,
):
    return tuple(fact.action for fact in result.action_facts)


def test_restore_calculates_every_active_product_without_scope_input() -> None:
    jm, _, _ = _recorded_machine(symbol="jm")
    ag, _, _ = _recorded_machine(symbol="ag")
    restore = _RestoreReader({"jm": jm, "ag": ag})
    evaluator = SubingStrategyRuntimeEvaluator(
        ("jm", "ag"),
        restore_reader=restore,
        current_reader=_CurrentReader(),
    )

    results = evaluator.restore_all(started_at=STARTED_AT)

    assert restore.calls == [("jm", STARTED_AT), ("ag", STARTED_AT)]
    assert tuple(result.product_status.symbol for result in results) == ("jm", "ag")
    assert all(result.action_facts == () for result in results)
    assert all(result.product_status.state == "warming" for result in results)


def test_final_catch_up_closes_restore_race_without_emitting_past_action() -> None:
    state, identity, events = _recorded_machine(event_count=758)
    catch_up = {
        BarFrequency.M5: (events[758].bar,),
        BarFrequency.M15: (events[759].bar,),
        BarFrequency.M1: (events[760].bar,),
    }
    current = _CurrentReader(streams={"jm": catch_up})
    evaluator = SubingStrategyRuntimeEvaluator(
        ("jm",),
        restore_reader=_RestoreReader({"jm": state}),
        current_reader=current,
    )
    evaluator.restore_all(started_at=STARTED_AT)

    result = evaluator.final_catch_up(ready_at=READY_AT)[0]

    assert result.action_facts == ()
    assert result.product_status.state == "ready"
    restored = evaluator.current_state("jm")
    assert restored is not None
    assert restored.position is not None
    assert restored.actions[-1].kind is SubingStrategyActionKind.OPEN_LONG
    queued_duplicate = evaluator.process_completed_bar(
        events[760].bar,
        BarFrequency.M1,
        source_identity=identity,
    )
    assert queued_duplicate.action_facts == ()
    assert queued_duplicate.product_status.state == "ready"
    assert current.catch_up_calls == [
        (
            "jm",
            identity,
            state.watermarks.latest_1m.bar_end,
            state.watermarks.latest_5m.bar_end,
            state.watermarks.latest_15m.bar_end,
            READY_AT,
        )
    ]


def test_pending_action_with_future_first_1m_remains_eligible_after_ready() -> None:
    pending, _, events = _recorded_machine(event_count=760)
    evaluator, identity = _ready_evaluator(pending)

    result = evaluator.process_completed_bar(
        events[760].bar,
        BarFrequency.M1,
        source_identity=identity,
    )

    assert tuple(action.kind for action in _emitted_actions(result)) == (
        SubingStrategyActionKind.OPEN_LONG,
    )
    assert result.product_status.state == "ready"


def test_future_interval_is_derived_from_authoritative_session_bucket() -> None:
    pending, _, events = _recorded_machine(event_count=760)
    target_end = events[759].bar.bar_end + timedelta(minutes=15)
    pending = replace(
        pending,
        intervals=tuple(
            interval
            for interval in pending.intervals
            if interval.effective_bar_end != target_end
        ),
    )
    evaluator, identity = _ready_evaluator(pending)

    result = evaluator.process_completed_bar(
        events[760].bar,
        BarFrequency.M1,
        source_identity=identity,
    )

    assert len(result.action_facts) == 1
    assert result.action_facts[0].action.effective_bar_end == target_end


def test_completed_5m_updates_internal_state_without_public_action() -> None:
    state, _, events = _recorded_machine(event_count=752)
    evaluator, identity = _ready_evaluator(state)

    result = evaluator.process_completed_bar(
        events[752].bar,
        BarFrequency.M5,
        source_identity=identity,
    )

    assert result.action_facts == ()
    current = evaluator.current_state("jm")
    assert current is not None
    assert current.watermarks.latest_5m == events[752].bar


def test_completed_15m_creates_pending_but_does_not_emit_action() -> None:
    state, _, events = _recorded_machine(event_count=758)
    evaluator, identity = _ready_evaluator(state)
    evaluator.process_completed_bar(
        events[758].bar,
        BarFrequency.M5,
        source_identity=identity,
    )

    result = evaluator.process_completed_bar(
        events[759].bar,
        BarFrequency.M15,
        source_identity=identity,
    )

    assert result.action_facts == ()
    current = evaluator.current_state("jm")
    assert current is not None
    assert current.pending_action is not None
    assert current.pending_action.kind is SubingStrategyActionKind.OPEN_LONG


def test_shared_boundary_order_cannot_use_final_5m_as_interval_open() -> None:
    """Catches the final 5m open becoming the next authoritative 15m open."""

    state, identity, events = _recorded_machine(event_count=758)
    final_5m = events[758]
    closing_15m = events[759]
    assert isinstance(final_5m, Completed5mBar)
    assert isinstance(closing_15m, Completed15mBar)
    assert final_5m.bar.bar_end == closing_15m.bar.bar_end
    assert final_5m.bar.open != closing_15m.bar.open
    boundary = closing_15m.bar.bar_end
    state = replace(
        state,
        intervals=tuple(
            interval
            for interval in state.intervals
            if interval.effective_bar_end != boundary
        ),
    )

    def process(order: tuple[RuntimeEvent, RuntimeEvent]):
        evaluator, _ = _ready_evaluator(state)
        first = evaluator.process_completed_bar(
            order[0].bar,
            BarFrequency.M5
            if isinstance(order[0], Completed5mBar)
            else BarFrequency.M15,
            source_identity=identity,
        )
        after_first = evaluator.current_state("jm")
        assert after_first is not None
        if isinstance(order[0], Completed5mBar):
            assert all(
                interval.effective_bar_end != boundary
                for interval in after_first.intervals
            )
        second = evaluator.process_completed_bar(
            order[1].bar,
            BarFrequency.M5
            if isinstance(order[1], Completed5mBar)
            else BarFrequency.M15,
            source_identity=identity,
        )
        assert first.action_facts == ()
        return second, evaluator.current_state("jm")

    five_first = process((final_5m, closing_15m))
    fifteen_first = process((closing_15m, final_5m))

    assert five_first == fifteen_first
    assert five_first[0].product_status.state == "ready"
    assert five_first[0].action_facts == fifteen_first[0].action_facts
    resolved = five_first[1]
    assert resolved is not None
    interval = next(
        item for item in resolved.intervals if item.effective_bar_end == boundary
    )
    assert interval.expected_open == closing_15m.bar.open
    assert interval.expected_open != final_5m.bar.open


def test_exact_first_completed_1m_applies_pending_action() -> None:
    pending, _, events = _recorded_machine(event_count=760)
    evaluator, identity = _ready_evaluator(pending)

    result = evaluator.process_completed_bar(
        events[760].bar,
        BarFrequency.M1,
        source_identity=identity,
    )

    assert len(result.action_facts) == 1
    assert result.action_facts[0].action.reference_price == events[760].bar.open
    assert result.action_facts[0].episode is None
    assert result.action_facts[0].action.effective_open_at == (
        events[760].bar.bar_end - timedelta(minutes=1)
    )


def test_duplicate_completed_bar_is_idempotent_after_action() -> None:
    pending, _, events = _recorded_machine(event_count=760)
    evaluator, identity = _ready_evaluator(pending)
    first = evaluator.process_completed_bar(
        events[760].bar,
        BarFrequency.M1,
        source_identity=identity,
    )
    state_after_first = evaluator.current_state("jm")

    duplicate = evaluator.process_completed_bar(
        events[760].bar,
        BarFrequency.M1,
        source_identity=identity,
    )

    assert len(first.action_facts) == 1
    assert duplicate.action_facts == ()
    assert duplicate.product_status.state == "ready"
    assert evaluator.current_state("jm") == state_after_first


def test_completed_close_emits_its_exact_closed_episode_fact() -> None:
    holding, _, events = _recorded_machine(event_count=779)
    evaluator, identity = _ready_evaluator(holding)

    result = evaluator.process_completed_bar(
        events[779].bar,
        BarFrequency.M1,
        source_identity=identity,
    )

    assert len(result.action_facts) == 1
    fact = result.action_facts[0]
    assert fact.action.kind is SubingStrategyActionKind.CLOSE_LONG
    assert fact.episode is not None
    assert fact.episode.exit_action == fact.action


def test_conflicting_same_identity_degrades_only_that_product() -> None:
    jm, jm_identity, jm_events = _recorded_machine(symbol="jm")
    ag, _, _ = _recorded_machine(symbol="ag")
    evaluator = SubingStrategyRuntimeEvaluator(
        ("jm", "ag"),
        restore_reader=_RestoreReader({"jm": jm, "ag": ag}),
        current_reader=_CurrentReader(),
    )
    evaluator.restore_all(started_at=STARTED_AT)
    evaluator.final_catch_up(ready_at=READY_AT)
    evaluator.process_completed_bar(
        jm_events[0].bar,
        BarFrequency.M1,
        source_identity=jm_identity,
    )
    conflicting = replace(
        jm_events[0].bar,
        open=jm_events[0].bar.open + Decimal("0.25"),
    )

    result = evaluator.process_completed_bar(
        conflicting,
        BarFrequency.M1,
        source_identity=jm_identity,
    )

    assert result.action_facts == ()
    assert result.product_status.state == "unavailable"
    assert result.product_status.reason_codes == ("CONFLICTING_DUPLICATE",)
    assert evaluator.current_state("ag") == ag


def test_one_restore_failure_does_not_stop_other_active_products() -> None:
    jm, _, _ = _recorded_machine(symbol="jm")
    restore = _RestoreReader(
        {
            "jm": jm,
            "ag": SubingStrategyRuntimeProductSourceError(
                "private restore fixture unavailable"
            ),
        }
    )
    evaluator = SubingStrategyRuntimeEvaluator(
        ("jm", "ag"),
        restore_reader=restore,
        current_reader=_CurrentReader(),
    )

    restored = evaluator.restore_all(started_at=STARTED_AT)
    ready = evaluator.final_catch_up(ready_at=READY_AT)

    assert _result_for(restored, "ag").product_status.state == "unavailable"
    assert _result_for(ready, "jm").product_status.state == "ready"
    assert evaluator.current_state("jm") == jm
    assert evaluator.current_state("ag") is None


@pytest.mark.parametrize(
    "stale_identity",
    (
        SubingStrategySourceIdentity("jm", "JM2609", TRADING_DAY),
        SubingStrategySourceIdentity(
            "jm",
            "JM2701",
            TRADING_DAY + timedelta(days=1),
        ),
    ),
)
def test_stale_contract_or_segment_identity_degrades_without_mutation(
    stale_identity: SubingStrategySourceIdentity,
) -> None:
    state, identity, events = _recorded_machine()
    evaluator, _ = _ready_evaluator(state)
    assert stale_identity != identity

    result = evaluator.process_completed_bar(
        events[0].bar,
        BarFrequency.M1,
        source_identity=stale_identity,
    )

    assert result.product_status.state == "unavailable"
    assert result.product_status.reason_codes == ("SOURCE_IDENTITY_MISMATCH",)
    assert evaluator.current_state("jm") == state


def test_later_1m_cancels_pending_when_exact_first_bar_is_missing() -> None:
    pending, _, events = _recorded_machine(event_count=760)
    evaluator, identity = _ready_evaluator(pending)

    result = evaluator.process_completed_bar(
        events[761].bar,
        BarFrequency.M1,
        source_identity=identity,
    )

    assert result.action_facts == ()
    assert result.product_status.state == "ready"
    current = evaluator.current_state("jm")
    assert current is not None
    assert current.pending_action is None


def test_later_1m_does_not_poison_new_interval_open_identity() -> None:
    pending, _, events = _recorded_machine(event_count=760)
    target_end = events[759].bar.bar_end + timedelta(minutes=15)
    pending = replace(
        pending,
        intervals=tuple(
            interval
            for interval in pending.intervals
            if interval.effective_bar_end != target_end
        ),
    )
    evaluator, identity = _ready_evaluator(pending)
    later_1m = Completed1mBar(
        replace(events[761].bar, open=events[761].bar.open + Decimal("0.25"))
    )
    five_minute_events = tuple(
        event
        for event in events
        if isinstance(event, Completed5mBar)
        and later_1m.bar.bar_end < event.bar.bar_end <= target_end
    )
    closing_15m = next(
        event
        for event in events
        if isinstance(event, Completed15mBar) and event.bar.bar_end == target_end
    )

    missing = evaluator.process_completed_bar(
        later_1m.bar,
        BarFrequency.M1,
        source_identity=identity,
    )
    five_results = tuple(
        evaluator.process_completed_bar(
            event.bar,
            BarFrequency.M5,
            source_identity=identity,
        )
        for event in five_minute_events
    )
    fifteen = evaluator.process_completed_bar(
        closing_15m.bar,
        BarFrequency.M15,
        source_identity=identity,
    )

    assert missing.product_status.state == "ready"
    assert all(result.product_status.state == "ready" for result in five_results)
    assert fifteen.product_status.state == "ready"
    current = evaluator.current_state("jm")
    assert current is not None
    interval = next(
        item for item in current.intervals if item.effective_bar_end == target_end
    )
    assert interval.expected_open == five_minute_events[0].bar.open
    assert interval.expected_open != later_1m.bar.open


def test_canonical_updated_emits_terminal_close_only_when_newly_authoritative() -> None:
    holding, identity, events = _recorded_machine(event_count=779)
    terminal = AuthoritativeSegmentTerminal(
        symbol="jm",
        contract=identity.contract,
        segment_start_trading_day=identity.segment_start_trading_day,
        terminal_bar=events[778].bar,
    )
    new_state, new_identity, new_bar = _new_flat_segment()
    restore = _RestoreReader({"jm": holding}, rollovers={"jm": new_state})
    current = _CurrentReader(terminals={("jm", TRADING_DAY): terminal})
    evaluator = SubingStrategyRuntimeEvaluator(
        ("jm",),
        restore_reader=restore,
        current_reader=current,
    )
    evaluator.restore_all(started_at=STARTED_AT)
    evaluator.final_catch_up(ready_at=READY_AT)

    first = evaluator.process_canonical_updated(TRADING_DAY)[0]
    rolled = evaluator.current_state("jm")
    second = evaluator.process_canonical_updated(TRADING_DAY)[0]
    continued = evaluator.process_completed_bar(
        new_bar,
        BarFrequency.M1,
        source_identity=new_identity,
    )

    assert len(first.action_facts) == 1
    terminal_fact = first.action_facts[0]
    assert terminal_fact.action.kind is SubingStrategyActionKind.CLOSE_LONG
    assert terminal_fact.action.reason_codes[-1] == "CONTRACT_SEGMENT_END"
    assert terminal_fact.episode is not None
    assert terminal_fact.episode.exit_action == terminal_fact.action
    assert rolled is not None
    assert rolled == new_state
    assert rolled.position is None
    assert second.action_facts == ()
    assert second.product_status.state == "ready"
    assert restore.rollover_calls == [("jm", TRADING_DAY, identity, terminal)]
    assert continued.product_status.state == "ready"
    assert evaluator.current_state("jm") is not None
    assert evaluator.current_state("jm").contract == new_identity.contract


def test_later_startup_does_not_reemit_restored_terminal_close() -> None:
    holding, identity, events = _recorded_machine(event_count=761)
    terminal = AuthoritativeSegmentTerminal(
        symbol="jm",
        contract=identity.contract,
        segment_start_trading_day=identity.segment_start_trading_day,
        terminal_bar=events[759].bar,
    )
    new_state, new_identity, _ = _new_flat_segment()
    current = _CurrentReader(terminals={("jm", TRADING_DAY): terminal})
    evaluator, _ = _ready_evaluator(new_state, current=current)

    result = evaluator.process_canonical_updated(TRADING_DAY)[0]

    assert result.action_facts == ()
    assert result.product_status.state == "ready"
    assert evaluator.current_state("jm") == new_state
    assert current.terminal_calls == [("jm", TRADING_DAY, new_identity)]


def test_restore_open_and_close_during_downtime_ends_flat_without_backfill() -> None:
    flat, _, _ = _recorded_machine(event_count=780)
    assert flat.position is None
    assert tuple(action.kind for action in flat.actions[-2:]) == (
        SubingStrategyActionKind.OPEN_LONG,
        SubingStrategyActionKind.CLOSE_LONG,
    )
    evaluator = SubingStrategyRuntimeEvaluator(
        ("jm",),
        restore_reader=_RestoreReader({"jm": flat}),
        current_reader=_CurrentReader(),
    )

    restored = evaluator.restore_all(started_at=STARTED_AT)[0]
    ready = evaluator.final_catch_up(ready_at=READY_AT)[0]

    assert restored.action_facts == ()
    assert ready.action_facts == ()
    assert ready.product_status.state == "ready"
    current = evaluator.current_state("jm")
    assert current is not None
    assert current.position is None


def test_restore_product_source_failure_uses_fixed_public_code() -> None:
    private = "token=private-restore-value"
    evaluator = SubingStrategyRuntimeEvaluator(
        ("jm",),
        restore_reader=_RestoreReader(
            {"jm": SubingStrategyRuntimeProductSourceError(private)}
        ),
        current_reader=_CurrentReader(),
    )

    result = evaluator.restore_all(started_at=STARTED_AT)[0]

    assert result.product_status.reason_codes == ("RESTORE_UNAVAILABLE",)
    assert private not in repr(result)


def test_catch_up_product_source_failure_uses_fixed_public_code() -> None:
    state, _, _ = _recorded_machine()
    private = "password=private-catch-up-value"
    evaluator = SubingStrategyRuntimeEvaluator(
        ("jm",),
        restore_reader=_RestoreReader({"jm": state}),
        current_reader=_CurrentReader(
            completed_error=SubingStrategyRuntimeProductSourceError(private)
        ),
    )
    evaluator.restore_all(started_at=STARTED_AT)

    result = evaluator.final_catch_up(ready_at=READY_AT)[0]

    assert result.product_status.reason_codes == ("CURRENT_UNAVAILABLE",)
    assert private not in repr(result)


def test_next_session_live_bar_without_occupancy_keeps_ready_product() -> None:
    """Friday occupancy-capped restore must ignore Monday overnight Live."""
    state, identity, events = _recorded_machine(event_count=18)
    current = _CurrentReader(
        session_error=SubingStrategyRuntimeProductSourceError(
            "MAIN_CONTRACT_MAP_MISSING"
        )
    )
    evaluator, identity = _ready_evaluator(state, current=current)
    restored = evaluator.current_state("jm")
    assert restored is not None
    latest = restored.watermarks.latest_15m or restored.watermarks.latest_1m
    assert latest is not None
    future = replace(
        events[0].bar,
        trading_day=latest.trading_day + timedelta(days=3),
        bar_end=latest.bar_end + timedelta(days=3),
    )

    result = evaluator.process_completed_bar(
        future,
        BarFrequency.M1,
        source_identity=identity,
    )

    assert result.product_status.state == "ready"
    assert result.product_status.reason_codes == ()
    assert result.action_facts == ()


def test_completed_bar_product_source_failure_uses_fixed_public_code() -> None:
    state, identity, events = _recorded_machine()
    private = "secret=session-private-value"
    evaluator, _ = _ready_evaluator(
        state,
        current=_CurrentReader(
            session_error=SubingStrategyRuntimeProductSourceError(private)
        ),
    )

    result = evaluator.process_completed_bar(
        events[0].bar,
        BarFrequency.M1,
        source_identity=identity,
    )

    assert result.product_status.reason_codes == ("COMPLETED_BAR_UNAVAILABLE",)
    assert private not in repr(result)


def test_terminal_product_source_failure_uses_fixed_public_code() -> None:
    state, _, _ = _recorded_machine()
    private = "credential=terminal-private-value"
    evaluator, _ = _ready_evaluator(
        state,
        current=_CurrentReader(
            terminal_error=SubingStrategyRuntimeProductSourceError(private)
        ),
    )

    result = evaluator.process_canonical_updated(TRADING_DAY)[0]

    assert result.product_status.reason_codes == ("TERMINAL_UNAVAILABLE",)
    assert private not in repr(result)


@pytest.mark.parametrize(
    "error",
    (
        ValueError("INVALID_POLICY_SCHEMA"),
        AssertionError("programming fault"),
    ),
)
def test_restore_process_faults_propagate(error: Exception) -> None:
    evaluator = SubingStrategyRuntimeEvaluator(
        ("jm",),
        restore_reader=_RestoreReader({"jm": error}),
        current_reader=_CurrentReader(),
    )

    with pytest.raises(type(error), match=str(error)):
        evaluator.restore_all(started_at=STARTED_AT)


def test_catch_up_unexpected_fault_propagates() -> None:
    state, _, _ = _recorded_machine()
    evaluator = SubingStrategyRuntimeEvaluator(
        ("jm",),
        restore_reader=_RestoreReader({"jm": state}),
        current_reader=_CurrentReader(
            completed_error=RuntimeError("unexpected catch-up bug")
        ),
    )
    evaluator.restore_all(started_at=STARTED_AT)

    with pytest.raises(RuntimeError, match="unexpected catch-up bug"):
        evaluator.final_catch_up(ready_at=READY_AT)


def test_completed_bar_unexpected_fault_propagates() -> None:
    state, identity, events = _recorded_machine()
    evaluator, _ = _ready_evaluator(
        state,
        current=_CurrentReader(session_error=AssertionError("unexpected session bug")),
    )

    with pytest.raises(AssertionError, match="unexpected session bug"):
        evaluator.process_completed_bar(
            events[0].bar,
            BarFrequency.M1,
            source_identity=identity,
        )


def test_terminal_unexpected_fault_propagates() -> None:
    state, _, _ = _recorded_machine()
    evaluator, _ = _ready_evaluator(
        state,
        current=_CurrentReader(terminal_error=RuntimeError("unexpected terminal bug")),
    )

    with pytest.raises(RuntimeError, match="unexpected terminal bug"):
        evaluator.process_canonical_updated(TRADING_DAY)


def test_unknown_machine_reason_is_not_published() -> None:
    private = "token=unknown-machine-private-value"
    evaluator = SubingStrategyRuntimeEvaluator(
        ("jm",),
        restore_reader=_RestoreReader({"jm": SubingStrategyMachineError(private)}),
        current_reader=_CurrentReader(),
    )

    with pytest.raises(SubingStrategyMachineError, match=private):
        evaluator.restore_all(started_at=STARTED_AT)
