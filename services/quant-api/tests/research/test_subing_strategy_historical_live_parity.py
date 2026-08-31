from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import Enum
import json

import pytest

from app.alerts.subing_strategy_runtime import (
    SubingStrategyRuntimeActionFact,
    SubingStrategyRuntimeEvaluator,
)
from app.market_data.aggregation import (
    SessionWindow,
    aggregate_from_1m,
    bucket_window_for_bar,
)
from app.market_data.domain import BarFrequency, CanonicalBar, ResolvedContractSegment
from app.market_data.subing_calibration import load_subing_calibration
from app.market_data.subing_lifecycle import ConfirmationSource
from app.market_data.subing_lifecycle_policy import load_subing_lifecycle_policy
from app.market_data.subing_strategy.contracts import SubingStrategyDirection
from app.market_data.subing_strategy.machine import (
    SubingStrategyInterval,
    SubingStrategyMachineState,
    SubingStrategySourceIdentity,
    authoritative_subing_strategy_intervals,
    initial_subing_strategy_machine,
    step_subing_strategy_machine,
    subing_strategy_segment_result,
)
from app.market_data.subing_strategy.live_continuation import (
    SubingLiveContinuationDecision,
    SubingLiveContinuationKind,
)
from app.market_data.subing_strategy.policy import load_subing_strategy_policy
from app.market_data.subing_strategy.replay import replay_subing_strategy_segment
from app.market_data.subing_strategy.stream_contracts import (
    AuthoritativeSegmentTerminal,
    Completed1mBar,
    Completed5mBar,
    Completed15mBar,
)
from research.subing_strategy_fixtures import recorded_strategy_stream
from research.test_subing_strategy_engine import _context


CONTRACT = "JM2701"
STARTED_AT = datetime(2026, 8, 3, 9, 59, 30, tzinfo=UTC)
READY_AT = datetime(2026, 8, 3, 10, 1, 30, tzinfo=UTC)


class _RuntimeRestoreReader:
    def __init__(self, state: SubingStrategyMachineState) -> None:
        self.state = state

    def restore(
        self,
        *,
        symbol: str,
        started_at: datetime,
    ) -> SubingStrategyMachineState:
        assert symbol == self.state.symbol
        assert started_at == STARTED_AT
        return self.state


class _RuntimeCurrentReader:
    def __init__(self, sessions: tuple[SessionWindow, ...]) -> None:
        self.sessions = sessions

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
        del symbol, source_identity, after_1m, after_5m, after_15m
        assert through == READY_AT
        return {}

    def resolve_live_continuation(
        self,
        *,
        symbol: str,
        source_identity: SubingStrategySourceIdentity,
        incoming_trading_day: date,
        now: datetime,
    ) -> SubingLiveContinuationDecision:
        del now
        assert symbol == source_identity.symbol
        return SubingLiveContinuationDecision(
            kind=SubingLiveContinuationKind.CONTINUE_SAME_SEGMENT,
            machine_identity=source_identity,
            incoming_trading_day=incoming_trading_day,
            market_trading_day=incoming_trading_day,
            frozen_live_contract=source_identity.contract,
            live_eligible=True,
            live_available=True,
            direction_context=None,
        )

    def read_session_windows(
        self,
        *,
        symbol: str,
        trading_day: date,
        source_identity: SubingStrategySourceIdentity,
    ) -> tuple[SessionWindow, ...]:
        assert symbol == source_identity.symbol
        assert trading_day == source_identity.segment_start_trading_day
        return self.sessions

    def read_authoritative_terminal(
        self,
        *,
        symbol: str,
        trading_day: date,
        source_identity: SubingStrategySourceIdentity,
    ) -> AuthoritativeSegmentTerminal | None:
        del symbol, trading_day, source_identity
        return None


def test_recorded_stream_has_authoritative_cross_frequency_bytes() -> None:
    recorded = recorded_strategy_stream(18, SubingStrategyDirection.LONG_ONLY)

    assert (
        aggregate_from_1m(
            recorded.bars_1m,
            target_frequency=BarFrequency.M5,
            sessions=recorded.sessions,
        )
        == recorded.bars_5m
    )
    assert (
        aggregate_from_1m(
            recorded.bars_1m,
            target_frequency=BarFrequency.M15,
            sessions=recorded.sessions,
        )
        == recorded.bars_15m
    )


