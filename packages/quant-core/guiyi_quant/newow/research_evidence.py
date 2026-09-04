"""Pure reporting contracts for reviewer-facing Newow futures evidence."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from enum import StrEnum

from .research_backtest import BacktestCostSnapshot, ResearchStrategy
from .research_walk_forward import (
    WalkForwardReplaySegmentResult,
    WalkForwardValidationResult,
)


class CostStressScenario(StrEnum):
    BASELINE = "baseline_sourced_costs"
    DOUBLE_COMMISSION = "double_commission"
    DOUBLE_SLIPPAGE = "double_slippage"


@dataclass(frozen=True, slots=True)
class WalkForwardEvidenceRow:
    product: str
    frequency: str
    strategy: ResearchStrategy
    scenario: CostStressScenario
    fold_name: str
    train_since: date
    train_through: date
    test_since: date
    test_through: date
    train_bar_count: int
    gap_bar_count: int
    warmup_bar_count: int
    test_bar_count: int
    test_segment_count: int
    physical_prefix_segment_count: int
    physical_prefix_bar_count: int
    earliest_physical_prefix_trading_day: date
    physical_prefix_segments: tuple[WalkForwardReplaySegmentResult, ...]
    closed_trade_count: int
    rejected_fill_count: int
    roll_exclusion_count: int
    end_exclusion_count: int
    cancelled_intent_count: int
    ignored_intent_count: int
    closed_trade_compounded_return_on_entry_cash_outlay_pct: Decimal
    closed_trade_drawdown_on_entry_cash_outlay_pct: Decimal
    win_count: int
    loss_count: int
    breakeven_count: int


def stress_cost_snapshots(
    snapshots: tuple[BacktestCostSnapshot, ...],
    scenario: CostStressScenario,
) -> tuple[BacktestCostSnapshot, ...]:
    """Apply a frozen stress while preserving multiplier, tick, and lineage."""

    if not isinstance(scenario, CostStressScenario) or not snapshots:
        raise ValueError("NEWOW_COST_STRESS_INVALID")
    if scenario is CostStressScenario.BASELINE:
        return snapshots
    stressed: list[BacktestCostSnapshot] = []
    for snapshot in snapshots:
        costs = snapshot.costs
        if scenario is CostStressScenario.DOUBLE_COMMISSION:
            costs = replace(
                costs,
                commission_rate=costs.commission_rate * 2,
                commission_per_contract=costs.commission_per_contract * 2,
            )
        else:
            costs = replace(
                costs,
                slippage_bps=costs.slippage_bps * 2,
                slippage_ticks=costs.slippage_ticks * 2,
            )
        stressed.append(replace(snapshot, costs=costs))
    return tuple(stressed)


def build_walk_forward_evidence_rows(
    result: WalkForwardValidationResult,
    *,
    product: str,
    frequency: str,
    scenario: CostStressScenario,
) -> tuple[WalkForwardEvidenceRow, ...]:
    """Flatten complete per-fold facts without inventing a promotion score."""

    if (
        not isinstance(result, WalkForwardValidationResult)
        or not product
        or product != product.lower()
        or not frequency
        or not isinstance(scenario, CostStressScenario)
    ):
        raise ValueError("NEWOW_EVIDENCE_RESULT_INVALID")
    rows: list[WalkForwardEvidenceRow] = []
    for evaluated in result.folds:
        backtest = evaluated.backtest
        if (
            backtest.frequency != frequency
            or backtest.strategy is not result.strategy
            or backtest.signal_formula_versions != result.signal_formula_versions
            or not evaluated.replay_segments
            or sum(item.bar_count for item in evaluated.replay_segments)
            != evaluated.physical_prefix_bar_count
            or min(
                item.earliest_trading_day for item in evaluated.replay_segments
            )
            != evaluated.earliest_physical_prefix_trading_day
            or len({item.segment_id for item in evaluated.replay_segments})
            != len(evaluated.replay_segments)
            or evaluated.segment_count > len(evaluated.replay_segments)
        ):
            raise ValueError("NEWOW_EVIDENCE_RESULT_INVALID")
        roll_exclusions = sum(
            item.reason == "DOMINANT_ROLL_EXCLUDED"
            for item in backtest.incomplete_positions
        )
        end_exclusions = sum(
            item.reason == "END_OF_SAMPLE_EXCLUDED"
            for item in backtest.incomplete_positions
        )
        if roll_exclusions + end_exclusions != len(backtest.incomplete_positions):
            raise ValueError("NEWOW_EVIDENCE_RESULT_INVALID")
        summary = backtest.summary
        fold = evaluated.fold
        rows.append(
            WalkForwardEvidenceRow(
                product=product,
                frequency=frequency,
                strategy=result.strategy,
                scenario=scenario,
                fold_name=fold.name,
                train_since=fold.train_since,
                train_through=fold.train_through,
                test_since=fold.test_since,
                test_through=fold.test_through,
                train_bar_count=evaluated.train_bar_count,
                gap_bar_count=evaluated.gap_bar_count,
                warmup_bar_count=evaluated.warmup_bar_count,
                test_bar_count=evaluated.test_bar_count,
                test_segment_count=evaluated.segment_count,
                physical_prefix_segment_count=len(evaluated.replay_segments),
                physical_prefix_bar_count=evaluated.physical_prefix_bar_count,
                earliest_physical_prefix_trading_day=(
                    evaluated.earliest_physical_prefix_trading_day
                ),
                physical_prefix_segments=evaluated.replay_segments,
                closed_trade_count=summary.closed_trade_count,
                rejected_fill_count=len(backtest.rejected_fills),
                roll_exclusion_count=roll_exclusions,
                end_exclusion_count=end_exclusions,
                cancelled_intent_count=backtest.cancelled_intent_count,
                ignored_intent_count=backtest.ignored_intent_count,
                closed_trade_compounded_return_on_entry_cash_outlay_pct=(
                    summary.compounded_net_return_pct
                ),
                closed_trade_drawdown_on_entry_cash_outlay_pct=(
                    summary.closed_trade_max_drawdown_pct
                ),
                win_count=summary.win_count,
                loss_count=summary.loss_count,
                breakeven_count=summary.breakeven_count,
            )
        )
    return tuple(rows)
