from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.market_data import subing_lifecycle as lifecycle_module
from app.market_data.subing_lifecycle import (
    ConfirmationSource,
    EntryProgress,
    LifecycleAvailability,
    LifecycleStage,
    SubingLifecycleContractError,
)
from app.market_data.domain import BarFrequency, CanonicalBar
from app.market_data.subing_research import (
    MacdCross,
    SubingDirection,
    SubingFactorStatus,
)
from research.subing_lifecycle_fixtures import (
    _bar,
    _evaluate,
    _evaluate_raw,
    _factor,
    _long_pivot_prefix,
)


_SEGMENT_START = date(2026, 8, 3)
_START = datetime(2026, 8, 3, 1, tzinfo=UTC)


def test_lifecycle_facts_are_prefix_invariant_for_every_fixture_boundary() -> None:
    bars_5m = (
        *_long_pivot_prefix(),
        _bar(35, close="112", high="113", low="111"),
        _bar(40, close="113", high="114", low="112"),
        _bar(45, close="114", high="115", low="113"),
        _bar(60, close="100", high="101", low="99"),
    )
    factors_5m = tuple(
        _factor(
            bar,
            BarFrequency.M5,
            cross=MacdCross.GOLDEN if bar.bar_end == bars_5m[5].bar_end else MacdCross.NONE,
            volume_ratio=(
                Decimal("3") if bar.bar_end == bars_5m[5].bar_end else Decimal("1")
            ),
            ema21=(
                str(bar.close + Decimal("1"))
                if bar.bar_end in {bars_5m[6].bar_end, bars_5m[7].bar_end}
                else None
            ),
            direction=(
                SubingDirection.SHORT
                if bar.bar_end == bars_5m[-1].bar_end
                else SubingDirection.LONG
            ),
        )
        for bar in bars_5m
    )
    bars_15m = (_bar(0), _bar(15), _bar(30), _bar(45), bars_5m[-1])
    factors_15m = tuple(
        _factor(
            bar,
            BarFrequency.M15,
            direction=(
                SubingDirection.SHORT
                if bar.bar_end == bars_15m[-1].bar_end
                else SubingDirection.LONG
            ),
        )
        for bar in bars_15m
    )
    full = _evaluate(
        bars_5m,
        factors_5m=factors_5m,
        bars_15m=bars_15m,
        factors_15m=factors_15m,
    )

    assert tuple(transition.reason_codes for transition in full.transitions) == (
        ("DIRECTION_CONTEXT_ALIGNED",),
        ("FORMAL_V1_MATCHED",),
        ("LOWER_TF_EMA21_BREACH",),
        ("LOWER_TF_EMA21_BREACH",),
        ("ANCHOR_RECOVERY_CONFIRMED",),
        ("OPPOSITE_DIRECTION_CONTEXT_CONFIRMED",),
    )

    for prefix_length, boundary in enumerate(bars_5m, start=1):
        visible_anchors = tuple(
            (bar, factor)
            for bar, factor in zip(bars_15m, factors_15m)
            if bar.bar_end <= boundary.bar_end
        )
        prefix = _evaluate(
            bars_5m[:prefix_length],
            factors_5m=factors_5m[:prefix_length],
            bars_15m=tuple(bar for bar, _ in visible_anchors),
            factors_15m=tuple(factor for _, factor in visible_anchors),
        )
        expected_transitions = tuple(
            transition
            for transition in full.transitions
            if transition.transition_at <= boundary.bar_end
        )
        completed_keys = {
            transition.opportunity_key
            for transition in expected_transitions
            if transition.to_stage is LifecycleStage.CLOSED
        }

        assert prefix.snapshots == full.snapshots[:prefix_length]
        assert prefix.transitions == expected_transitions
        assert prefix.confirmed_pivots == tuple(
            pivot
            for pivot in full.confirmed_pivots
            if pivot.confirmed_at <= boundary.bar_end
        )
        assert prefix.completed_opportunities == tuple(
            state
            for state in full.completed_opportunities
            if state.opportunity_key in completed_keys
        )


def test_direct_formal_without_trigger_rejects_positive_hold_count() -> None:
    boundary = _bar(15)
    snapshot = _evaluate(
        (boundary,),
        factors_5m=(
            _factor(
                boundary,
                BarFrequency.M5,
                cross=MacdCross.GOLDEN,
                volume_ratio=Decimal("3"),
            ),
        ),
        bars_15m=(boundary,),
    ).current_snapshot

    assert snapshot.trigger_kind is None
    with pytest.raises(SubingLifecycleContractError):
        replace(snapshot, hold_count=1)


