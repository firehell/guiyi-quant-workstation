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
    ResearchStrategy,
    assess_oos_candidate,
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
        cost_snapshots=_costs(),
        execution_constraints=_constraints(bars),
    )

    assert result.strategy is ResearchStrategy.TREND
    assert result.signal_formula_versions == ("newow_trend_band_page_v2",)
    assert result.closed_trade_count == 1
    assert len(result.folds) == 1
    evaluated = result.folds[0]
    assert evaluated.warmup_bar_count == 2
    assert evaluated.test_bar_count == 3
    trade = evaluated.backtest.trades[0]
    assert trade.entry.signal_bar_end == bars[2].bar_end
    assert trade.entry.fill_bar_end == bars[3].bar_end
    assert trade.exit.signal_bar_end == bars[3].bar_end
    assert trade.exit.fill_bar_end == bars[4].bar_end
    assert all(fill.signal_bar_end >= bars[2].bar_end for fill in evaluated.backtest.fills)
    assessment = assess_oos_candidate(result)
    assert assessment.trustworthy_for_research is True
    assert assessment.closed_trade_count == result.closed_trade_count


def test_walk_forward_assessment_revalidates_aggregate_before_trusting() -> None:
    bars = _bars((100, 80, 120, 80, 90))
    result = run_fixed_formula_walk_forward(
        bars,
        (
            WalkForwardFold(
                name="fold-1",
                train_since=_START,
                train_through=_START + timedelta(days=1),
                test_since=_START + timedelta(days=2),
                test_through=_START + timedelta(days=4),
            ),
        ),
        strategy=ResearchStrategy.TREND,
        cost_snapshots=_costs(),
        execution_constraints=_constraints(bars),
    )
    object.__setattr__(result, "closed_trade_count", -1)

    with pytest.raises(ValueError, match="NEWOW_OOS_RESULT_INVALID"):
        assess_oos_candidate(result)


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
        cost_snapshots=_costs(),
        execution_constraints=_constraints(bars),
    )

    backtest = result.folds[0].backtest
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
        cost_snapshots=_costs(),
        execution_constraints=_constraints(bars),
    )

    assert result.folds[0].warmup_bar_count == 3
