from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from guiyi_quant.newow import (
    BacktestCostSnapshot,
    BacktestCosts,
    BacktestExecutionConstraint,
    NewowResearchBar,
    NewowStrategyReplaySegment,
    ResearchStrategy,
    build_strategy_intents_from_replay_segments,
)
from guiyi_quant.newow.research_walk_forward import (
    WalkForwardFold,
    run_fixed_formula_walk_forward,
)


_START = date(2026, 1, 1)


def _bars(values: tuple[int, ...]) -> tuple[NewowResearchBar, ...]:
    return tuple(
        NewowResearchBar(
            product="rb",
            physical_contract="RB2610",
            segment_id="rb:RB2610:2026-01-01:2026-12-31",
            trading_day=_START + timedelta(days=index),
            bar_end=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=index),
            open=Decimal(value),
            high=Decimal(value + 1),
            low=Decimal(value - 1),
            close=Decimal(value),
            volume=100,
            open_interest=1000,
            source_identity=f"canonical-rb-1d-{index}",
            observation_eligible=True,
            completed=True,
        )
        for index, value in enumerate(values)
    )


def _costs() -> tuple[BacktestCostSnapshot, ...]:
    return (
        BacktestCostSnapshot(
            product="rb",
            physical_contract="RB2610",
            effective_from=_START,
            effective_to=date(2027, 1, 1),
            captured_at=datetime(2025, 12, 31, tzinfo=UTC),
            source_identity="fee-rb-2026",
            costs=BacktestCosts(
                contract_multiplier=Decimal("10"),
                commission_per_contract=Decimal("2"),
                price_tick=Decimal("1"),
                slippage_ticks=1,
            ),
        ),
    )


def _constraints(
    bars: tuple[NewowResearchBar, ...],
) -> tuple[BacktestExecutionConstraint, ...]:
    return tuple(
        BacktestExecutionConstraint(
            bar_source_identity=bar.source_identity,
            physical_contract=bar.physical_contract,
            limit_up=Decimal("1000"),
            limit_down=Decimal("1"),
            captured_at=datetime(2025, 12, 31, tzinfo=UTC),
            source_identity=f"limit-{bar.source_identity}",
        )
        for bar in bars
    )


def _replay(
    bars: tuple[NewowResearchBar, ...],
) -> tuple[NewowStrategyReplaySegment, ...]:
    return (NewowStrategyReplaySegment(bars),)


def _physical_prefix_bars() -> tuple[
    tuple[NewowResearchBar, ...],
    tuple[NewowResearchBar, ...],
]:
    full = _bars((80, 100, 80, 100, 80, 80))
    replay_bars = tuple(
        replace(
            bar,
            observation_eligible=index >= 2,
            source_identity=(
                bar.source_identity
                if index >= 2
                else f"canonical-contract-prefix-{index}"
            ),
            series_kind="actual_dominant" if index >= 2 else "contract",
        )
        for index, bar in enumerate(full)
    )
    return full[2:], replay_bars


def _oscillation_bars() -> tuple[NewowResearchBar, ...]:
    rows = [(100, 110, 90, 100)] * 10 + [
        (109, 110, 108, 109),
        (109, 110, 108, 109),
    ]
    return tuple(
        NewowResearchBar(
            product="rb",
            physical_contract="RB2610",
            segment_id="rb:RB2610:2026-01-01:2026-12-31",
            trading_day=_START + timedelta(days=index),
            bar_end=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=index),
            open=Decimal(open_value),
            high=Decimal(high),
            low=Decimal(low),
            close=Decimal(close),
            volume=100,
            open_interest=1000,
            source_identity=f"canonical-rb-oscillation-1d-{index}",
            observation_eligible=True,
            completed=True,
        )
        for index, (open_value, high, low, close) in enumerate(rows)
    )


