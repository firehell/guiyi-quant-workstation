"""Causal, research-only evaluation for Newow page-parity signals.

This module has no persistence, scheduling, Runtime, notification, or order
surface.  A signal produced by a completed bar can only fill at the next bar's
open, and positions never cross an actual-dominant physical-contract segment.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from enum import StrEnum
from typing import cast

from .main_rise import (
    MAIN_RISE_PAGE_V1,
    MainRiseAction,
    initial_main_rise_state,
    step_main_rise,
)
from .models import NewowDailyBar, NewowMarkerType
from .oscillation_channel import (
    OSCILLATION_FORMULA_VERSION,
    OscillationAction,
    OscillationState,
    step_oscillation,
)
from .profile import NEWOW_TREND_D1_PAGE_V2
from .trend_band import initial_trend_band_state, step_trend_band


CAUSAL_BACKTEST_FORMULA_VERSION = "newow_causal_next_open_costed_v1"
FORMAL_FREQUENCIES = ("1m", "5m", "15m", "30m", "60m", "1d", "1w")


class ResearchStrategy(StrEnum):
    TREND = "trend"
    OSCILLATION = "oscillation"
    MAIN_RISE = "main_rise"


class BacktestAction(StrEnum):
    BUILD = "BUILD"
    CLEAR = "CLEAR"


@dataclass(frozen=True, slots=True)
class NewowResearchBar:
    """Completed actual-dominant bar supplied by the canonical application seam."""

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

    def __post_init__(self) -> None:
        if not self.completed:
            raise ValueError("NEWOW_RESEARCH_BAR_NOT_COMPLETED")
        if self.series_kind != "actual_dominant":
            raise ValueError("NEWOW_RESEARCH_BAR_INVALID_SERIES_KIND")
        if self.frequency not in FORMAL_FREQUENCIES:
            raise ValueError("NEWOW_RESEARCH_BAR_INVALID_FREQUENCY")
        if not self.product or self.product != self.product.lower():
            raise ValueError("NEWOW_RESEARCH_BAR_INVALID_PRODUCT")
        if (
            not self.physical_contract
            or self.physical_contract != self.physical_contract.upper()
        ):
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
        }


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
    signal_formula_version: str


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
    compounded_net_return_pct: Decimal
    closed_trade_max_drawdown_pct: Decimal


@dataclass(frozen=True, slots=True)
class ResearchBacktestResult:
    frequency: str
    strategy: ResearchStrategy | None
    formula_version: str
    signal_formula_versions: tuple[str, ...]
    costs: BacktestCosts
    fills: tuple[BacktestFill, ...]
    trades: tuple[BacktestTrade, ...]
    incomplete_positions: tuple[IncompletePosition, ...]
    cancelled_intent_count: int
    ignored_intent_count: int
    summary: BacktestSummary


def _validate_bars(bars: tuple[NewowResearchBar, ...]) -> None:
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
    intent: BacktestIntent, bar: NewowResearchBar, costs: BacktestCosts
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
        intent.signal_formula_version,
    )


def _summary(trades: tuple[BacktestTrade, ...]) -> BacktestSummary:
    equity = Decimal("1")
    peak = equity
    max_drawdown = Decimal("0")
    wins = 0
    for trade in trades:
        equity *= Decimal("1") + trade.net_return_pct / Decimal("100")
        peak = max(peak, equity)
        drawdown = (
            Decimal("0") if peak == 0 else (peak - equity) / peak * Decimal("100")
        )
        max_drawdown = max(max_drawdown, drawdown)
        wins += int(trade.net_pnl_per_contract > 0)
    return BacktestSummary(
        len(trades),
        wins,
        len(trades) - wins,
        (equity - Decimal("1")) * Decimal("100"),
        max_drawdown,
    )


def run_causal_long_only_backtest(
    bars: tuple[NewowResearchBar, ...],
    intents: tuple[BacktestIntent, ...],
    *,
    costs: BacktestCosts = BacktestCosts(),
    strategy: ResearchStrategy | None = None,
    signal_formula_versions: tuple[str, ...] = (),
) -> ResearchBacktestResult:
    """Evaluate immutable completed-bar intents without same-bar execution."""

    _validate_bars(bars)
    by_end = {bar.bar_end: bar for bar in bars}
    intents_by_end: dict[datetime, list[BacktestIntent]] = {}
    for intent in intents:
        if (
            not isinstance(intent.action, BacktestAction)
            or intent.signal_bar_end not in by_end
            or not intent.signal_formula_version
        ):
            raise ValueError("NEWOW_BACKTEST_INTENT_INVALID")
        intents_by_end.setdefault(intent.signal_bar_end, []).append(intent)

    fills: list[BacktestFill] = []
    trades: list[BacktestTrade] = []
    incomplete: list[IncompletePosition] = []
    pending: list[BacktestIntent] = []
    entry: BacktestFill | None = None
    entry_bar_index = -1
    cancelled = 0
    ignored = 0
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

        if pending:
            for intent in pending:
                fill = _fill(intent, bar, costs)
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
                fills.append(fill)
                gross_pnl = (
                    fill.fill_price - entry.fill_price
                ) * costs.contract_multiplier
                entry_total = entry.fill_price * costs.contract_multiplier + entry.fee
                net_pnl = (
                    fill.fill_price * costs.contract_multiplier - fill.fee
                ) - entry_total
                trades.append(
                    BacktestTrade(
                        entry,
                        fill,
                        gross_pnl,
                        net_pnl,
                        gross_pnl
                        / (entry.fill_price * costs.contract_multiplier)
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
        bars[0].frequency,
        strategy,
        CAUSAL_BACKTEST_FORMULA_VERSION,
        signal_formula_versions,
        costs,
        tuple(fills),
        frozen_trades,
        tuple(incomplete),
        cancelled,
        ignored,
        _summary(frozen_trades),
    )


def _strategy_intents(
    bars: tuple[NewowResearchBar, ...], strategy: ResearchStrategy
) -> tuple[tuple[BacktestIntent, ...], tuple[str, ...]]:
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
        return tuple(intents), (NEWOW_TREND_D1_PAGE_V2.trend_band_formula,)

    if strategy is ResearchStrategy.OSCILLATION:
        oscillation_state = OscillationState()
        for bar in bars:
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
        return tuple(intents), (OSCILLATION_FORMULA_VERSION,)

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
    versions = (
        MAIN_RISE_PAGE_V1.band_formula,
        MAIN_RISE_PAGE_V1.j_reduce_formula,
        MAIN_RISE_PAGE_V1.escape_formula,
        MAIN_RISE_PAGE_V1.buy_formula,
        MAIN_RISE_PAGE_V1.magic11_formula,
    )
    return tuple(intents), versions


def backtest_newow_strategy(
    bars: tuple[NewowResearchBar, ...],
    *,
    strategy: ResearchStrategy,
    costs: BacktestCosts = BacktestCosts(),
) -> ResearchBacktestResult:
    if not isinstance(strategy, ResearchStrategy):
        raise ValueError("NEWOW_BACKTEST_STRATEGY_NOT_CAUSAL")
    _validate_bars(bars)
    intents, versions = _strategy_intents(bars, strategy)
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
