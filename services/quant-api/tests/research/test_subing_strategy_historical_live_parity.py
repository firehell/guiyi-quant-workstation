from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
import json

import pytest

from app.market_data.aggregation import aggregate_from_1m, bucket_window_for_bar
from app.market_data.domain import BarFrequency, ResolvedContractSegment
from app.market_data.subing_calibration import load_subing_calibration
from app.market_data.subing_lifecycle import ConfirmationSource
from app.market_data.subing_lifecycle_policy import load_subing_lifecycle_policy
from app.market_data.subing_strategy.contracts import SubingStrategyDirection
from app.market_data.subing_strategy.machine import (
    SubingStrategyInterval,
    SubingStrategySourceIdentity,
    initial_subing_strategy_machine,
    step_subing_strategy_machine,
    subing_strategy_segment_result,
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
