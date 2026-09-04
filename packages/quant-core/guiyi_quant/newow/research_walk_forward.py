"""Anchored walk-forward evaluation for frozen Newow research formulas."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .research_backtest import (
    BacktestCostSnapshot,
    BacktestExecutionConstraint,
    NewowResearchBar,
    NewowStrategyReplaySegment,
    ResearchBacktestResult,
    ResearchStrategy,
    build_strategy_intents_from_replay_segments,
    run_causal_long_only_backtest,
    validate_research_bars,
)


_PLAN_ERROR = "NEWOW_WALK_FORWARD_PLAN_INVALID"


@dataclass(frozen=True, slots=True)
class WalkForwardFold:
    name: str
    train_since: date
    train_through: date
    test_since: date
    test_through: date

    def __post_init__(self) -> None:
        dates = (
            self.train_since,
            self.train_through,
            self.test_since,
            self.test_through,
        )
        if (
            not self.name
            or any(type(value) is not date for value in dates)
            or self.train_since > self.train_through
            or self.train_through >= self.test_since
            or self.test_since > self.test_through
        ):
            raise ValueError(_PLAN_ERROR)


@dataclass(frozen=True, slots=True)
class WalkForwardFoldResult:
    fold: WalkForwardFold
    train_bar_count: int
    gap_bar_count: int
    warmup_bar_count: int
    test_bar_count: int
    segment_count: int
    physical_prefix_bar_count: int
    earliest_physical_prefix_trading_day: date
    replay_segments: tuple[WalkForwardReplaySegmentResult, ...]
    backtest: ResearchBacktestResult


@dataclass(frozen=True, slots=True)
class WalkForwardReplaySegmentResult:
    physical_contract: str
    segment_id: str
    bar_count: int
    eligible_bar_count: int
    earliest_trading_day: date
    latest_trading_day: date


@dataclass(frozen=True, slots=True)
class WalkForwardValidationResult:
    strategy: ResearchStrategy
    signal_formula_versions: tuple[str, ...]
    folds: tuple[WalkForwardFoldResult, ...]
    closed_trade_count: int
    compounded_net_return_pct: Decimal


def _validate_folds(folds: tuple[WalkForwardFold, ...]) -> None:
    if not folds or len({fold.name for fold in folds}) != len(folds):
        raise ValueError(_PLAN_ERROR)
    previous_test_through: date | None = None
    for fold in folds:
        if (
            not isinstance(fold, WalkForwardFold)
            or (
                previous_test_through is not None
                and fold.test_since <= previous_test_through
            )
        ):
            raise ValueError(_PLAN_ERROR)
        previous_test_through = fold.test_through


def run_fixed_formula_walk_forward(
    bars: tuple[NewowResearchBar, ...],
    folds: tuple[WalkForwardFold, ...],
    *,
    strategy: ResearchStrategy,
    strategy_replay_segments: tuple[NewowStrategyReplaySegment, ...],
    cost_snapshots: tuple[BacktestCostSnapshot, ...],
    execution_constraints: tuple[BacktestExecutionConstraint, ...],
) -> WalkForwardValidationResult:
    """Score fixed formulas OOS while using earlier fold Bars only as warm-up."""

    if not isinstance(strategy, ResearchStrategy):
        raise ValueError(_PLAN_ERROR)
    _validate_folds(folds)
    if not bars:
        raise ValueError(_PLAN_ERROR)
    try:
        validate_research_bars(bars)
    except ValueError:
        raise ValueError(_PLAN_ERROR) from None
    if not strategy_replay_segments:
        raise ValueError(_PLAN_ERROR)
    execution_bar_ends = {bar.bar_end for bar in bars}
    eligible_replay_ends = {
        bar.bar_end
        for segment in strategy_replay_segments
        for bar in segment.bars
        if bar.observation_eligible
    }
    eligible_replay_bars = tuple(
        bar
        for segment in strategy_replay_segments
        for bar in segment.bars
        if bar.observation_eligible
    )
    if (
        eligible_replay_ends != execution_bar_ends
        or len(eligible_replay_bars) != len(bars)
    ):
        raise ValueError(_PLAN_ERROR)
    execution_by_end = {bar.bar_end: bar for bar in bars}
    if any(
        bar.as_kwargs() != execution_by_end[bar.bar_end].as_kwargs()
        for segment in strategy_replay_segments
        for bar in segment.bars
        if bar.observation_eligible
    ):
        raise ValueError(_PLAN_ERROR)
    available_since = min(bar.trading_day for bar in bars)
    available_through = max(bar.trading_day for bar in bars)
    if any(
        fold.train_since < available_since
        or fold.test_through > available_through
        for fold in folds
    ):
        raise ValueError(_PLAN_ERROR)
    evaluated: list[WalkForwardFoldResult] = []
    formula_versions: tuple[str, ...] | None = None
    equity = Decimal("1")
    closed_trade_count = 0
    for fold in folds:
        training = tuple(
            bar
            for bar in bars
            if fold.train_since <= bar.trading_day <= fold.train_through
        )
        warmup = tuple(
            bar
            for bar in bars
            if fold.train_since <= bar.trading_day < fold.test_since
        )
        test = tuple(
            bar
            for bar in bars
            if fold.test_since <= bar.trading_day <= fold.test_through
        )
        if not training or not test:
            raise ValueError(_PLAN_ERROR)
        fold_bars = tuple(
            bar
            for bar in bars
            if fold.train_since <= bar.trading_day <= fold.test_through
        )
        replay_segments = tuple(
            NewowStrategyReplaySegment(
                tuple(
                    bar
                    for bar in segment.bars
                    if bar.trading_day <= fold.test_through
                    and (
                        not bar.observation_eligible
                        or bar.trading_day >= fold.train_since
                    )
                )
            )
            for segment in strategy_replay_segments
            if any(
                bar.observation_eligible
                and fold.train_since <= bar.trading_day <= fold.test_through
                for bar in segment.bars
            )
        )
        intents, versions = build_strategy_intents_from_replay_segments(
            replay_segments,
            strategy,
            flat_from=fold.test_since,
        )
        bar_by_end = {bar.bar_end: bar for bar in fold_bars}
        test_intents = tuple(
            intent
            for intent in intents
            if fold.test_since
            <= bar_by_end[intent.signal_bar_end].trading_day
            <= fold.test_through
        )
        backtest = run_causal_long_only_backtest(
            fold_bars,
            test_intents,
            cost_snapshots=cost_snapshots,
            execution_constraints=execution_constraints,
            require_execution_facts=True,
            strategy=strategy,
            signal_formula_versions=versions,
        )
        if formula_versions is None:
            formula_versions = versions
        elif formula_versions != versions:
            raise ValueError(_PLAN_ERROR)
        evaluated.append(
            WalkForwardFoldResult(
                fold=fold,
                train_bar_count=len(training),
                gap_bar_count=len(warmup) - len(training),
                warmup_bar_count=len(warmup),
                test_bar_count=len(test),
                segment_count=len(
                    {
                        (bar.physical_contract, bar.segment_id)
                        for bar in test
                    }
                ),
                physical_prefix_bar_count=sum(
                    len(segment.bars) for segment in replay_segments
                ),
                earliest_physical_prefix_trading_day=min(
                    bar.trading_day
                    for segment in replay_segments
                    for bar in segment.bars
                ),
                replay_segments=tuple(
                    WalkForwardReplaySegmentResult(
                        physical_contract=segment.bars[0].physical_contract,
                        segment_id=segment.bars[0].segment_id,
                        bar_count=len(segment.bars),
                        eligible_bar_count=sum(
                            bar.observation_eligible for bar in segment.bars
                        ),
                        earliest_trading_day=segment.bars[0].trading_day,
                        latest_trading_day=segment.bars[-1].trading_day,
                    )
                    for segment in replay_segments
                ),
                backtest=backtest,
            )
        )
        closed_trade_count += backtest.summary.closed_trade_count
        equity *= Decimal("1") + (
            backtest.summary.compounded_net_return_pct / Decimal("100")
        )
    assert formula_versions is not None
    return WalkForwardValidationResult(
        strategy=strategy,
        signal_formula_versions=formula_versions,
        folds=tuple(evaluated),
        closed_trade_count=closed_trade_count,
        compounded_net_return_pct=(equity - Decimal("1")) * Decimal("100"),
    )