@pytest.mark.parametrize("boundary_order", ("5m_first", "15m_first"))
def test_runtime_evaluator_matches_historical_for_every_completed_15m_prefix(
    boundary_order: str,
) -> None:
    recorded = recorded_strategy_stream(18, SubingStrategyDirection.LONG_ONLY)
    trading_day = recorded.bars_15m[0].trading_day
    context = _context(recorded.bars_15m[0], SubingStrategyDirection.LONG_ONLY)
    identity = SubingStrategySourceIdentity("jm", CONTRACT, trading_day)
    state = initial_subing_strategy_machine(
        symbol="jm",
        contract=CONTRACT,
        segment_start_trading_day=trading_day,
        calibration=load_subing_calibration(),
        lifecycle_policy=load_subing_lifecycle_policy(),
        strategy_policy=load_subing_strategy_policy(),
        direction_contexts={trading_day: context},
        intervals=authoritative_subing_strategy_intervals(
            bars_1m=recorded.bars_1m,
            bars_15m=recorded.bars_15m,
            sessions=recorded.sessions,
        ),
    )
    evaluator = SubingStrategyRuntimeEvaluator(
        ("jm",),
        restore_reader=_RuntimeRestoreReader(state),
        current_reader=_RuntimeCurrentReader(recorded.sessions),
    )
    evaluator.restore_all(started_at=STARTED_AT)
    ready = evaluator.final_catch_up(ready_at=READY_AT)
    assert ready[0].product_status.state == "ready"
    assert ready[0].action_facts == ()

    events_by_end: dict[datetime, list[tuple[BarFrequency, CanonicalBar]]] = defaultdict(
        list
    )
    for frequency, bars in (
        (BarFrequency.M1, recorded.bars_1m),
        (BarFrequency.M5, recorded.bars_5m),
        (BarFrequency.M15, recorded.bars_15m),
    ):
        for bar in bars:
            events_by_end[bar.bar_end].append((frequency, bar))
    rank = {
        BarFrequency.M1: 0,
        BarFrequency.M5: 1 if boundary_order == "5m_first" else 2,
        BarFrequency.M15: 2 if boundary_order == "5m_first" else 1,
    }

    emitted: list[SubingStrategyRuntimeActionFact] = []
    boundary_count = 0
    for bar_end in sorted(events_by_end):
        group = sorted(events_by_end[bar_end], key=lambda item: rank[item[0]])
        for frequency, bar in group:
            result = evaluator.process_completed_bar(
                bar,
                frequency,
                source_identity=identity,
            )
            assert result.product_status.state == "ready"
            emitted.extend(result.action_facts)
        if any(frequency is BarFrequency.M15 for frequency, _ in group):
            boundary_count += 1
            historical = replay_subing_strategy_segment(
                symbol="jm",
                segment=ResolvedContractSegment(CONTRACT, trading_day, trading_day),
                bars_1m=recorded.bars_1m[: boundary_count * 15],
                bars_5m=recorded.bars_5m[: boundary_count * 3],
                bars_15m=recorded.bars_15m[:boundary_count],
                sessions=recorded.sessions,
                direction_contexts={trading_day: context},
                calibration=load_subing_calibration(),
                lifecycle_policy=load_subing_lifecycle_policy(),
                strategy_policy=load_subing_strategy_policy(),
                terminal_bar_end=None,
            ).actions
            assert tuple(fact.action for fact in emitted) == historical
            if boundary_count <= 12:
                assert emitted == []