def test_walk_forward_uses_training_only_as_warmup_and_scores_test_intents() -> None:
    bars = _bars((100, 80, 120, 80, 90))
    fold = WalkForwardFold(
        name="fold-1",
        train_since=_START,
        train_through=_START + timedelta(days=1),
        test_since=_START + timedelta(days=2),
        test_through=_START + timedelta(days=4),
    )

    result = run_fixed_formula_walk_forward(
        bars,
        (fold,),
        strategy=ResearchStrategy.TREND,
        strategy_replay_segments=_replay(bars),
        cost_snapshots=_costs(),
        execution_constraints=_constraints(bars),
    )

    assert result.strategy is ResearchStrategy.TREND
    assert result.signal_formula_versions == ("newow_trend_band_page_v2",)
    assert result.closed_trade_count == 1
    assert len(result.folds) == 1
    evaluated = result.folds[0]
    assert evaluated.train_bar_count == 2
    assert evaluated.gap_bar_count == 0
    assert evaluated.warmup_bar_count == 2
    assert evaluated.test_bar_count == 3
    assert evaluated.segment_count == 1
    assert evaluated.physical_prefix_bar_count == 5
    assert evaluated.earliest_physical_prefix_trading_day == _START
    trade = evaluated.backtest.trades[0]
    assert trade.entry.signal_bar_end == bars[2].bar_end
    assert trade.entry.fill_bar_end == bars[3].bar_end
    assert trade.exit.signal_bar_end == bars[3].bar_end
    assert trade.exit.fill_bar_end == bars[4].bar_end
    assert all(fill.signal_bar_end >= bars[2].bar_end for fill in evaluated.backtest.fills)


def test_walk_forward_starts_flat_and_excludes_open_test_end_position() -> None:
    bars = _bars((100, 80, 120, 130))
    result = run_fixed_formula_walk_forward(
        bars,
        (
            WalkForwardFold(
                name="open-end",
                train_since=_START,
                train_through=_START + timedelta(days=1),
                test_since=_START + timedelta(days=2),
                test_through=_START + timedelta(days=3),
            ),
        ),
        strategy=ResearchStrategy.TREND,
        strategy_replay_segments=_replay(bars),
        cost_snapshots=_costs(),
        execution_constraints=_constraints(bars),
    )

    backtest = result.folds[0].backtest
    assert backtest.trades == ()
    assert len(backtest.incomplete_positions) == 1
    assert backtest.incomplete_positions[0].reason == "END_OF_SAMPLE_EXCLUDED"
    assert result.closed_trade_count == 0


def test_walk_forward_clears_training_position_state_before_oscillation_test() -> None:
    bars = _oscillation_bars()
    result = run_fixed_formula_walk_forward(
        bars,
        (
            WalkForwardFold(
                name="oscillation-flat",
                train_since=_START,
                train_through=_START + timedelta(days=9),
                test_since=_START + timedelta(days=10),
                test_through=_START + timedelta(days=11),
            ),
        ),
        strategy=ResearchStrategy.OSCILLATION,
        strategy_replay_segments=_replay(bars),
        cost_snapshots=_costs(),
        execution_constraints=_constraints(bars),
    )

    backtest = result.folds[0].backtest
    assert result.signal_formula_versions == (
        "newow_oscillation_hhv_llv10_page_v1",
        "newow_hhv_llv_channel_page_v1",
    )
    assert backtest.fills == ()
    assert backtest.ignored_intent_count == 0
    assert backtest.cancelled_intent_count == 0


