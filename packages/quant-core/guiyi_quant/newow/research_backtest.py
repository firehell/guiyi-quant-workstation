"""Causal, research-only evaluation for Newow page-parity signals.

This module has no persistence, scheduling, Runtime, notification, or order
surface.  A signal produced by a completed bar can only fill at the next bar's
open, and positions never cross an actual-dominant physical-contract segment.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from enum import StrEnum
import re
from typing import cast

from .main_rise import (
    MAIN_RISE_PAGE_V1,
    MainRiseAction,
    initial_main_rise_state,
    step_main_rise,
)
from .models import NewowDailyBar, NewowMarkerType
from .oscillation_channel import (
    CHANNEL_FORMULA_VERSION,
    OSCILLATION_FORMULA_VERSION,
    OscillationAction,
    OscillationState,
    step_oscillation,
)
from .profile import NEWOW_TREND_D1_PAGE_V2
from .trend_band import initial_trend_band_state, step_trend_band


CAUSAL_BACKTEST_FORMULA_VERSION = "newow_causal_next_open_costed_v1"
FORMAL_FREQUENCIES = ("1m", "5m", "15m", "30m", "60m", "1d", "1w")
CAUSAL_SIGNAL_FORMULAS = frozenset(
    {
        NEWOW_TREND_D1_PAGE_V2.trend_band_formula,
        OSCILLATION_FORMULA_VERSION,
        MAIN_RISE_PAGE_V1.band_formula,
    }
)
_PHYSICAL_CONTRACT = re.compile(r"([A-Z]+)[0-9]{3,4}\Z")


class ResearchStrategy(StrEnum):
    TREND = "trend"
    OSCILLATION = "oscillation"
    MAIN_RISE = "main_rise"


def _contract_matches_product(product: str, contract: str) -> bool:
    match = _PHYSICAL_CONTRACT.fullmatch(contract)
    return (
        match is not None
        and match.group(1) == product.upper()
        and 1 <= int(contract[-2:]) <= 12
    )


def _formula_versions_for_strategy(
    strategy: ResearchStrategy,
) -> tuple[str, ...]:
    if strategy is ResearchStrategy.TREND:
        return (NEWOW_TREND_D1_PAGE_V2.trend_band_formula,)
    if strategy is ResearchStrategy.OSCILLATION:
        return (OSCILLATION_FORMULA_VERSION, CHANNEL_FORMULA_VERSION)
    return (
        MAIN_RISE_PAGE_V1.band_formula,
        MAIN_RISE_PAGE_V1.j_reduce_formula,
        MAIN_RISE_PAGE_V1.escape_formula,
        MAIN_RISE_PAGE_V1.buy_formula,
        MAIN_RISE_PAGE_V1.magic11_formula,
    )


_INTENT_STRATEGY_BY_FORMULA = {
    NEWOW_TREND_D1_PAGE_V2.trend_band_formula: ResearchStrategy.TREND,
    OSCILLATION_FORMULA_VERSION: ResearchStrategy.OSCILLATION,
    MAIN_RISE_PAGE_V1.band_formula: ResearchStrategy.MAIN_RISE,
}


class BacktestAction(StrEnum):
    BUILD = "BUILD"
    CLEAR = "CLEAR"


@dataclass(frozen=True, slots=True)
class NewowResearchBar:
    """Completed execution Bar or same-contract formula warm-up Bar."""

    product: str
    physical_contract: str
    segment_id: str
    trading_day: date
    bar_end: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    open_interest: int | None
    source_identity: str
    observation_eligible: bool
    completed: bool
    series_kind: str = "actual_dominant"
    frequency: str = "1d"
    turnover: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.completed:
            raise ValueError("NEWOW_RESEARCH_BAR_NOT_COMPLETED")
        if self.series_kind not in {"actual_dominant", "contract"} or (
            self.observation_eligible and self.series_kind != "actual_dominant"
        ):
            raise ValueError("NEWOW_RESEARCH_BAR_INVALID_SERIES_KIND")
        if self.frequency not in FORMAL_FREQUENCIES:
            raise ValueError("NEWOW_RESEARCH_BAR_INVALID_FREQUENCY")
        if not self.product or self.product != self.product.lower():
            raise ValueError("NEWOW_RESEARCH_BAR_INVALID_PRODUCT")
        if not _contract_matches_product(self.product, self.physical_contract):
            raise ValueError("NEWOW_RESEARCH_BAR_INVALID_PHYSICAL_CONTRACT")
        if not self.segment_id or not self.source_identity:
            raise ValueError("NEWOW_RESEARCH_BAR_EMPTY_IDENTITY")
        if self.bar_end.tzinfo is None or self.bar_end.utcoffset() is None:
            raise ValueError("NEWOW_RESEARCH_BAR_NAIVE_TIMESTAMP")
        prices = (self.open, self.high, self.low, self.close)
        if not all(isinstance(value, Decimal) for value in prices):
            raise ValueError("NEWOW_RESEARCH_BAR_PRICE_MUST_BE_DECIMAL")
        if not all(value.is_finite() and value > 0 for value in prices):
            raise ValueError("NEWOW_RESEARCH_BAR_INVALID_OHLC")
        if (
            self.low > self.high
            or not self.low <= self.open <= self.high
            or not self.low <= self.close <= self.high
        ):
            raise ValueError("NEWOW_RESEARCH_BAR_INVALID_OHLC")
        if self.volume < 0 or (
            self.open_interest is not None and self.open_interest < 0
        ):
            raise ValueError("NEWOW_RESEARCH_BAR_NEGATIVE_VOLUME_OR_OI")
        if self.turnover is not None and (
            not isinstance(self.turnover, Decimal)
            or not self.turnover.is_finite()
            or self.turnover < 0
        ):
            raise ValueError("NEWOW_RESEARCH_BAR_INVALID_TURNOVER")

    def as_kwargs(self) -> dict[str, object]:
        return {
            "product": self.product,
            "physical_contract": self.physical_contract,
            "segment_id": self.segment_id,
            "trading_day": self.trading_day,
            "bar_end": self.bar_end,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "open_interest": self.open_interest,
            "source_identity": self.source_identity,
            "observation_eligible": self.observation_eligible,
            "completed": self.completed,
            "series_kind": self.series_kind,
            "frequency": self.frequency,
            "turnover": self.turnover,
        }


@dataclass(frozen=True, slots=True)
class NewowStrategyReplaySegment:
    """One physical-contract prefix replay with rank-1 output eligibility."""

    bars: tuple[NewowResearchBar, ...]

    def __post_init__(self) -> None:
        try:
            validate_research_bars(self.bars)
        except ValueError:
            raise ValueError("NEWOW_STRATEGY_REPLAY_SEGMENT_INVALID") from None
        first = self.bars[0]
        if (
            any(
                (bar.physical_contract, bar.segment_id)
                != (first.physical_contract, first.segment_id)
                for bar in self.bars
            )
            or not any(bar.observation_eligible for bar in self.bars)
            or any(
                (bar.series_kind == "actual_dominant")
                != bar.observation_eligible
                for bar in self.bars
            )
        ):
            raise ValueError("NEWOW_STRATEGY_REPLAY_SEGMENT_INVALID")


@dataclass(frozen=True, slots=True)
class BacktestCosts:
    commission_rate: Decimal = Decimal("0")
    commission_per_contract: Decimal = Decimal("0")
    contract_multiplier: Decimal = Decimal("1")
    slippage_bps: Decimal = Decimal("0")
    price_tick: Decimal | None = None
    slippage_ticks: int = 0

    def __post_init__(self) -> None:
        decimals = (
            self.commission_rate,
            self.commission_per_contract,
            self.contract_multiplier,
            self.slippage_bps,
        )
        if not all(
            isinstance(value, Decimal) and value.is_finite() for value in decimals
        ):
            raise ValueError("NEWOW_BACKTEST_COST_INVALID")
        if not Decimal("0") <= self.commission_rate < Decimal("1"):
            raise ValueError("NEWOW_BACKTEST_COMMISSION_INVALID")
        if self.commission_per_contract < 0 or self.contract_multiplier <= 0:
            raise ValueError("NEWOW_BACKTEST_CONTRACT_COST_INVALID")
        if not Decimal("0") <= self.slippage_bps < Decimal("10000"):
            raise ValueError("NEWOW_BACKTEST_SLIPPAGE_INVALID")
        if self.price_tick is not None and (
            not isinstance(self.price_tick, Decimal)
            or not self.price_tick.is_finite()
            or self.price_tick <= 0
        ):
            raise ValueError("NEWOW_BACKTEST_PRICE_TICK_INVALID")
        if type(self.slippage_ticks) is not int or self.slippage_ticks < 0:
            raise ValueError("NEWOW_BACKTEST_SLIPPAGE_TICKS_INVALID")
        if self.slippage_ticks and self.price_tick is None:
            raise ValueError("NEWOW_BACKTEST_PRICE_TICK_REQUIRED")


@dataclass(frozen=True, slots=True)
class BacktestCostSnapshot:
    product: str
    physical_contract: str
    effective_from: date
    effective_to: date
    captured_at: datetime
    source_identity: str
    costs: BacktestCosts

    def __post_init__(self) -> None:
        if (
            not self.product
            or self.product != self.product.lower()
            or not _contract_matches_product(self.product, self.physical_contract)
            or type(self.effective_from) is not date
            or type(self.effective_to) is not date
            or self.effective_from >= self.effective_to
            or not isinstance(self.captured_at, datetime)
            or self.captured_at.tzinfo is None
            or self.captured_at.utcoffset() is None
            or not self.source_identity
            or not isinstance(self.costs, BacktestCosts)
        ):
            raise ValueError("NEWOW_BACKTEST_COST_SNAPSHOT_INVALID")


@dataclass(frozen=True, slots=True)
class BacktestExecutionConstraint:
    bar_source_identity: str
    physical_contract: str
    limit_up: Decimal
    limit_down: Decimal
    captured_at: datetime
    source_identity: str

    def __post_init__(self) -> None:
        if (
            not self.bar_source_identity
            or not self.physical_contract
            or self.physical_contract != self.physical_contract.upper()
            or not isinstance(self.limit_up, Decimal)
            or not isinstance(self.limit_down, Decimal)
            or not self.limit_up.is_finite()
            or not self.limit_down.is_finite()
            or self.limit_down <= 0
            or self.limit_down >= self.limit_up
            or not isinstance(self.captured_at, datetime)
            or self.captured_at.tzinfo is None
            or self.captured_at.utcoffset() is None
            or not self.source_identity
        ):
            raise ValueError("NEWOW_BACKTEST_EXECUTION_CONSTRAINT_INVALID")


@dataclass(frozen=True, slots=True)
class BacktestIntent:
    action: BacktestAction
    signal_bar_end: datetime
    signal_formula_version: str


@dataclass(frozen=True, slots=True)
class BacktestFill:
    action: BacktestAction
    signal_bar_end: datetime
    fill_bar_end: datetime
    physical_contract: str
    raw_open: Decimal
    fill_price: Decimal
    fee: Decimal
    contract_multiplier: Decimal
    cost_source_identity: str | None
    signal_formula_version: str


@dataclass(frozen=True, slots=True)
class RejectedFill:
    action: BacktestAction
    signal_bar_end: datetime
    fill_bar_end: datetime
    physical_contract: str
    bar_source_identity: str
    constraint_source_identity: str
    reason: str


@dataclass(frozen=True, slots=True)
class BacktestTrade:
    entry: BacktestFill
    exit: BacktestFill
    gross_pnl_per_contract: Decimal
    net_pnl_per_contract: Decimal
    gross_return_pct: Decimal
    net_return_pct: Decimal
    holding_bars: int


@dataclass(frozen=True, slots=True)
class IncompletePosition:
    entry: BacktestFill
    last_bar_end: datetime
    reason: str


@dataclass(frozen=True, slots=True)
class BacktestSummary:
    closed_trade_count: int
    win_count: int
    loss_count: int
    breakeven_count: int
    compounded_net_return_pct: Decimal
    closed_trade_max_drawdown_pct: Decimal


@dataclass(frozen=True, slots=True)
class ResearchBacktestResult:
    frequency: str
    strategy: ResearchStrategy | None
    formula_version: str
    signal_formula_versions: tuple[str, ...]
    costs: BacktestCosts
    cost_snapshot_identities: tuple[str, ...]
    fills: tuple[BacktestFill, ...]
    rejected_fills: tuple[RejectedFill, ...]
    trades: tuple[BacktestTrade, ...]
    incomplete_positions: tuple[IncompletePosition, ...]
    cancelled_intent_count: int
    ignored_intent_count: int
    summary: BacktestSummary


def validate_research_bars(bars: tuple[NewowResearchBar, ...]) -> None:
    if not bars:
        raise ValueError("NEWOW_BACKTEST_BARS_EMPTY")
    first = bars[0]
    seen_sources: set[str] = set()
    previous_end: datetime | None = None
    for bar in bars:
        if bar.product != first.product:
            raise ValueError("NEWOW_BACKTEST_MIXED_PRODUCT")
        if bar.frequency != first.frequency:
            raise ValueError("NEWOW_BACKTEST_MIXED_FREQUENCY")
        if previous_end is not None and bar.bar_end <= previous_end:
            raise ValueError("NEWOW_BACKTEST_BARS_NOT_STRICTLY_ORDERED")
        if bar.source_identity in seen_sources:
            raise ValueError("NEWOW_BACKTEST_DUPLICATE_SOURCE_IDENTITY")
        previous_end = bar.bar_end
        seen_sources.add(bar.source_identity)


def _fill(
    intent: BacktestIntent,
    bar: NewowResearchBar,
    costs: BacktestCosts,
    *,
    cost_source_identity: str | None,
    constraint: BacktestExecutionConstraint | None,
) -> BacktestFill:
    proportional_slip = bar.open * costs.slippage_bps / Decimal("10000")
    tick_slip = (costs.price_tick or Decimal("0")) * costs.slippage_ticks
    adverse_slip = proportional_slip + tick_slip
    price = (
        bar.open + adverse_slip
        if intent.action is BacktestAction.BUILD
        else bar.open - adverse_slip
    )
    if costs.price_tick is not None:
        rounding = (
            ROUND_CEILING if intent.action is BacktestAction.BUILD else ROUND_FLOOR
        )
        price = (price / costs.price_tick).to_integral_value(
            rounding=rounding
        ) * costs.price_tick
    if constraint is not None:
        price = (
            min(price, constraint.limit_up)
            if intent.action is BacktestAction.BUILD
            else max(price, constraint.limit_down)
        )
    if price <= 0:
        raise ValueError("NEWOW_BACKTEST_FILL_PRICE_NONPOSITIVE")
    fee = (
        price * costs.contract_multiplier * costs.commission_rate
        + costs.commission_per_contract
    )
    return BacktestFill(
        intent.action,
        intent.signal_bar_end,
        bar.bar_end,
        bar.physical_contract,
        bar.open,
        price,
        fee,
        costs.contract_multiplier,
        cost_source_identity,
        intent.signal_formula_version,
    )


def _validate_cost_snapshots(
    snapshots: tuple[BacktestCostSnapshot, ...],
) -> None:
    ordered = sorted(
        snapshots,
        key=lambda item: (
            item.product,
            item.physical_contract,
            item.effective_from,
            item.effective_to,
            item.source_identity,
        ),
    )
    for previous, current in zip(ordered, ordered[1:], strict=False):
        if (
            (previous.product, previous.physical_contract)
            == (current.product, current.physical_contract)
            and current.effective_from < previous.effective_to
        ):
            raise ValueError("NEWOW_BACKTEST_COST_SNAPSHOT_OVERLAP")


def _resolve_costs(
    bar: NewowResearchBar,
    *,
    default: BacktestCosts,
    snapshots: tuple[BacktestCostSnapshot, ...],
    required: bool,
) -> tuple[BacktestCosts, str | None]:
    matches = tuple(
        snapshot
        for snapshot in snapshots
        if snapshot.product == bar.product
        and snapshot.physical_contract == bar.physical_contract
        and snapshot.effective_from <= bar.trading_day < snapshot.effective_to
    )
    if len(matches) > 1:
        raise ValueError("NEWOW_BACKTEST_COST_SNAPSHOT_OVERLAP")
    if not matches:
        if required:
            raise ValueError("NEWOW_BACKTEST_COST_SNAPSHOT_MISSING")
        return default, None
    return matches[0].costs, matches[0].source_identity


def _index_execution_constraints(
    constraints: tuple[BacktestExecutionConstraint, ...],
) -> dict[str, BacktestExecutionConstraint]:
    result: dict[str, BacktestExecutionConstraint] = {}
    for constraint in constraints:
        if constraint.bar_source_identity in result:
            raise ValueError("NEWOW_BACKTEST_EXECUTION_CONSTRAINT_CONFLICT")
        result[constraint.bar_source_identity] = constraint
    return result


def _resolve_execution_constraint(
    bar: NewowResearchBar,
    *,
    constraints: Mapping[str, BacktestExecutionConstraint],
    required: bool,
) -> BacktestExecutionConstraint | None:
    constraint = constraints.get(bar.source_identity)
    if constraint is None:
        if required:
            raise ValueError("NEWOW_BACKTEST_EXECUTION_CONSTRAINT_MISSING")
        return None
    if (
        constraint.physical_contract != bar.physical_contract
        or bar.high > constraint.limit_up
        or bar.low < constraint.limit_down
    ):
        raise ValueError("NEWOW_BACKTEST_EXECUTION_CONSTRAINT_CONFLICT")
    return constraint


def _validate_strict_bar_cost_facts(
    bar: NewowResearchBar,
    costs: BacktestCosts,
) -> None:
    tick = costs.price_tick
    if tick is None:
        raise ValueError("NEWOW_BACKTEST_PRICE_TICK_REQUIRED")
    if any(price % tick != 0 for price in (bar.open, bar.high, bar.low, bar.close)):
        raise ValueError("NEWOW_BACKTEST_BAR_PRICE_TICK_MISMATCH")


def _resolve_strict_cost_facts(
    bars: tuple[NewowResearchBar, ...],
    *,
    costs: BacktestCosts = BacktestCosts(),
    cost_snapshots: tuple[BacktestCostSnapshot, ...],
) -> dict[str, tuple[BacktestCosts, str | None]]:
    """Resolve and validate sourced cost facts for every causal input bar."""

    _validate_cost_snapshots(cost_snapshots)
    strict_costs_by_bar: dict[str, tuple[BacktestCosts, str | None]] = {}
    for bar in bars:
        resolved_costs = _resolve_costs(
            bar,
            default=costs,
            snapshots=cost_snapshots,
            required=True,
        )
        _validate_strict_bar_cost_facts(bar, resolved_costs[0])
        strict_costs_by_bar[bar.source_identity] = resolved_costs
    return strict_costs_by_bar


def _validate_strict_execution_facts(
    costs: BacktestCosts,
    constraint: BacktestExecutionConstraint | None,
) -> None:
    tick = costs.price_tick
    if tick is None:
        raise ValueError("NEWOW_BACKTEST_PRICE_TICK_REQUIRED")
    if constraint is None:
        raise ValueError("NEWOW_BACKTEST_EXECUTION_CONSTRAINT_MISSING")
    if any(
        price % tick != 0
        for price in (constraint.limit_up, constraint.limit_down)
    ):
        raise ValueError("NEWOW_BACKTEST_EXECUTION_CONSTRAINT_TICK_MISMATCH")


def _rejected_fill(
    intent: BacktestIntent,
    bar: NewowResearchBar,
    constraint: BacktestExecutionConstraint | None,
) -> RejectedFill | None:
    if constraint is None:
        return None
    reason: str | None = None
    if bar.volume == 0:
        reason = "ZERO_VOLUME"
    elif (
        intent.action is BacktestAction.BUILD
        and bar.open >= constraint.limit_up
    ):
        reason = "BUY_AT_LIMIT_UP"
    elif (
        intent.action is BacktestAction.CLEAR
        and bar.open <= constraint.limit_down
    ):
        reason = "SELL_AT_LIMIT_DOWN"
    if reason is None:
        return None
    return RejectedFill(
        intent.action,
        intent.signal_bar_end,
        bar.bar_end,
        bar.physical_contract,
        bar.source_identity,
        constraint.source_identity,
        reason,
    )


def _summary(trades: tuple[BacktestTrade, ...]) -> BacktestSummary:
    equity = Decimal("1")
    peak = equity
    max_drawdown = Decimal("0")
    wins = 0
    losses = 0
    breakevens = 0
    for trade in trades:
        equity *= Decimal("1") + trade.net_return_pct / Decimal("100")
        peak = max(peak, equity)
        drawdown = (
            Decimal("0") if peak == 0 else (peak - equity) / peak * Decimal("100")
        )
        max_drawdown = max(max_drawdown, drawdown)
        wins += int(trade.net_pnl_per_contract > 0)
        losses += int(trade.net_pnl_per_contract < 0)
        breakevens += int(trade.net_pnl_per_contract == 0)
    return BacktestSummary(
        len(trades),
        wins,
        losses,
        breakevens,
        (equity - Decimal("1")) * Decimal("100"),
        max_drawdown,
    )


def run_causal_long_only_backtest(
    bars: tuple[NewowResearchBar, ...],
    intents: tuple[BacktestIntent, ...],
    *,
    costs: BacktestCosts = BacktestCosts(),
    cost_snapshots: tuple[BacktestCostSnapshot, ...] = (),
    execution_constraints: tuple[BacktestExecutionConstraint, ...] = (),
    require_execution_facts: bool = False,
    strategy: ResearchStrategy | None = None,
    signal_formula_versions: tuple[str, ...] = (),
) -> ResearchBacktestResult:
    """Evaluate immutable completed-bar intents without same-bar execution."""

    validate_research_bars(bars)
    if any(bar.series_kind != "actual_dominant" for bar in bars):
        raise ValueError("NEWOW_BACKTEST_EXECUTION_SERIES_NOT_ACTUAL_DOMINANT")
    if strategy is not None and not isinstance(strategy, ResearchStrategy):
        raise ValueError("NEWOW_BACKTEST_STRATEGY_NOT_CAUSAL")

    by_end = {bar.bar_end: bar for bar in bars}
    intents_by_end: dict[datetime, list[BacktestIntent]] = {}
    intent_strategies: set[ResearchStrategy] = set()
    for intent in intents:
        if (
            not isinstance(intent.action, BacktestAction)
            or intent.signal_bar_end not in by_end
            or not intent.signal_formula_version
        ):
            raise ValueError("NEWOW_BACKTEST_INTENT_INVALID")
        if intent.signal_formula_version not in CAUSAL_SIGNAL_FORMULAS:
            raise ValueError("NEWOW_BACKTEST_SIGNAL_FORMULA_NOT_CAUSAL")
        intent_strategies.add(
            _INTENT_STRATEGY_BY_FORMULA[intent.signal_formula_version]
        )
        intents_by_end.setdefault(intent.signal_bar_end, []).append(intent)

    if strategy is None:
        if len(intent_strategies) > 1:
            raise ValueError("NEWOW_BACKTEST_STRATEGY_FORMULA_MISMATCH")
        if signal_formula_versions:
            matching_strategies = tuple(
                candidate
                for candidate in ResearchStrategy
                if signal_formula_versions
                == _formula_versions_for_strategy(candidate)
            )
            if len(matching_strategies) != 1:
                raise ValueError("NEWOW_BACKTEST_STRATEGY_FORMULA_MISMATCH")
            strategy = matching_strategies[0]
        elif intent_strategies:
            strategy = next(iter(intent_strategies))
            signal_formula_versions = _formula_versions_for_strategy(strategy)

    expected_formula_versions: tuple[str, ...] | None = None
    if strategy is not None:
        expected_formula_versions = _formula_versions_for_strategy(strategy)
        if (
            signal_formula_versions != expected_formula_versions
            or any(candidate is not strategy for candidate in intent_strategies)
        ):
            raise ValueError("NEWOW_BACKTEST_STRATEGY_FORMULA_MISMATCH")
    if type(require_execution_facts) is not bool:
        raise ValueError("NEWOW_BACKTEST_EXECUTION_CONSTRAINT_INVALID")
    constraints_by_bar = _index_execution_constraints(execution_constraints)
    sourced_costs_required = require_execution_facts or bool(cost_snapshots)
    constraints_required = require_execution_facts or bool(execution_constraints)
    strict_costs_by_bar: dict[str, tuple[BacktestCosts, str | None]] = {}
    if require_execution_facts:
        strict_costs_by_bar = _resolve_strict_cost_facts(
            bars,
            costs=costs,
            cost_snapshots=cost_snapshots,
        )
    else:
        _validate_cost_snapshots(cost_snapshots)
    fills: list[BacktestFill] = []
    rejected_fills: list[RejectedFill] = []
    trades: list[BacktestTrade] = []
    incomplete: list[IncompletePosition] = []
    pending: list[BacktestIntent] = []
    entry: BacktestFill | None = None
    entry_bar_index = -1
    cancelled = 0
    ignored = 0
    used_cost_sources: set[str] = set()
    previous: NewowResearchBar | None = None

    for index, bar in enumerate(bars):
        if previous is not None and (bar.physical_contract, bar.segment_id) != (
            previous.physical_contract,
            previous.segment_id,
        ):
            cancelled += len(pending)
            pending = []
            if entry is not None:
                incomplete.append(
                    IncompletePosition(
                        entry, previous.bar_end, "DOMINANT_ROLL_EXCLUDED"
                    )
                )
                entry = None
                entry_bar_index = -1

        if entry is not None and require_execution_facts:
            bar_costs, _ = strict_costs_by_bar[bar.source_identity]
            if bar_costs.contract_multiplier != entry.contract_multiplier:
                raise ValueError("NEWOW_BACKTEST_COST_SNAPSHOT_CONFLICT")

        if pending:
            for intent in pending:
                if require_execution_facts:
                    fill_costs, cost_source_identity = strict_costs_by_bar[
                        bar.source_identity
                    ]
                else:
                    fill_costs, cost_source_identity = _resolve_costs(
                        bar,
                        default=costs,
                        snapshots=cost_snapshots,
                        required=sourced_costs_required,
                    )
                constraint = _resolve_execution_constraint(
                    bar,
                    constraints=constraints_by_bar,
                    required=constraints_required,
                )
                if require_execution_facts:
                    _validate_strict_execution_facts(fill_costs, constraint)
                rejected = _rejected_fill(intent, bar, constraint)
                if rejected is not None:
                    rejected_fills.append(rejected)
                    continue
                fill = _fill(
                    intent,
                    bar,
                    fill_costs,
                    cost_source_identity=cost_source_identity,
                    constraint=constraint,
                )
                if cost_source_identity is not None:
                    used_cost_sources.add(cost_source_identity)
                if intent.action is BacktestAction.BUILD:
                    if entry is not None:
                        ignored += 1
                        continue
                    entry = fill
                    entry_bar_index = index
                    fills.append(fill)
                    continue
                if entry is None:
                    ignored += 1
                    continue
                if fill.contract_multiplier != entry.contract_multiplier:
                    raise ValueError("NEWOW_BACKTEST_COST_SNAPSHOT_CONFLICT")
                fills.append(fill)
                gross_pnl = (
                    fill.fill_price - entry.fill_price
                ) * entry.contract_multiplier
                entry_total = (
                    entry.fill_price * entry.contract_multiplier + entry.fee
                )
                net_pnl = (
                    fill.fill_price * entry.contract_multiplier - fill.fee
                ) - entry_total
                trades.append(
                    BacktestTrade(
                        entry,
                        fill,
                        gross_pnl,
                        net_pnl,
                        gross_pnl
                        / (entry.fill_price * entry.contract_multiplier)
                        * Decimal("100"),
                        net_pnl / entry_total * Decimal("100"),
                        index - entry_bar_index,
                    )
                )
                entry = None
                entry_bar_index = -1
            pending = []

        pending.extend(intents_by_end.get(bar.bar_end, ()))
        previous = bar

    cancelled += len(pending)
    if entry is not None:
        incomplete.append(
            IncompletePosition(entry, bars[-1].bar_end, "END_OF_SAMPLE_EXCLUDED")
        )
    frozen_trades = tuple(trades)
    return ResearchBacktestResult(
        frequency=bars[0].frequency,
        strategy=strategy,
        formula_version=CAUSAL_BACKTEST_FORMULA_VERSION,
        signal_formula_versions=signal_formula_versions,
        costs=costs,
        cost_snapshot_identities=tuple(sorted(used_cost_sources)),
        fills=tuple(fills),
        rejected_fills=tuple(rejected_fills),
        trades=frozen_trades,
        incomplete_positions=tuple(incomplete),
        cancelled_intent_count=cancelled,
        ignored_intent_count=ignored,
        summary=_summary(frozen_trades),
    )


def build_strategy_intents(
    bars: tuple[NewowResearchBar, ...],
    strategy: ResearchStrategy,
    *,
    flat_from: date | None = None,
) -> tuple[tuple[BacktestIntent, ...], tuple[str, ...]]:
    if not isinstance(strategy, ResearchStrategy):
        raise ValueError("NEWOW_BACKTEST_STRATEGY_NOT_CAUSAL")
    if flat_from is not None and type(flat_from) is not date:
        raise ValueError("NEWOW_BACKTEST_FLAT_FROM_INVALID")
    intents: list[BacktestIntent] = []
    if strategy is ResearchStrategy.TREND:
        trend_state = initial_trend_band_state()
        for bar in bars:
            trend_result = step_trend_band(
                trend_state,
                cast(NewowDailyBar, bar),
                profile=NEWOW_TREND_D1_PAGE_V2,
            )
            trend_state = trend_result.state
            if trend_result.marker is not None:
                action = (
                    BacktestAction.BUILD
                    if trend_result.marker.marker_type is NewowMarkerType.BUILD
                    else BacktestAction.CLEAR
                )
                intents.append(
                    BacktestIntent(
                        action, bar.bar_end, trend_result.marker.formula_version
                    )
                )
        return tuple(intents), _formula_versions_for_strategy(strategy)

    if strategy is ResearchStrategy.OSCILLATION:
        oscillation_state = OscillationState()
        flattened = flat_from is None
        for bar in bars:
            if not flattened:
                assert flat_from is not None
                if bar.trading_day >= flat_from and bar.observation_eligible:
                    oscillation_state = replace(oscillation_state, holding=False)
                    flattened = True
            oscillation_result = step_oscillation(
                oscillation_state, cast(NewowDailyBar, bar)
            )
            oscillation_state = oscillation_result.state
            for signal in oscillation_result.signals:
                action = (
                    BacktestAction.BUILD
                    if signal.action is OscillationAction.BUILD
                    else BacktestAction.CLEAR
                )
                intents.append(
                    BacktestIntent(action, bar.bar_end, signal.formula_version)
                )
        return tuple(intents), _formula_versions_for_strategy(strategy)

    main_rise_state = initial_main_rise_state()
    for bar in bars:
        main_rise_result = step_main_rise(main_rise_state, cast(NewowDailyBar, bar))
        main_rise_state = main_rise_result.state
        if main_rise_result.band_signal is not None:
            action = (
                BacktestAction.BUILD
                if main_rise_result.band_signal.action is MainRiseAction.BUILD
                else BacktestAction.CLEAR
            )
            intents.append(
                BacktestIntent(
                    action, bar.bar_end, main_rise_result.band_signal.formula_version
                )
            )
    return tuple(intents), _formula_versions_for_strategy(strategy)


def build_strategy_intents_from_replay_segments(
    segments: tuple[NewowStrategyReplaySegment, ...],
    strategy: ResearchStrategy,
    *,
    flat_from: date | None = None,
) -> tuple[tuple[BacktestIntent, ...], tuple[str, ...]]:
    """Replay each physical contract from fresh state, then merge eligible intents."""

    if not segments:
        raise ValueError("NEWOW_STRATEGY_REPLAY_SEGMENTS_EMPTY")
    intents: list[BacktestIntent] = []
    versions: tuple[str, ...] | None = None
    seen_signal_bars: set[datetime] = set()
    for segment in segments:
        if not isinstance(segment, NewowStrategyReplaySegment):
            raise ValueError("NEWOW_STRATEGY_REPLAY_SEGMENT_INVALID")
        segment_intents, segment_versions = build_strategy_intents(
            segment.bars,
            strategy,
            flat_from=flat_from,
        )
        if versions is None:
            versions = segment_versions
        elif versions != segment_versions:
            raise ValueError("NEWOW_STRATEGY_REPLAY_FORMULA_MISMATCH")
        eligible_ends = {
            bar.bar_end for bar in segment.bars if bar.observation_eligible
        }
        for intent in segment_intents:
            if (
                intent.signal_bar_end not in eligible_ends
                or intent.signal_bar_end in seen_signal_bars
            ):
                raise ValueError("NEWOW_STRATEGY_REPLAY_IDENTITY_CONFLICT")
            seen_signal_bars.add(intent.signal_bar_end)
            intents.append(intent)
    assert versions is not None
    intents.sort(key=lambda item: item.signal_bar_end)
    return tuple(intents), versions


def backtest_newow_strategy(
    bars: tuple[NewowResearchBar, ...],
    *,
    strategy: ResearchStrategy,
    costs: BacktestCosts = BacktestCosts(),
) -> ResearchBacktestResult:
    if not isinstance(strategy, ResearchStrategy):
        raise ValueError("NEWOW_BACKTEST_STRATEGY_NOT_CAUSAL")
    validate_research_bars(bars)
    intents, versions = build_strategy_intents(bars, strategy)
    return run_causal_long_only_backtest(
        bars,
        intents,
        costs=costs,
        strategy=strategy,
        signal_formula_versions=versions,
    )


def evaluate_newow_timeframes(
    series: Mapping[str, tuple[NewowResearchBar, ...]],
    *,
    strategy: ResearchStrategy,
    costs: BacktestCosts = BacktestCosts(),
) -> dict[str, ResearchBacktestResult]:
    results: dict[str, ResearchBacktestResult] = {}
    for frequency, bars in series.items():
        if (
            frequency not in FORMAL_FREQUENCIES
            or not bars
            or any(bar.frequency != frequency for bar in bars)
        ):
            raise ValueError("NEWOW_BACKTEST_TIMEFRAME_IDENTITY_INVALID")
        results[frequency] = backtest_newow_strategy(
            bars, strategy=strategy, costs=costs
        )
    return results
