from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import timedelta
from decimal import Decimal

import pytest

from app.market_data.domain import BarFrequency, CanonicalBar
from app.market_data import subing_lifecycle as lifecycle_module
from app.market_data.subing_lifecycle import (
    ConfirmationSource,
    evaluate_subing_lifecycle,
)
from app.market_data.subing_lifecycle_policy import load_subing_lifecycle_policy
from app.market_data.subing_research import (
    MacdCross,
    SubingFactorResult,
)
from research.subing_lifecycle_fixtures import (
    _SEGMENT_START,
    _accepted_calibration,
    _bar,
    _factor,
    _long_pivot_prefix,
    _stream_lifecycle_prefixes,
    _with_lifecycle_reset,
)


def _case(
    source: ConfirmationSource,
) -> tuple[
    tuple[CanonicalBar, ...],
    tuple[SubingFactorResult, ...],
    tuple[CanonicalBar, ...],
    tuple[SubingFactorResult, ...],
]:
    if source is ConfirmationSource.FORMAL_V1:
        bars = (_bar(15),)
        factors = (
            _factor(
                bars[0],
                BarFrequency.M5,
                cross=MacdCross.GOLDEN,
                volume_ratio=Decimal("3"),
            ),
        )
        anchors = (bars[0],)
    elif source is ConfirmationSource.MOMENTUM_HOLD:
        bars = tuple(_bar(minutes) for minutes in (5, 10, 15, 20))
        factors = tuple(
            _factor(
                bar,
                BarFrequency.M5,
                cross=MacdCross.GOLDEN if index == 1 else MacdCross.NONE,
            )
            for index, bar in enumerate(bars)
        )
        anchors = (_bar(0), _bar(15))
    else:
        prefix = _long_pivot_prefix()
        setup = _bar(35, close="112", high="113", low="111")
        if source is ConfirmationSource.PIVOT_BREAK_HOLD:
            tail = (setup, _bar(40, close="113", high="114", low="112"))
        else:
            tail = (
                _bar(35, close="111", high="112", low="109"),
                _bar(40, close="114", high="114", low="111"),
                _bar(45, close="116", high="117", low="113"),
            )
        bars = (*prefix, *tail)
        factors = tuple(_factor(bar, BarFrequency.M5) for bar in bars)
        anchors = (_bar(0),)
    bars, factors = _with_lifecycle_reset(bars, factors)
    return (
        bars,
        factors,
        anchors,
        tuple(_factor(bar, BarFrequency.M15) for bar in anchors),
    )


@pytest.mark.parametrize("source", tuple(ConfirmationSource))
def test_streaming_every_prefix_matches_batch_trace(source: ConfirmationSource) -> None:
    bars_5m, factors_5m, bars_15m, factors_15m = _case(source)
    states = _stream_lifecycle_prefixes(
        bars_5m,
        factors_5m=factors_5m,
        bars_15m=bars_15m,
        factors_15m=factors_15m,
    )
    calibration = _accepted_calibration()
    policy = load_subing_lifecycle_policy()

    for prefix, state in enumerate(states, start=1):
        boundary = bars_5m[prefix - 1].bar_end
        anchor_count = sum(bar.bar_end <= boundary for bar in bars_15m)
        batch = evaluate_subing_lifecycle(
            symbol="JM",
            contract="JM2701",
            segment_start_trading_day=_SEGMENT_START,
            bars_5m=bars_5m[:prefix],
            factors_5m=factors_5m[:prefix],
            bars_15m=bars_15m[:anchor_count],
            factors_15m=factors_15m[:anchor_count],
            calibration=calibration,
            policy=policy,
        )

        assert state.snapshots[-1] == batch.current_snapshot
        assert state.snapshots == batch.snapshots
        assert state.transitions == batch.transitions
        assert state.confirmed_pivots == batch.confirmed_pivots
        assert state.completed_opportunities == batch.completed_opportunities

    assert states[-1].snapshots[-1].confirmation_source is source


def test_equal_boundary_uses_new_completed_15m_anchor_before_5m_output() -> None:
    bars_5m, factors_5m, bars_15m, factors_15m = _case(ConfirmationSource.FORMAL_V1)

    state = _stream_lifecycle_prefixes(
        bars_5m,
        factors_5m=factors_5m,
        bars_15m=bars_15m,
        factors_15m=factors_15m,
    )[-1]

    assert state.snapshots[-1].anchor_bar_end == bars_5m[-1].bar_end
    assert state.snapshots[-1].confirmation_source is ConfirmationSource.FORMAL_V1