def _json_default(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(type(value).__name__)


def _serialized(records: tuple[object, ...]) -> bytes:
    return json.dumps(
        [asdict(record) for record in records],
        default=_json_default,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _streamed_result(
    seed: int,
    direction: SubingStrategyDirection,
    *,
    terminal: bool,
):
    recorded = recorded_strategy_stream(seed, direction)
    trading_day = recorded.bars_15m[0].trading_day
    context = _context(recorded.bars_15m[0], direction)
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
        symbol="jm",
        contract=CONTRACT,
        segment_start_trading_day=trading_day,
        calibration=load_subing_calibration(),
        lifecycle_policy=load_subing_lifecycle_policy(),
        strategy_policy=load_subing_strategy_policy(),
        direction_contexts={trading_day: context},
        intervals=intervals,
    )
    identity = SubingStrategySourceIdentity(
        symbol="jm",
        contract=CONTRACT,
        segment_start_trading_day=trading_day,
    )
    events = [*(Completed1mBar(bar) for bar in recorded.bars_1m)]
    events.extend(Completed5mBar(bar) for bar in recorded.bars_5m)
    events.extend(Completed15mBar(bar) for bar in recorded.bars_15m)
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
    cancellations = []
    for event in events:
        state, output = step_subing_strategy_machine(
            state,
            event,
            source_identity=identity,
        )
        cancellations.extend(output.cancellations)
    if terminal:
        state, output = step_subing_strategy_machine(
            state,
            AuthoritativeSegmentTerminal(
                symbol="jm",
                contract=CONTRACT,
                segment_start_trading_day=trading_day,
                terminal_bar=recorded.bars_15m[-1],
            ),
            source_identity=identity,
        )
        cancellations.extend(output.cancellations)
    result = subing_strategy_segment_result(
        state,
        canceled_pending=tuple(cancellations),
    )
    return recorded, result


def _historical_result(
    seed: int,
    direction: SubingStrategyDirection,
    *,
    terminal: bool,
):
    recorded = recorded_strategy_stream(seed, direction)
    trading_day = recorded.bars_15m[0].trading_day
    result = replay_subing_strategy_segment(
        symbol="jm",
        segment=ResolvedContractSegment(CONTRACT, trading_day, trading_day),
        bars_1m=recorded.bars_1m,
        bars_5m=recorded.bars_5m,
        bars_15m=recorded.bars_15m,
        sessions=recorded.sessions,
        direction_contexts={trading_day: _context(recorded.bars_15m[0], direction)},
        calibration=load_subing_calibration(),
        lifecycle_policy=load_subing_lifecycle_policy(),
        strategy_policy=load_subing_strategy_policy(),
        terminal_bar_end=(recorded.bars_15m[-1].bar_end if terminal else None),
    )
    return recorded, result


@pytest.mark.parametrize(
    ("source", "seed", "direction"),
    (
        (ConfirmationSource.FORMAL_V1, 18, SubingStrategyDirection.LONG_ONLY),
        (ConfirmationSource.MOMENTUM_HOLD, 32, SubingStrategyDirection.SHORT_ONLY),
        (ConfirmationSource.PIVOT_BREAK_HOLD, 8, SubingStrategyDirection.SHORT_ONLY),
        (
            ConfirmationSource.PIVOT_RETEST_REBREAK,
            18,
            SubingStrategyDirection.LONG_ONLY,
        ),
    ),
)
def test_complete_stream_is_byte_equal_for_every_entry_source(
    source: ConfirmationSource,
    seed: int,
    direction: SubingStrategyDirection,
) -> None:
    _, historical = _historical_result(seed, direction, terminal=True)
    _, streamed = _streamed_result(seed, direction, terminal=True)

    assert source in {
        action.confirmation_source
        for action in historical.actions
        if action.confirmation_source is not None
    }
    assert _serialized(streamed.actions) == _serialized(historical.actions)
    assert _serialized(streamed.episodes) == _serialized(historical.episodes)


@pytest.mark.parametrize(
    ("reason_prefix", "seed", "direction"),
    (
        ("EMA21_", 19, SubingStrategyDirection.LONG_ONLY),
        ("PREVIOUS_BAR_", 4, SubingStrategyDirection.SHORT_ONLY),
        ("BOUND_", 19, SubingStrategyDirection.LONG_ONLY),
        ("MACD_", 15, SubingStrategyDirection.LONG_ONLY),
    ),
)
def test_complete_stream_is_byte_equal_for_every_exit_family(
    reason_prefix: str,
    seed: int,
    direction: SubingStrategyDirection,
) -> None:
    _, historical = _historical_result(seed, direction, terminal=False)
    _, streamed = _streamed_result(seed, direction, terminal=False)

    assert any(
        reason.startswith(reason_prefix)
        for action in historical.actions
        for reason in action.reason_codes
    )
    assert _serialized(streamed.actions) == _serialized(historical.actions)
    assert _serialized(streamed.episodes) == _serialized(historical.episodes)