def test_direct_formal_without_trigger_rejects_completed_hold_count() -> None:
    boundary = _bar(15)
    snapshot = _evaluate(
        (boundary,),
        factors_5m=(
            _factor(
                boundary,
                BarFrequency.M5,
                cross=MacdCross.GOLDEN,
                volume_ratio=Decimal("3"),
            ),
        ),
        bars_15m=(boundary,),
    ).current_snapshot

    assert snapshot.trigger_kind is None
    with pytest.raises(SubingLifecycleContractError):
        replace(snapshot, hold_count=snapshot.hold_required)


def test_closed_direction_is_not_reused_for_a_new_opposite_opportunity() -> None:
    first, close_boundary, new_boundary = (_bar(value) for value in (5, 10, 15))
    anchor_long = _bar(0)
    anchor_short = _bar(10)

    trace = _evaluate(
        (first, close_boundary, new_boundary),
        factors_5m=(
            _factor(first, BarFrequency.M5),
            _factor(close_boundary, BarFrequency.M5, direction=SubingDirection.SHORT),
            _factor(new_boundary, BarFrequency.M5, direction=SubingDirection.SHORT),
        ),
        bars_15m=(anchor_long, anchor_short),
        factors_15m=(
            _factor(anchor_long, BarFrequency.M15),
            _factor(
                anchor_short,
                BarFrequency.M15,
                direction=SubingDirection.SHORT,
            ),
        ),
    )

    old_key = trace.snapshots[0].opportunity_key
    assert old_key is not None
    assert trace.snapshots[1].stage is LifecycleStage.CLOSED
    assert trace.snapshots[1].opportunity_key == old_key
    new_key = trace.snapshots[2].opportunity_key
    assert new_key is not None
    assert new_key != old_key
    assert new_key.direction is SubingDirection.SHORT
    assert new_key.origin_at == new_boundary.bar_end


@pytest.mark.parametrize(
    "trigger_timeframe",
    (BarFrequency.M5, BarFrequency.M15),
)
def test_same_direction_macd_cross_starts_momentum_hold_at_one(
    trigger_timeframe: BarFrequency,
) -> None:
    first, trigger = (_bar(value) for value in (5, 15))
    anchor_first, anchor_trigger = (_bar(value) for value in (0, 15))
    factors_5m = (
        _factor(first, BarFrequency.M5),
        _factor(
            trigger,
            BarFrequency.M5,
            cross=(
                MacdCross.GOLDEN
                if trigger_timeframe is BarFrequency.M5
                else MacdCross.NONE
            ),
        ),
    )
    factors_15m = (
        _factor(anchor_first, BarFrequency.M15),
        _factor(
            anchor_trigger,
            BarFrequency.M15,
            cross=(
                MacdCross.GOLDEN
                if trigger_timeframe is BarFrequency.M15
                else MacdCross.NONE
            ),
        ),
    )

    trace = _evaluate(
        (first, trigger),
        factors_5m=factors_5m,
        bars_15m=(anchor_first, anchor_trigger),
        factors_15m=factors_15m,
    )

    snapshot = trace.current_snapshot
    assert snapshot.stage is LifecycleStage.SETUP_ARMED
    assert snapshot.entry_progress is EntryProgress.HOLD_CONFIRMING
    assert snapshot.trigger_kind == "macd_cross"
    assert snapshot.trigger_timeframe is trigger_timeframe
    assert snapshot.triggered_at == trigger.bar_end
    assert snapshot.hold_count == 1


def test_momentum_hold_confirms_after_three_evaluable_5m_boundaries() -> None:
    bars_5m = tuple(_bar(value) for value in (5, 10, 15, 20))
    anchor = _bar(0)
    factors_5m = tuple(
        _factor(
            bar,
            BarFrequency.M5,
            cross=MacdCross.GOLDEN if index == 1 else MacdCross.NONE,
        )
        for index, bar in enumerate(bars_5m)
    )

    trace = _evaluate(
        bars_5m,
        factors_5m=factors_5m,
        bars_15m=(anchor,),
    )

    assert tuple(snapshot.hold_count for snapshot in trace.snapshots[1:]) == (1, 2, 3)
    assert trace.current_snapshot.stage is LifecycleStage.ENTRY_CONFIRMED
    assert trace.current_snapshot.confirmation_source is ConfirmationSource.MOMENTUM_HOLD
    assert trace.current_snapshot.confirmed_at == bars_5m[-1].bar_end