def test_streaming_preserves_risk_recovery_day_crossing_and_segment_reset() -> None:
    next_day = _SEGMENT_START + timedelta(days=1)
    confirmed, first_risk, second_risk, recovery = (
        _bar(minutes) for minutes in (15, 20, 25, 30)
    )
    crossing = _bar(35, trading_day=next_day)
    bars, factors = _with_lifecycle_reset(
        (confirmed, first_risk, second_risk, recovery, crossing),
        (
            _factor(
                confirmed,
                BarFrequency.M5,
                cross=MacdCross.GOLDEN,
                volume_ratio=Decimal("3"),
            ),
            _factor(first_risk, BarFrequency.M5, ema21="101"),
            _factor(second_risk, BarFrequency.M5, ema21="101"),
            _factor(recovery, BarFrequency.M5),
            _factor(crossing, BarFrequency.M5),
        ),
    )
    anchors = (confirmed, recovery, crossing)
    anchor_factors = tuple(_factor(bar, BarFrequency.M15) for bar in anchors)

    states = _stream_lifecycle_prefixes(
        bars,
        factors_5m=factors,
        bars_15m=anchors,
        factors_15m=anchor_factors,
    )

    assert states[0].snapshots[-1].boundary_reset == "segment_changed"
    assert tuple(transition.reason_codes for transition in states[-1].transitions) == (
        ("FORMAL_V1_MATCHED",),
        ("LOWER_TF_EMA21_BREACH",),
        ("LOWER_TF_EMA21_BREACH",),
        ("ANCHOR_RECOVERY_CONFIRMED",),
    )
    assert states[-1].snapshots[-1].crossed_trading_day is True
    assert states[-1].pivot_window == (crossing,)


def test_machine_state_is_frozen_and_rejects_out_of_order_or_other_segment() -> None:
    state = lifecycle_module.initial_subing_lifecycle_state(
        symbol="JM",
        contract="JM2701",
        segment_start_trading_day=_SEGMENT_START,
    )
    anchor = _bar(15)
    state = lifecycle_module.step_subing_lifecycle_15m(
        state,
        bar=anchor,
        factor=_factor(anchor, BarFrequency.M15),
    )

    with pytest.raises(FrozenInstanceError):
        state.latest_15m_bar_end = None  # type: ignore[misc]
    with pytest.raises(ValueError, match="SUBING_LIFECYCLE_STREAM_ORDER_INVALID"):
        lifecycle_module.step_subing_lifecycle_15m(
            state,
            bar=anchor,
            factor=_factor(anchor, BarFrequency.M15),
        )
    other_segment = _bar(
        20,
        trading_day=_SEGMENT_START - timedelta(days=1),
    )
    with pytest.raises(ValueError, match="SUBING_LIFECYCLE_STREAM_SEGMENT_INVALID"):
        lifecycle_module.step_subing_lifecycle_5m(
            state,
            bar=other_segment,
            factor=_factor(other_segment, BarFrequency.M5),
            calibration=_accepted_calibration(),
            policy=load_subing_lifecycle_policy(),
        )


def test_equal_boundary_rejects_15m_anchor_after_5m_output() -> None:
    state = lifecycle_module.initial_subing_lifecycle_state(
        symbol="JM",
        contract="JM2701",
        segment_start_trading_day=_SEGMENT_START,
    )
    initial_anchor = _bar(0)
    state = lifecycle_module.step_subing_lifecycle_15m(
        state,
        bar=initial_anchor,
        factor=_factor(initial_anchor, BarFrequency.M15),
    )
    boundary = _bar(5)
    state, _ = lifecycle_module.step_subing_lifecycle_5m(
        state,
        bar=boundary,
        factor=_factor(boundary, BarFrequency.M5),
        calibration=_accepted_calibration(),
        policy=load_subing_lifecycle_policy(),
    )

    with pytest.raises(ValueError, match="SUBING_LIFECYCLE_STREAM_ORDER_INVALID"):
        lifecycle_module.step_subing_lifecycle_15m(
            state,
            bar=boundary,
            factor=_factor(boundary, BarFrequency.M15),
        )
