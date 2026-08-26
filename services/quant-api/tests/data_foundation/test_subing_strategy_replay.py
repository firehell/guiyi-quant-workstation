from __future__ import annotations

from types import MappingProxyType

import pytest

from app.market_data.domain import ResolvedContractSegment
from app.market_data.subing_lifecycle_policy import load_subing_lifecycle_policy
from app.market_data.subing_research import (
    SubingDirection,
    SubingFactorResult,
    SubingFactorStatus,
)
from app.market_data.subing_strategy.contracts import SubingStrategyDirection
from app.market_data.subing_strategy.direction_context import (
    SubingStrategyContextIdentityError,
)
from app.market_data.subing_strategy.replay import (
    build_subing_strategy_frames,
    replay_subing_strategy_segment,
)
from app.market_data.subing_strategy.policy import load_subing_strategy_policy

from research.subing_lifecycle_fixtures import _accepted_calibration
from research.test_subing_strategy_engine import (
    CONTRACT,
    SEGMENT_START,
    _bar,
    _candidate,
    _context,
    _factor,
)
from datetime import timedelta
from dataclasses import replace


def test_build_frames_rejects_future_lifecycle_confirmation() -> None:
    bar = _bar(1)
    candidate = _candidate(bar, direction=SubingDirection.LONG)
    object.__setattr__(candidate, "confirmed_at", bar.bar_end.replace(year=2027))

    with pytest.raises(SubingStrategyContextIdentityError):
        build_subing_strategy_frames(
            bars_15m=(bar,),
            factors_15m=(SubingFactorResult(SubingFactorStatus.READY, _factor(bar)),),
            entries_by_boundary=MappingProxyType({bar.bar_end: (candidate,)}),
            direction_contexts=MappingProxyType(
                {
                    bar.trading_day: _context(
                        bar,
                        SubingStrategyDirection.LONG_ONLY,
                    )
                }
            ),
        )


def test_replay_consumes_authoritative_three_frequency_stream() -> None:
    bars_15m = (_bar(1), _bar(2, open_price="101"))
    bars_5m = bars_15m
    bars_1m = tuple(
        replace(
            bar,
            bar_end=bar.bar_end - timedelta(minutes=15 - minute),
            open=bar.open,
            high=bar.open,
            low=bar.open,
            close=bar.open,
        )
        for bar in bars_15m
        for minute in range(1, 16)
    )
    segment = ResolvedContractSegment(CONTRACT, SEGMENT_START, SEGMENT_START)
    contexts = MappingProxyType(
        {
            bar.trading_day: _context(
                bar,
                SubingStrategyDirection.LONG_ONLY,
            )
            for bar in bars_15m
        }
    )

    result = replay_subing_strategy_segment(
        symbol="jm",
        segment=segment,
        bars_1m=bars_1m,
        bars_5m=bars_5m,
        bars_15m=bars_15m,
        direction_contexts=contexts,
        calibration=_accepted_calibration(),
        lifecycle_policy=load_subing_lifecycle_policy(),
        strategy_policy=load_subing_strategy_policy(),
        terminal_bar_end=None,
    )

    assert result.actions == ()
    assert result.final_position.value == "flat"


def test_replay_rejects_15m_open_that_disagrees_with_first_1m() -> None:
    bar_15m = _bar(1)
    first_1m = replace(
        bar_15m,
        bar_end=bar_15m.bar_end - timedelta(minutes=14),
        open=bar_15m.open + 1,
    )
    segment = ResolvedContractSegment(CONTRACT, SEGMENT_START, SEGMENT_START)

    with pytest.raises(SubingStrategyContextIdentityError):
        replay_subing_strategy_segment(
            symbol="jm",
            segment=segment,
            bars_1m=(first_1m,),
            bars_5m=(bar_15m,),
            bars_15m=(bar_15m,),
            direction_contexts={
                SEGMENT_START: _context(
                    bar_15m,
                    SubingStrategyDirection.LONG_ONLY,
                )
            },
            calibration=_accepted_calibration(),
            lifecycle_policy=load_subing_lifecycle_policy(),
            strategy_policy=load_subing_strategy_policy(),
            terminal_bar_end=None,
        )