def test_unavailable_boundary_pauses_momentum_hold_counter() -> None:
    bars_5m = tuple(_bar(value) for value in (5, 10, 15, 20, 25))
    anchor = _bar(0)
    factors = tuple(
        (
            _factor(bar, BarFrequency.M5, status=SubingFactorStatus.INSUFFICIENT_DATA)
            if index == 2
            else _factor(
                bar,
                BarFrequency.M5,
                cross=MacdCross.GOLDEN if index == 1 else MacdCross.NONE,
            )
        )
        for index, bar in enumerate(bars_5m)
    )

    trace = _evaluate(
        bars_5m,
        factors_5m=factors,
        bars_15m=(anchor,),
    )

    unavailable = trace.snapshots[2]
    assert unavailable.availability is LifecycleAvailability.UNAVAILABLE
    assert unavailable.entry_progress is EntryProgress.HOLD_CONFIRMING
    assert unavailable.hold_count == 1
    assert trace.snapshots[3].hold_count == 2
    assert trace.current_snapshot.hold_count == 3
    assert trace.current_snapshot.stage is LifecycleStage.ENTRY_CONFIRMED


@pytest.mark.parametrize("failure", ("opposite_cross", "persistence"))
def test_momentum_hold_closes_on_hard_failure(failure: str) -> None:
    first, trigger, failure_bar = (_bar(value) for value in (5, 10, 15))
    anchor = _bar(0)
    failed_factor = (
        _factor(failure_bar, BarFrequency.M5, cross=MacdCross.DEAD)
        if failure == "opposite_cross"
        else _factor(
            failure_bar,
            BarFrequency.M5,
            direction=SubingDirection.SHORT,
        )
    )

    trace = _evaluate(
        (first, trigger, failure_bar),
        factors_5m=(
            _factor(first, BarFrequency.M5),
            _factor(trigger, BarFrequency.M5, cross=MacdCross.GOLDEN),
            failed_factor,
        ),
        bars_15m=(anchor,),
    )

    assert trace.current_snapshot.stage is LifecycleStage.CLOSED
    assert trace.transitions[-1].reason_codes == ("MOMENTUM_HOLD_FAILED",)
    assert trace.current_snapshot.hold_count == 1


def test_pivot_break_requires_prior_confirmation_and_a_true_close_cross() -> None:
    prefix = _long_pivot_prefix()
    intrabar_only = CanonicalBar(
        bar_end=prefix[-1].bar_end,
        trading_day=prefix[-1].trading_day,
        open=Decimal("108"),
        high=Decimal("115"),
        low=Decimal("108"),
        close=Decimal("110"),
        volume=Decimal("100"),
        turnover=None,
        open_interest=Decimal("1000"),
    )
    bars = (*prefix[:-1], intrabar_only)

    trace = _evaluate(bars, bars_15m=(_bar(0),))

    assert trace.current_snapshot.entry_progress is EntryProgress.WAITING_TRIGGER
    assert trace.current_snapshot.bound_reference_pivot is None


def test_pivot_break_beats_macd_and_freezes_reference_at_trigger() -> None:
    bars = _long_pivot_prefix()
    factors = tuple(
        _factor(
            bar,
            BarFrequency.M5,
            cross=MacdCross.GOLDEN if index == len(bars) - 1 else MacdCross.NONE,
        )
        for index, bar in enumerate(bars)
    )

    trace = _evaluate(
        bars,
        factors_5m=factors,
        bars_15m=(_bar(0),),
    )

    snapshot = trace.current_snapshot
    pivot = snapshot.bound_reference_pivot
    assert pivot is not None
    assert pivot.price == Decimal("110")
    assert pivot.confirmed_at == bars[4].bar_end
    assert pivot.confirmed_at < snapshot.triggered_at
    assert snapshot.trigger_kind == "pivot_break"
    assert snapshot.trigger_timeframe is BarFrequency.M5
    assert snapshot.hold_count == 1
    assert snapshot.rebreak_reference_price == Decimal("115")


