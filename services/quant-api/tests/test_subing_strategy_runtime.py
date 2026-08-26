from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.alerts.subing_strategy_runtime import (
    SubingStrategyRuntimeEvaluator,
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
    ) -> None:
        self.states = dict(states)
        self.calls: list[tuple[str, datetime]] = []

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
    ) -> None:
        self.streams = {
            symbol: dict(stream) for symbol, stream in (streams or {}).items()
        }
        self.terminals = dict(terminals or {})
        self.sessions = dict(sessions or {})
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
        return self.streams.get(symbol, {})

    def read_authoritative_terminal(
        self,
        *,
        symbol: str,
        trading_day: date,
        source_identity: SubingStrategySourceIdentity,
    ) -> AuthoritativeSegmentTerminal | None:
        self.terminal_calls.append((symbol, trading_day, source_identity))
        return self.terminals.get((symbol, trading_day))

    def read_session_windows(
        self,
        *,
        symbol: str,
        trading_day: date,
        source_identity: SubingStrategySourceIdentity,
    ) -> tuple[SessionWindow, ...]:
        del source_identity
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
    assert all(result.actions == () for result in results)
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

    assert result.actions == ()
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
    assert queued_duplicate.actions == ()
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

    assert tuple(action.kind for action in result.actions) == (
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

    assert len(result.actions) == 1
    assert result.actions[0].effective_bar_end == target_end


def test_completed_5m_updates_internal_state_without_public_action() -> None:
    state, _, events = _recorded_machine(event_count=752)
    evaluator, identity = _ready_evaluator(state)

    result = evaluator.process_completed_bar(
        events[752].bar,
        BarFrequency.M5,
        source_identity=identity,
    )

    assert result.actions == ()
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

    assert result.actions == ()
    current = evaluator.current_state("jm")
    assert current is not None
    assert current.pending_action is not None
    assert current.pending_action.kind is SubingStrategyActionKind.OPEN_LONG


def test_exact_first_completed_1m_applies_pending_action() -> None:
    pending, _, events = _recorded_machine(event_count=760)
    evaluator, identity = _ready_evaluator(pending)

    result = evaluator.process_completed_bar(
        events[760].bar,
        BarFrequency.M1,
        source_identity=identity,
    )

    assert len(result.actions) == 1
    assert result.actions[0].reference_price == events[760].bar.open
    assert result.actions[0].effective_open_at == (
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

    assert len(first.actions) == 1
    assert duplicate.actions == ()
    assert duplicate.product_status.state == "ready"
    assert evaluator.current_state("jm") == state_after_first


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

    assert result.actions == ()
    assert result.product_status.state == "unavailable"
    assert result.product_status.reason_codes == ("CONFLICTING_DUPLICATE",)
    assert evaluator.current_state("ag") == ag


def test_one_restore_failure_does_not_stop_other_active_products() -> None:
    jm, _, _ = _recorded_machine(symbol="jm")
    restore = _RestoreReader(
        {
            "jm": jm,
            "ag": SubingStrategyMachineError("RESTORE_FIXTURE_UNAVAILABLE"),
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

    assert result.actions == ()
    assert result.product_status.state == "ready"
    current = evaluator.current_state("jm")
    assert current is not None
    assert current.pending_action is None


def test_canonical_updated_emits_terminal_close_only_when_newly_authoritative() -> None:
    holding, identity, events = _recorded_machine(event_count=761)
    terminal = AuthoritativeSegmentTerminal(
        symbol="jm",
        contract=identity.contract,
        segment_start_trading_day=identity.segment_start_trading_day,
        terminal_bar=events[759].bar,
    )
    current = _CurrentReader(terminals={("jm", TRADING_DAY): terminal})
    evaluator, _ = _ready_evaluator(holding, current=current)

    first = evaluator.process_canonical_updated(TRADING_DAY)[0]
    second = evaluator.process_canonical_updated(TRADING_DAY)[0]

    assert tuple(action.kind for action in first.actions) == (
        SubingStrategyActionKind.CLOSE_LONG,
    )
    assert first.actions[0].reason_codes == ("CONTRACT_SEGMENT_END",)
    assert second.actions == ()
    assert second.product_status.state == "ready"


def test_later_startup_does_not_reemit_restored_terminal_close() -> None:
    holding, identity, events = _recorded_machine(event_count=761)
    terminal = AuthoritativeSegmentTerminal(
        symbol="jm",
        contract=identity.contract,
        segment_start_trading_day=identity.segment_start_trading_day,
        terminal_bar=events[759].bar,
    )
    closed, output = step_subing_strategy_machine(
        holding,
        terminal,
        source_identity=identity,
    )
    assert len(output.actions) == 1
    current = _CurrentReader(terminals={("jm", TRADING_DAY): terminal})
    evaluator, _ = _ready_evaluator(closed, current=current)

    result = evaluator.process_canonical_updated(TRADING_DAY)[0]

    assert result.actions == ()
    assert result.product_status.state == "ready"
    assert evaluator.current_state("jm") == closed


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

    assert restored.actions == ()
    assert ready.actions == ()
    assert ready.product_status.state == "ready"
    current = evaluator.current_state("jm")
    assert current is not None
    assert current.position is None