def test_walk_forward_rejects_invalid_or_overlapping_folds() -> None:
    bars = _bars((100, 80, 120, 80, 90, 100, 110))
    with pytest.raises(ValueError, match="NEWOW_WALK_FORWARD_PLAN_INVALID"):
        WalkForwardFold(
            name="invalid",
            train_since=_START,
            train_through=_START + timedelta(days=2),
            test_since=_START + timedelta(days=2),
            test_through=_START + timedelta(days=3),
        )

    overlapping = (
        WalkForwardFold(
            name="fold-a",
            train_since=_START,
            train_through=_START + timedelta(days=1),
            test_since=_START + timedelta(days=2),
            test_through=_START + timedelta(days=4),
        ),
        WalkForwardFold(
            name="fold-b",
            train_since=_START,
            train_through=_START + timedelta(days=2),
            test_since=_START + timedelta(days=4),
            test_through=_START + timedelta(days=6),
        ),
    )
    with pytest.raises(ValueError, match="NEWOW_WALK_FORWARD_PLAN_INVALID"):
        run_fixed_formula_walk_forward(
            bars,
            overlapping,
            strategy=ResearchStrategy.TREND,
            strategy_replay_segments=_replay(bars),
            cost_snapshots=_costs(),
            execution_constraints=_constraints(bars),
        )


def test_walk_forward_rejects_windows_without_available_train_or_test_bars() -> None:
    bars = _bars((100, 80, 120, 80, 90))
    outside = WalkForwardFold(
        name="outside",
        train_since=date(2025, 1, 1),
        train_through=date(2025, 1, 2),
        test_since=date(2025, 1, 3),
        test_through=date(2025, 1, 4),
    )

    with pytest.raises(ValueError, match="NEWOW_WALK_FORWARD_PLAN_INVALID"):
        run_fixed_formula_walk_forward(
            bars,
            (outside,),
            strategy=ResearchStrategy.TREND,
            strategy_replay_segments=_replay(bars),
            cost_snapshots=_costs(),
            execution_constraints=_constraints(bars),
        )


def test_walk_forward_rejects_empty_explicit_train_window_even_with_gap_bars() -> None:
    source = _bars((100, 80, 120, 90))
    bars = (source[0], source[2], source[3])
    fold = WalkForwardFold(
        name="empty-explicit-train",
        train_since=_START + timedelta(days=1),
        train_through=_START + timedelta(days=1),
        test_since=_START + timedelta(days=3),
        test_through=_START + timedelta(days=3),
    )

    with pytest.raises(ValueError, match="NEWOW_WALK_FORWARD_PLAN_INVALID"):
        run_fixed_formula_walk_forward(
            bars,
            (fold,),
            strategy=ResearchStrategy.TREND,
            strategy_replay_segments=_replay(bars),
            cost_snapshots=_costs(),
            execution_constraints=_constraints(bars),
        )


def test_walk_forward_rejects_mixed_products_across_separate_folds() -> None:
    rb_bars = _bars((100, 80, 120, 90))
    jm_bars = tuple(
        replace(
            bar,
            product="jm",
            physical_contract="JM2610",
            segment_id="jm:JM2610:2026-01-11:2026-12-31",
            trading_day=bar.trading_day + timedelta(days=10),
            bar_end=bar.bar_end + timedelta(days=10),
            source_identity=f"canonical-jm-1d-{index}",
        )
        for index, bar in enumerate(rb_bars)
    )
    folds = (
        WalkForwardFold(
            name="rb",
            train_since=_START,
            train_through=_START + timedelta(days=1),
            test_since=_START + timedelta(days=2),
            test_through=_START + timedelta(days=3),
        ),
        WalkForwardFold(
            name="jm",
            train_since=_START + timedelta(days=10),
            train_through=_START + timedelta(days=11),
            test_since=_START + timedelta(days=12),
            test_through=_START + timedelta(days=13),
        ),
    )

    with pytest.raises(ValueError, match="NEWOW_WALK_FORWARD_PLAN_INVALID"):
        run_fixed_formula_walk_forward(
            rb_bars + jm_bars,
            folds,
            strategy=ResearchStrategy.TREND,
            strategy_replay_segments=(
                NewowStrategyReplaySegment(rb_bars),
                NewowStrategyReplaySegment(jm_bars),
            ),
            cost_snapshots=_costs(),
            execution_constraints=_constraints(rb_bars + jm_bars),
        )