def test_formal_v1_has_priority_over_simultaneous_pivot_break() -> None:
    bars = _long_pivot_prefix()
    factors = tuple(
        _factor(
            bar,
            BarFrequency.M5,
            cross=MacdCross.GOLDEN if index == len(bars) - 1 else MacdCross.NONE,
            volume_ratio=(Decimal("3") if index == len(bars) - 1 else Decimal("1")),
        )
        for index, bar in enumerate(bars)
    )

    trace = _evaluate(bars, factors_5m=factors, bars_15m=(_bar(0),))

    assert trace.current_snapshot.stage is LifecycleStage.ENTRY_CONFIRMED
    assert trace.current_snapshot.confirmation_source is ConfirmationSource.FORMAL_V1
    assert trace.current_snapshot.bound_reference_pivot is None


def test_formal_v1_preempts_active_momentum_hold_with_prior_trigger_evidence() -> None:
    first, trigger, formal = (_bar(value) for value in (5, 10, 15))

    trace = _evaluate(
        (first, trigger, formal),
        factors_5m=(
            _factor(first, BarFrequency.M5),
            _factor(trigger, BarFrequency.M5, cross=MacdCross.GOLDEN),
            _factor(
                formal,
                BarFrequency.M5,
                cross=MacdCross.GOLDEN,
                volume_ratio=Decimal("3"),
            ),
        ),
        bars_15m=(_bar(0), _bar(15)),
    )

    snapshot = trace.current_snapshot
    assert snapshot.stage is LifecycleStage.ENTRY_CONFIRMED
    assert snapshot.confirmation_source is ConfirmationSource.FORMAL_V1
    assert snapshot.confirmed_at == formal.bar_end
    assert snapshot.trigger_kind == "macd_cross"
    assert snapshot.triggered_at == trigger.bar_end
    assert snapshot.triggered_at < snapshot.confirmed_at
    assert snapshot.hold_count == 1
    for inconsistent in (
        {"triggered_at": snapshot.confirmed_at},
        {"hold_count": 0},
        {"hold_count": snapshot.hold_required},
    ):
        with pytest.raises(SubingLifecycleContractError):
            replace(snapshot, **inconsistent)


def test_formal_v1_preempts_active_pivot_hold_with_prior_trigger_evidence() -> None:
    prefix = _long_pivot_prefix()
    formal = _bar(35, close="112", high="113", low="111")
    bars = (*prefix, formal)
    factors = tuple(
        _factor(
            bar,
            BarFrequency.M5,
            cross=MacdCross.GOLDEN if index == len(bars) - 1 else MacdCross.NONE,
            volume_ratio=(Decimal("3") if index == len(bars) - 1 else Decimal("1")),
        )
        for index, bar in enumerate(bars)
    )

    trace = _evaluate(bars, factors_5m=factors, bars_15m=(_bar(0),))

    snapshot = trace.current_snapshot
    assert snapshot.stage is LifecycleStage.ENTRY_CONFIRMED
    assert snapshot.confirmation_source is ConfirmationSource.FORMAL_V1
    assert snapshot.confirmed_at == formal.bar_end
    assert snapshot.trigger_kind == "pivot_break"
    assert snapshot.triggered_at == prefix[-1].bar_end
    assert snapshot.triggered_at < snapshot.confirmed_at
    assert snapshot.hold_count == 1
    assert snapshot.bound_reference_pivot is not None


def test_pivot_break_hold_confirms_after_three_bars_with_frozen_pivot() -> None:
    prefix = _long_pivot_prefix()
    bars = (
        *prefix,
        _bar(35, close="112", high="113", low="111"),
        _bar(40, close="113", high="114", low="112"),
    )

    trace = _evaluate(bars, bars_15m=(_bar(0),))

    assert trace.snapshots[-3].hold_count == 1
    assert trace.snapshots[-2].hold_count == 2
    assert trace.current_snapshot.hold_count == 3
    assert trace.current_snapshot.stage is LifecycleStage.ENTRY_CONFIRMED
    assert (
        trace.current_snapshot.confirmation_source
        is ConfirmationSource.PIVOT_BREAK_HOLD
    )
    assert trace.current_snapshot.bound_reference_pivot is not None
    assert trace.current_snapshot.bound_reference_pivot.price == Decimal("110")


