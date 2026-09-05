from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from guiyi_quant.newow import (
    BacktestCostSnapshot,
    BacktestCosts,
    BacktestSummary,
    CostStressScenario,
    ResearchBacktestResult,
    ResearchStrategy,
    WalkForwardFold,
    WalkForwardFoldResult,
    WalkForwardReplaySegmentResult,
    WalkForwardValidationResult,
    build_walk_forward_evidence_rows,
    stress_cost_snapshots,
)


def _snapshot() -> BacktestCostSnapshot:
    return BacktestCostSnapshot(
        product="rb",
        physical_contract="RB2610",
        effective_from=date(2026, 1, 1),
        effective_to=date(2027, 1, 1),
        captured_at=datetime(2025, 12, 31, tzinfo=UTC),
        source_identity="sha256:baseline",
        costs=BacktestCosts(
            commission_rate=Decimal("0.0001"),
            commission_per_contract=Decimal("2"),
            contract_multiplier=Decimal("10"),
            slippage_bps=Decimal("3"),
            price_tick=Decimal("1"),
            slippage_ticks=1,
        ),
    )


def test_cost_stress_changes_only_the_requested_cost_dimension() -> None:
    baseline = _snapshot()

    double_commission = stress_cost_snapshots(
        (baseline,), CostStressScenario.DOUBLE_COMMISSION
    )[0]
    double_slippage = stress_cost_snapshots(
        (baseline,), CostStressScenario.DOUBLE_SLIPPAGE
    )[0]

    assert double_commission.costs.commission_rate == Decimal("0.0002")
    assert double_commission.costs.commission_per_contract == Decimal("4")
    assert double_commission.costs.slippage_bps == Decimal("3")
    assert double_commission.costs.slippage_ticks == 1
    assert double_slippage.costs.commission_rate == Decimal("0.0001")
    assert double_slippage.costs.commission_per_contract == Decimal("2")
    assert double_slippage.costs.slippage_bps == Decimal("6")
    assert double_slippage.costs.slippage_ticks == 2
    for stressed in (double_commission, double_slippage):
        assert stressed.costs.contract_multiplier == Decimal("10")
        assert stressed.costs.price_tick == Decimal("1")
        assert stressed.source_identity == baseline.source_identity


def test_fold_evidence_reports_required_nonaggregate_dimensions() -> None:
    fold = WalkForwardFold(
        "2026",
        date(2025, 1, 1),
        date(2025, 12, 31),
        date(2026, 1, 1),
        date(2026, 12, 31),
    )
    backtest = ResearchBacktestResult(
        frequency="1d",
        strategy=ResearchStrategy.TREND,
        formula_version="newow_causal_next_open_costed_v1",
        signal_formula_versions=("newow_trend_band_page_v2",),
        costs=BacktestCosts(),
        cost_snapshot_identities=("sha256:baseline",),
        fills=(),
        rejected_fills=(),
        trades=(),
        incomplete_positions=(),
        cancelled_intent_count=2,
        ignored_intent_count=1,
        summary=BacktestSummary(
            closed_trade_count=3,
            win_count=2,
            loss_count=1,
            breakeven_count=0,
            compounded_net_return_pct=Decimal("4.5"),
            closed_trade_max_drawdown_pct=Decimal("2.25"),
        ),
    )
    result = WalkForwardValidationResult(
        strategy=ResearchStrategy.TREND,
        signal_formula_versions=("newow_trend_band_page_v2",),
        folds=(
            WalkForwardFoldResult(
                fold=fold,
                train_bar_count=200,
                gap_bar_count=5,
                warmup_bar_count=205,
                test_bar_count=210,
                segment_count=3,
                physical_prefix_bar_count=240,
                earliest_physical_prefix_trading_day=date(2024, 6, 1),
                replay_segments=(
                    WalkForwardReplaySegmentResult(
                        "RB2505",
                        "rb:RB2505:2024-01-01:2024-12-31",
                        80,
                        70,
                        date(2024, 6, 1),
                        date(2025, 12, 31),
                    ),
                    WalkForwardReplaySegmentResult(
                        "RB2510",
                        "rb:RB2510:2025-01-01:2025-12-31",
                        80,
                        70,
                        date(2024, 7, 1),
                        date(2026, 6, 30),
                    ),
                    WalkForwardReplaySegmentResult(
                        "RB2605",
                        "rb:RB2605:2026-01-01:2026-12-31",
                        80,
                        70,
                        date(2024, 8, 1),
                        date(2026, 12, 31),
                    ),
                ),
                backtest=backtest,
            ),
        ),
        closed_trade_count=3,
        compounded_net_return_pct=Decimal("4.5"),
    )

    rows = build_walk_forward_evidence_rows(
        result,
        product="rb",
        frequency="1d",
        scenario=CostStressScenario.BASELINE,
    )

    assert len(rows) == 1
    row = rows[0]
    assert (row.product, row.frequency, row.fold_name) == ("rb", "1d", "2026")
    assert (row.train_bar_count, row.gap_bar_count, row.test_bar_count) == (
        200,
        5,
        210,
    )
    assert row.test_segment_count == 3
    assert row.physical_prefix_segment_count == 3
    assert row.physical_prefix_bar_count == 240
    assert row.earliest_physical_prefix_trading_day == date(2024, 6, 1)
    assert len(row.physical_prefix_segments) == 3
    assert row.physical_prefix_segments[0].physical_contract == "RB2505"
    assert row.closed_trade_count == 3
    assert row.cancelled_intent_count == 2
    assert row.ignored_intent_count == 1
    assert row.closed_trade_compounded_return_on_entry_cash_outlay_pct == Decimal(
        "4.5"
    )
    assert row.closed_trade_drawdown_on_entry_cash_outlay_pct == Decimal("2.25")
    assert (row.win_count, row.loss_count) == (2, 1)
    assert row.breakeven_count == 0

    inconsistent = replace(
        result,
        folds=(replace(result.folds[0], segment_count=4),),
    )
    with pytest.raises(ValueError, match="NEWOW_EVIDENCE_RESULT_INVALID"):
        build_walk_forward_evidence_rows(
            inconsistent,
            product="rb",
            frequency="1d",
            scenario=CostStressScenario.BASELINE,
        )
