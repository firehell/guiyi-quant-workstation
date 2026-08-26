from __future__ import annotations

from dataclasses import asdict, replace
from datetime import timedelta

import pytest

from app.market_data.subing_calibration import load_subing_calibration
from app.market_data.subing_lifecycle import ConfirmationSource
from app.market_data.subing_lifecycle_policy import load_subing_lifecycle_policy
from app.market_data.subing_research import MacdCross, SubingDirection
from app.market_data.subing_strategy.engine import decide_completed_15m
from app.market_data.subing_strategy.machine import (
    SubingStrategyInterval,
    initial_subing_strategy_machine,
    step_subing_strategy_machine,
)
from app.market_data.subing_strategy.stream_contracts import Completed1mBar
from research.test_subing_strategy_engine import (
    CONTRACT,
    POLICY,
    SEGMENT_START,
    _bar,
    _entry_frames,
    _pivot,
    _run,
)


def _first_1m_bars(frames):
    return tuple(
        type(frame.bar)(
            bar_end=frame.bar.bar_end - timedelta(minutes=14),
            trading_day=frame.bar.trading_day,
            open=frame.bar.open,
            high=frame.bar.open,
            low=frame.bar.open,
            close=frame.bar.open,
            volume=frame.bar.volume,
            turnover=None,
            open_interest=frame.bar.open_interest,
        )
        for frame in frames
    )


def _state(frames, first_1m):
    return initial_subing_strategy_machine(
        symbol="jm",
        contract=CONTRACT,
        segment_start_trading_day=SEGMENT_START,
        calibration=load_subing_calibration(),
        lifecycle_policy=load_subing_lifecycle_policy(),
        strategy_policy=POLICY,
        direction_contexts={
            frame.bar.trading_day: frame.direction_context for frame in frames
        },
        intervals=tuple(
            SubingStrategyInterval(
                effective_bar_end=frame.bar.bar_end,
                first_1m_bar_end=minute.bar_end,
                expected_open=frame.bar.open,
            )
            for frame, minute in zip(frames, first_1m, strict=True)
        ),
    )


@pytest.mark.parametrize("source", tuple(ConfirmationSource))
def test_all_entry_sources_are_byte_equal_between_batch_and_stream(
    source: ConfirmationSource,
) -> None:
    frames = _entry_frames()[:2]
    candidate = replace(frames[0].entry_candidates[0], confirmation_source=source)
    frames = (replace(frames[0], entry_candidates=(candidate,)), frames[1])
    first_1m = _first_1m_bars(frames)
    historical = _run(frames, first_1m_bars=first_1m)
    state = _state(frames, first_1m)
    pending, consumed = decide_completed_15m(
        frame=frames[0],
        position=None,
        pending_action=None,
        consumed_opportunity_ids=frozenset(),
    )
    state = replace(
        state,
        pending_action=pending,
        consumed_opportunity_ids=consumed,
    )

    state, output = step_subing_strategy_machine(
        state,
        Completed1mBar(first_1m[1]),
    )

    assert asdict(output.actions[0]) == asdict(historical.actions[0])
    assert state.actions == output.actions


@pytest.mark.parametrize(
    ("exit_bar", "ema21", "cross", "pivot"),
    (
        (_bar(2, close="98"), "99", MacdCross.NONE, None),
        (_bar(2, close="94", high="100", low="93"), "90", MacdCross.NONE, None),
        (
            _bar(2, close="97"),
            "90",
            MacdCross.NONE,
            _pivot(SubingDirection.LONG, "98"),
        ),
        (_bar(2), "99", MacdCross.DEAD, None),
    ),
)
def test_all_exit_families_are_byte_equal_between_batch_and_stream(
    exit_bar,
    ema21: str,
    cross: MacdCross,
    pivot,
) -> None:
    frames = _entry_frames(
        pivot=pivot,
        exit_bar=exit_bar,
        exit_ema=ema21,
        exit_cross=cross,
        exit_cross_level="1",
    )
    first_1m = _first_1m_bars(frames)
    historical = _run(frames, first_1m_bars=first_1m)
    state = _state(frames, first_1m)
    pending, consumed = decide_completed_15m(
        frame=frames[0],
        position=None,
        pending_action=None,
        consumed_opportunity_ids=frozenset(),
    )
    state = replace(state, pending_action=pending, consumed_opportunity_ids=consumed)
    state, _ = step_subing_strategy_machine(state, Completed1mBar(first_1m[1]))
    pending, newly_consumed = decide_completed_15m(
        frame=frames[1],
        position=state.position,
        pending_action=state.pending_action,
        consumed_opportunity_ids=frozenset(state.consumed_opportunity_ids),
    )
    state = replace(
        state,
        pending_action=pending,
        consumed_opportunity_ids=(*state.consumed_opportunity_ids, *newly_consumed),
        completed_15m_bars=tuple(frame.bar for frame in frames[:2]),
    )

    state, output = step_subing_strategy_machine(
        state,
        Completed1mBar(first_1m[2]),
    )

    assert asdict(output.actions[0]) == asdict(historical.actions[-1])
    assert tuple(asdict(action) for action in state.actions) == tuple(
        asdict(action) for action in historical.actions
    )
    assert tuple(asdict(episode) for episode in state.closed_episodes) == tuple(
        asdict(episode) for episode in historical.episodes
    )