def test_legal_retest_beats_hold_increment_and_rebreak_uses_trigger_high() -> None:
    prefix = _long_pivot_prefix()
    retest = _bar(35, close="111", high="112", low="109")
    below_trigger_high = _bar(40, close="114", high="114", low="111")
    rebreak = _bar(45, close="116", high="117", low="113")
    bars = (*prefix, retest, below_trigger_high, rebreak)

    trace = _evaluate(bars, bars_15m=(_bar(0),))

    retest_snapshot = trace.snapshots[-3]
    assert retest_snapshot.entry_progress is EntryProgress.RETEST_CONFIRMING
    assert retest_snapshot.hold_count == 1
    assert retest_snapshot.retest_at == retest.bar_end
    assert retest_snapshot.retest_rebreak_count == 0
    assert trace.snapshots[-2].retest_rebreak_count == 1
    assert trace.current_snapshot.stage is LifecycleStage.ENTRY_CONFIRMED
    assert (
        trace.current_snapshot.confirmation_source
        is ConfirmationSource.PIVOT_RETEST_REBREAK
    )
    assert trace.current_snapshot.rebreak_reference_price == Decimal("115")


@pytest.mark.parametrize(
    ("tail", "expected_reason"),
    (
        (
            (
                _bar(35, close="111", high="112", low="109"),
                _bar(40, close="112", high="113", low="111"),
                _bar(45, close="113", high="114", low="112"),
                _bar(50, close="114", high="114", low="113"),
            ),
            "RETEST_REBREAK_TIMEOUT",
        ),
        (
            (
                _bar(35, close="111", high="112", low="109"),
                _bar(40, close="109", high="111", low="108"),
            ),
            "PIVOT_RETEST_INVALIDATED",
        ),
    ),
)
def test_pivot_retest_closes_on_three_bar_timeout_or_hard_invalidation(
    tail: tuple[CanonicalBar, ...],
    expected_reason: str,
) -> None:
    trace = _evaluate((*_long_pivot_prefix(), *tail), bars_15m=(_bar(0),))

    assert trace.current_snapshot.stage is LifecycleStage.CLOSED
    assert trace.transitions[-1].reason_codes == (expected_reason,)


def test_unconfirmed_rollover_waits_for_first_evaluable_later_day_boundary() -> None:
    next_day = date(2026, 8, 4)
    first = _bar(5)
    unavailable = _bar(24 * 60 + 5, trading_day=next_day)
    evaluable = _bar(24 * 60 + 10, trading_day=next_day)
    first_anchor = _bar(0)
    next_day_anchor = _bar(24 * 60, trading_day=next_day)

    trace = _evaluate(
        (first, unavailable, evaluable),
        factors_5m=(
            _factor(first, BarFrequency.M5),
            _factor(
                unavailable,
                BarFrequency.M5,
                status=SubingFactorStatus.INSUFFICIENT_DATA,
            ),
            _factor(evaluable, BarFrequency.M5),
        ),
        bars_15m=(first_anchor, next_day_anchor),
    )

    assert trace.snapshots[1].availability is LifecycleAvailability.UNAVAILABLE
    assert trace.snapshots[1].stage is LifecycleStage.SETUP_ARMED
    assert trace.snapshots[1].opportunity_key == trace.snapshots[0].opportunity_key
    assert trace.current_snapshot.stage is LifecycleStage.CLOSED
    assert trace.transitions[-1].reason_codes == (
        "UNCONFIRMED_TRADING_DAY_ROLLOVER",
    )
    assert trace.current_snapshot.opportunity_key == trace.snapshots[0].opportunity_key


def test_next_day_same_direction_formal_v1_preempts_rollover() -> None:
    next_day = date(2026, 8, 4)
    first = _bar(5)
    next_day_boundary = _bar(24 * 60 + 15, trading_day=next_day)
    first_anchor = _bar(0)
    next_day_anchor = _bar(24 * 60 + 15, trading_day=next_day)

    trace = _evaluate(
        (first, next_day_boundary),
        factors_5m=(
            _factor(first, BarFrequency.M5),
            _factor(
                next_day_boundary,
                BarFrequency.M5,
                cross=MacdCross.GOLDEN,
                volume_ratio=Decimal("3"),
            ),
        ),
        bars_15m=(first_anchor, next_day_anchor),
    )

    old_key = trace.snapshots[0].opportunity_key
    assert old_key is not None
    assert trace.current_snapshot.stage is LifecycleStage.ENTRY_CONFIRMED
    assert trace.current_snapshot.opportunity_key == old_key
    assert trace.current_snapshot.confirmation_source is ConfirmationSource.FORMAL_V1
    assert trace.current_snapshot.confirmed_at == next_day_boundary.bar_end
    assert trace.current_snapshot.crossed_trading_day is True
    assert trace.transitions[-1].reason_codes == (
        "FORMAL_V1_MATCHED",
    )