def test_walk_forward_rejects_a_fold_that_partly_exceeds_available_history() -> None:
    bars = _bars((100, 80, 120, 80, 90))
    partly_outside = WalkForwardFold(
        name="partial",
        train_since=date(2025, 12, 31),
        train_through=_START,
        test_since=_START + timedelta(days=1),
        test_through=_START + timedelta(days=3),
    )

    with pytest.raises(ValueError, match="NEWOW_WALK_FORWARD_PLAN_INVALID"):
        run_fixed_formula_walk_forward(
            bars,
            (partly_outside,),
            strategy=ResearchStrategy.TREND,
            strategy_replay_segments=_replay(bars),
            cost_snapshots=_costs(),
            execution_constraints=_constraints(bars),
        )


def test_walk_forward_counts_the_full_causal_prefix_before_test() -> None:
    bars = _bars((100, 80, 90, 120, 100))
    result = run_fixed_formula_walk_forward(
        bars,
        (
            WalkForwardFold(
                name="gap-prefix",
                train_since=_START,
                train_through=_START + timedelta(days=1),
                test_since=_START + timedelta(days=3),
                test_through=_START + timedelta(days=4),
            ),
        ),
        strategy=ResearchStrategy.TREND,
        strategy_replay_segments=_replay(bars),
        cost_snapshots=_costs(),
        execution_constraints=_constraints(bars),
    )

    assert result.folds[0].warmup_bar_count == 3
    assert result.folds[0].train_bar_count == 2
    assert result.folds[0].gap_bar_count == 1


def test_walk_forward_uses_noneligible_physical_prefix_for_strategy_state_only() -> None:
    bars, replay_bars = _physical_prefix_bars()
    fold = WalkForwardFold(
        name="physical-prefix",
        train_since=bars[0].trading_day,
        train_through=bars[0].trading_day,
        test_since=bars[1].trading_day,
        test_through=bars[-1].trading_day,
    )

    result = run_fixed_formula_walk_forward(
        bars,
        (fold,),
        strategy=ResearchStrategy.TREND,
        strategy_replay_segments=(NewowStrategyReplaySegment(replay_bars),),
        cost_snapshots=_costs(),
        execution_constraints=_constraints(bars),
    )

    trade = result.folds[0].backtest.trades[0]
    assert trade.entry.signal_bar_end == bars[1].bar_end
    assert trade.entry.fill_bar_end == bars[2].bar_end
    assert trade.exit.signal_bar_end == bars[2].bar_end
    assert trade.exit.fill_bar_end == bars[3].bar_end
    assert all(
        fill.fill_bar_end in {bar.bar_end for bar in bars}
        for fill in result.folds[0].backtest.fills
    )
    assert result.folds[0].physical_prefix_bar_count == 6
    assert result.folds[0].earliest_physical_prefix_trading_day == _START


def test_walk_forward_requires_cost_snapshot_for_noneligible_physical_prefix() -> None:
    bars, replay_bars = _physical_prefix_bars()
    fold = WalkForwardFold(
        name="physical-prefix-missing-cost",
        train_since=bars[0].trading_day,
        train_through=bars[0].trading_day,
        test_since=bars[1].trading_day,
        test_through=bars[-1].trading_day,
    )
    cost_snapshots = (
        replace(_costs()[0], effective_from=bars[0].trading_day),
    )

    with pytest.raises(ValueError, match="NEWOW_BACKTEST_COST_SNAPSHOT_MISSING"):
        run_fixed_formula_walk_forward(
            bars,
            (fold,),
            strategy=ResearchStrategy.TREND,
            strategy_replay_segments=(NewowStrategyReplaySegment(replay_bars),),
            cost_snapshots=cost_snapshots,
            execution_constraints=_constraints(bars),
        )


