"""Anchored walk-forward evaluation for frozen Newow research formulas."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .research_backtest import (
    BacktestCostSnapshot,
    BacktestExecutionConstraint,
    NewowResearchBar,
    ResearchBacktestResult,
    ResearchStrategy,
    build_strategy_intents,
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
    warmup_bar_count: int
    test_bar_count: int
    backtest: ResearchBacktestResult


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
        intents, versions = build_strategy_intents(
            fold_bars,
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
                warmup_bar_count=len(warmup),
                test_bar_count=len(test),
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