def test_next_day_opposite_formal_v1_closes_old_setup_as_rollover() -> None:
    next_day = date(2026, 8, 4)
    first = _bar(5)
    next_day_boundary = _bar(24 * 60 + 15, trading_day=next_day)
    first_anchor = _bar(0)
    next_day_anchor = _bar(24 * 60 + 15, trading_day=next_day)

    trace = _evaluate(
        (first, next_day_boundary),
        factors_5m=(
            _factor(first, BarFrequency.M5),
            _factor(
                next_day_boundary,
                BarFrequency.M5,
                direction=SubingDirection.SHORT,
                cross=MacdCross.DEAD,
                volume_ratio=Decimal("3"),
            ),
        ),
        bars_15m=(first_anchor, next_day_anchor),
        factors_15m=(
            _factor(first_anchor, BarFrequency.M15),
            _factor(
                next_day_anchor,
                BarFrequency.M15,
                direction=SubingDirection.SHORT,
            ),
        ),
    )

    old_key = trace.snapshots[0].opportunity_key
    assert old_key is not None
    assert trace.current_snapshot.stage is LifecycleStage.CLOSED
    assert trace.current_snapshot.opportunity_key == old_key
    assert trace.current_snapshot.confirmation_source is None
    assert trace.current_snapshot.crossed_trading_day is False
    assert trace.transitions[-1].reason_codes == (
        "UNCONFIRMED_TRADING_DAY_ROLLOVER",
    )


def test_previous_trading_day_pivot_cannot_trigger_a_new_day_opportunity() -> None:
    next_day = date(2026, 8, 4)
    prior_day = _long_pivot_prefix()[:-1]
    rollover = _bar(
        24 * 60 + 5,
        close="108",
        high="109",
        low="107",
        trading_day=next_day,
    )
    new_setup = _bar(
        24 * 60 + 10,
        close="108",
        high="109",
        low="107",
        trading_day=next_day,
    )
    old_level_cross = _bar(
        24 * 60 + 15,
        close="111",
        high="112",
        low="108",
        trading_day=next_day,
    )
    next_day_anchor = _bar(24 * 60, trading_day=next_day)

    trace = _evaluate(
        (*prior_day, rollover, new_setup, old_level_cross),
        bars_15m=(_bar(0), next_day_anchor),
    )

    assert trace.current_snapshot.stage is LifecycleStage.SETUP_ARMED
    assert trace.current_snapshot.entry_progress is EntryProgress.WAITING_TRIGGER
    assert trace.current_snapshot.bound_reference_pivot is None


def test_confirmed_pivot_cursor_consumes_each_pivot_once() -> None:
    pivots = lifecycle_module._all_confirmed_pivots(
        _long_pivot_prefix(),
        contract="JM2701",
        segment_start_trading_day=_SEGMENT_START,
    )
    assert len(pivots) == 1

    class CountingPivots:
        def __init__(self, values) -> None:
            self.values = values
            self.read_count = 0

        def __len__(self) -> int:
            return len(self.values)

        def __getitem__(self, index: int):
            self.read_count += 1
            return self.values[index]

    counting = CountingPivots(pivots)
    cursor = lifecycle_module._ConfirmedPivotCursor(
        counting,
        pivot_trading_days={pivots[0].pivot_id: _SEGMENT_START},
    )
    boundaries = (_bar(25), _bar(30), _bar(35), _bar(40))

    observed = tuple(
        cursor.latest_before(boundary=boundary, kind=lifecycle_module.PivotKind.HIGH)
        for boundary in boundaries
    )

    assert observed == (None, pivots[0], pivots[0], pivots[0])
    assert counting.read_count <= len(boundaries) + len(pivots)


def test_trading_days_must_not_move_backwards_inside_a_segment() -> None:
    later_day = date(2026, 8, 4)
    first = _bar(5, trading_day=later_day)
    second = _bar(10, trading_day=_SEGMENT_START)

    trace = _evaluate_raw(
        (first, second),
        bars_15m=(_bar(0),),
    )

    assert trace.current_snapshot.availability is LifecycleAvailability.UNAVAILABLE
    assert (
        trace.current_snapshot.unavailable_reason
        == "SUBING_LIFECYCLE_SERIES_IDENTITY_INVALID"
    )
    assert all(
        snapshot.availability is LifecycleAvailability.UNAVAILABLE
        for snapshot in trace.snapshots
    )
