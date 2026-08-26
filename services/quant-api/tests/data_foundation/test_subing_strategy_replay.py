from __future__ import annotations

from types import MappingProxyType

import pytest

from app.market_data.domain import BarFrequency, ResolvedContractSegment
from app.market_data.subing_lifecycle import ConfirmationSource
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
from research.test_subing_strategy_entry_projection import _trace_for_source


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


def test_replay_calculates_both_frequencies_from_segment_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bars_15m = (_bar(1), _bar(2, open_price="101"))
    bars_5m = bars_15m
    segment = ResolvedContractSegment(CONTRACT, SEGMENT_START, SEGMENT_START)
    calls: list[tuple[BarFrequency, str, object]] = []

    def calculate(bars, *, timeframe, contract, segment_start_trading_day, latest_bar_source):
        calls.append((timeframe, contract, segment_start_trading_day))
        return tuple(
            SubingFactorResult(SubingFactorStatus.READY, _factor(bar)) for bar in bars
        )

    candidate = _candidate(
        bars_15m[0],
        direction=SubingDirection.LONG,
    )
    monkeypatch.setattr(
        "app.market_data.subing_strategy.replay.calculate_subing_factor_series",
        calculate,
    )
    monkeypatch.setattr(
        "app.market_data.subing_strategy.replay.evaluate_subing_lifecycle",
        lambda **_kwargs: _trace_for_source(ConfirmationSource.FORMAL_V1),
    )
    monkeypatch.setattr(
        "app.market_data.subing_strategy.replay.project_lifecycle_entries",
        lambda _trace, _bars: MappingProxyType(
            {bars_15m[0].bar_end: (candidate,), bars_15m[1].bar_end: ()}
        ),
    )
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
        bars_5m=bars_5m,
        bars_15m=bars_15m,
        direction_contexts=contexts,
        calibration=_accepted_calibration(),
        lifecycle_policy=load_subing_lifecycle_policy(),
        strategy_policy=load_subing_strategy_policy(),
        terminal_bar_end=None,
    )

    assert calls == [
        (BarFrequency.M5, CONTRACT, SEGMENT_START),
        (BarFrequency.M15, CONTRACT, SEGMENT_START),
    ]
    assert result.actions[0].contract == CONTRACT
    assert result.actions[0].segment_start_trading_day == SEGMENT_START