def test_walk_forward_validates_tick_for_noneligible_physical_prefix() -> None:
    bars, replay_bars = _physical_prefix_bars()
    replay_bars = (
        replace(
            replay_bars[0],
            open=Decimal("80.5"),
            high=Decimal("81.5"),
            low=Decimal("79.5"),
            close=Decimal("80.5"),
        ),
        *replay_bars[1:],
    )
    fold = WalkForwardFold(
        name="physical-prefix-tick-mismatch",
        train_since=bars[0].trading_day,
        train_through=bars[0].trading_day,
        test_since=bars[1].trading_day,
        test_through=bars[-1].trading_day,
    )

    with pytest.raises(ValueError, match="NEWOW_BACKTEST_BAR_PRICE_TICK_MISMATCH"):
        run_fixed_formula_walk_forward(
            bars,
            (fold,),
            strategy=ResearchStrategy.TREND,
            strategy_replay_segments=(NewowStrategyReplaySegment(replay_bars),),
            cost_snapshots=_costs(),
            execution_constraints=_constraints(bars),
        )


def test_walk_forward_does_not_validate_prefix_after_fold_test_window() -> None:
    bars, replay_bars = _physical_prefix_bars()
    future_prefix = replace(
        replay_bars[-1],
        trading_day=replay_bars[-1].trading_day + timedelta(days=1),
        bar_end=replay_bars[-1].bar_end + timedelta(days=1),
        open=Decimal("80.5"),
        high=Decimal("81.5"),
        low=Decimal("79.5"),
        close=Decimal("80.5"),
        observation_eligible=False,
        source_identity="canonical-contract-future-prefix",
        series_kind="contract",
    )
    fold = WalkForwardFold(
        name="bounded-physical-prefix",
        train_since=bars[0].trading_day,
        train_through=bars[0].trading_day,
        test_since=bars[1].trading_day,
        test_through=bars[-1].trading_day,
    )

    result = run_fixed_formula_walk_forward(
        bars,
        (fold,),
        strategy=ResearchStrategy.TREND,
        strategy_replay_segments=(
            NewowStrategyReplaySegment(replay_bars + (future_prefix,)),
        ),
        cost_snapshots=_costs(),
        execution_constraints=_constraints(bars),
    )

    assert result.folds[0].physical_prefix_bar_count == len(replay_bars)


def test_walk_forward_rejects_replay_eligible_bar_fact_mismatch() -> None:
    bars = _bars((100, 80, 120, 80))
    replay_bars = bars[:2] + (
        replace(
            bars[2],
            open=Decimal("121"),
            high=Decimal("122"),
            close=Decimal("121"),
        ),
    ) + bars[3:]

    with pytest.raises(ValueError, match="NEWOW_WALK_FORWARD_PLAN_INVALID"):
        run_fixed_formula_walk_forward(
            bars,
            (
                WalkForwardFold(
                    "mismatch",
                    bars[0].trading_day,
                    bars[1].trading_day,
                    bars[2].trading_day,
                    bars[3].trading_day,
                ),
            ),
            strategy=ResearchStrategy.TREND,
            strategy_replay_segments=(NewowStrategyReplaySegment(replay_bars),),
            cost_snapshots=_costs(),
            execution_constraints=_constraints(bars),
        )


def test_oscillation_flattens_at_first_eligible_test_bar_not_hidden_prefix() -> None:
    rows = [(100, 109, 90, 100)] * 12
    bars = tuple(
        NewowResearchBar(
            product="rb",
            physical_contract="RB2610",
            segment_id="rb:RB2610:2026-01-01:2026-12-31",
            trading_day=_START + timedelta(days=index),
            bar_end=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=index),
            open=Decimal(open_value),
            high=Decimal(high),
            low=Decimal(low),
            close=Decimal(close),
            volume=100,
            open_interest=1000,
            source_identity=f"oscillation-prefix-{index}",
            observation_eligible=index == 11,
            completed=True,
            series_kind="actual_dominant" if index == 11 else "contract",
        )
        for index, (open_value, high, low, close) in enumerate(rows)
    )

    intents, _ = build_strategy_intents_from_replay_segments(
        (NewowStrategyReplaySegment(bars),),
        ResearchStrategy.OSCILLATION,
        flat_from=bars[10].trading_day,
    )

    assert len(intents) == 1
    assert intents[0].signal_bar_end == bars[11].bar_end
