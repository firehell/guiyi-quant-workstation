"""Page-exact target/absorb channels and explicitly bounded display selection."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from .research_backtest import NewowResearchBar, validate_research_bars


TARGET_ABSORB_CHANNEL_PAGE_V1 = "newow_target_absorb_hhv_llv10_page_v1"
TARGET_ABSORB_DISPLAY_PAGE_V1 = (
    "newow_target_absorb_display_selection_page_v1"
)


class DisplayPeriod(StrEnum):
    DAY = "day"
    WEEK = "week"
    BEST_AVAILABLE = "best_available"


class PageSignalState(StrEnum):
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    WAIT = "wait"


@dataclass(frozen=True, slots=True)
class PriceChannelPoint:
    bar_end: datetime
    target: Decimal | None
    absorb: Decimal | None
    window: int
    available: bool
    formula_version: str = TARGET_ABSORB_CHANNEL_PAGE_V1


@dataclass(frozen=True, slots=True)
class MultiPeriodPriceFacts:
    target_daily: Decimal | None
    target_weekly: Decimal | None
    absorb_daily: Decimal | None
    absorb_weekly: Decimal | None
    signal_daily: PageSignalState | None
    signal_weekly: PageSignalState | None
    cross_weekly_buy: bool
    fallback_target: Decimal | None = None
    fallback_high: Decimal | None = None
    fallback_absorb: Decimal | None = None

    def __post_init__(self) -> None:
        values = (
            self.target_daily,
            self.target_weekly,
            self.absorb_daily,
            self.absorb_weekly,
            self.fallback_target,
            self.fallback_high,
            self.fallback_absorb,
        )
        if any(
            value is not None
            and (
                not isinstance(value, Decimal)
                or not value.is_finite()
                or value <= 0
            )
            for value in values
        ):
            raise ValueError("NEWOW_DISPLAY_PRICE_FACTS_INCOMPLETE")
        if self.signal_daily is not None and not isinstance(
            self.signal_daily, PageSignalState
        ):
            raise ValueError("NEWOW_DISPLAY_PRICE_FACTS_INCOMPLETE")
        if self.signal_weekly is not None and not isinstance(
            self.signal_weekly, PageSignalState
        ):
            raise ValueError("NEWOW_DISPLAY_PRICE_FACTS_INCOMPLETE")
        if type(self.cross_weekly_buy) is not bool:
            raise ValueError("NEWOW_DISPLAY_PRICE_FACTS_INCOMPLETE")


@dataclass(frozen=True, slots=True)
class DisplayPriceSelection:
    target: Decimal | None
    absorb: Decimal | None
    raw_target: Decimal | None
    raw_absorb: Decimal | None
    target_period: DisplayPeriod | None
    absorb_period: DisplayPeriod | None
    target_branch_token: str
    absorb_branch_token: str
    formula_version: str = TARGET_ABSORB_DISPLAY_PAGE_V1


def _valid_window(window: object) -> bool:
    return type(window) is int and 5 <= window <= 120


def calculate_price_channel(
    bars: Sequence[NewowResearchBar], *, window: int
) -> tuple[PriceChannelPoint, ...]:
    """Calculate full-window HHV/LLV, including the current completed bar."""

    if not _valid_window(window):
        raise ValueError("NEWOW_PRICE_CHANNEL_INVALID_WINDOW")
    materialized = tuple(bars)
    validate_research_bars(materialized)
    series = {
        (bar.physical_contract, bar.segment_id) for bar in materialized
    }
    if len(series) != 1:
        raise ValueError("NEWOW_PRICE_CHANNEL_MIXED_SERIES")

    result: list[PriceChannelPoint] = []
    for index, bar in enumerate(materialized):
        if index + 1 < window:
            result.append(
                PriceChannelPoint(bar.bar_end, None, None, window, False)
            )
            continue
        sample = materialized[index + 1 - window : index + 1]
        result.append(
            PriceChannelPoint(
                bar.bar_end,
                max(item.high for item in sample),
                min(item.low for item in sample),
                window,
                True,
            )
        )
    return tuple(result)


def _guard_price(
    value: Decimal | None, previous_close: Decimal | None
) -> Decimal | None:
    if value is None or not value.is_finite() or value <= 0:
        return None
    guarded = value
    if previous_close is not None:
        guarded = min(
            max(value, previous_close / Decimal("2")),
            previous_close * Decimal("2"),
        )
    return guarded.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _positive(signal: PageSignalState) -> bool:
    return signal in {PageSignalState.BUY, PageSignalState.HOLD}


def _select_target(
    facts: MultiPeriodPriceFacts,
    *,
    view_period: DisplayPeriod,
    current_price: Decimal,
) -> tuple[Decimal | None, DisplayPeriod | None, str]:
    daily = facts.target_daily
    weekly = facts.target_weekly
    day_signal = facts.signal_daily or PageSignalState.WAIT
    week_signal = facts.signal_weekly or PageSignalState.WAIT
    day_positive = _positive(day_signal)
    week_positive = _positive(week_signal) or facts.cross_weekly_buy

    if daily is not None or weekly is not None:
        if day_positive and week_positive:
            if view_period is DisplayPeriod.WEEK and weekly is not None:
                return weekly, DisplayPeriod.WEEK, "WEEK_VIEW"
            if day_signal is PageSignalState.BUY and daily is not None:
                if weekly is not None and current_price >= daily:
                    return weekly, DisplayPeriod.WEEK, "DAILY_TARGET_BREAKOUT"
                return daily, DisplayPeriod.DAY, "DAILY_BUY"
            if week_signal is PageSignalState.BUY and weekly is not None:
                return weekly, DisplayPeriod.WEEK, "WEEKLY_BUY"
            if view_period is DisplayPeriod.DAY:
                if daily is not None:
                    return daily, DisplayPeriod.DAY, "BOTH_HOLD_DAY_VIEW"
                return weekly, DisplayPeriod.WEEK, "BOTH_HOLD_DAY_FALLBACK"
            if weekly is not None:
                token = (
                    "WEEKLY_CROSS"
                    if facts.cross_weekly_buy
                    else "BOTH_HOLD_BEST_AVAILABLE"
                )
                return weekly, DisplayPeriod.WEEK, token
            if (
                facts.fallback_target is not None
                and facts.fallback_target > (daily or Decimal("0"))
            ):
                return facts.fallback_target, None, "WEEKLY_GENERIC_FALLBACK"
            if daily is not None:
                return daily, DisplayPeriod.DAY, "BOTH_HOLD_DAILY_FALLBACK"
            return facts.fallback_target, None, "GENERIC_TARGET_FALLBACK"

        if day_positive and daily is not None:
            if weekly is not None and current_price >= daily:
                return weekly, DisplayPeriod.WEEK, "DAILY_TARGET_BREAKOUT"
            return daily, DisplayPeriod.DAY, "DAILY_POSITIVE"
        if week_positive and weekly is not None:
            token = "WEEKLY_CROSS" if facts.cross_weekly_buy else "WEEKLY_BUY"
            return weekly, DisplayPeriod.WEEK, token
        if daily is not None:
            return daily, DisplayPeriod.DAY, "BOTH_NEGATIVE_DAILY"
        if view_period is not DisplayPeriod.DAY and weekly is not None:
            return weekly, DisplayPeriod.WEEK, "WEEKLY_FALLBACK"
        return None, None, "NO_TARGET"

    if facts.fallback_high is not None and facts.fallback_high > current_price:
        return facts.fallback_high, None, "HIGH_FALLBACK"
    if facts.fallback_target is not None:
        return facts.fallback_target, None, "GENERIC_TARGET_FALLBACK"
    return None, None, "NO_TARGET"


def _select_absorb(
    facts: MultiPeriodPriceFacts, *, view_period: DisplayPeriod
) -> tuple[Decimal | None, DisplayPeriod | None, str]:
    daily = facts.absorb_daily
    weekly = facts.absorb_weekly
    day_signal = facts.signal_daily or PageSignalState.WAIT
    week_signal = facts.signal_weekly or PageSignalState.WAIT
    day_positive = _positive(day_signal)
    week_positive = _positive(week_signal)
    allow_week = view_period is not DisplayPeriod.DAY

    if day_positive and week_positive:
        if view_period is DisplayPeriod.WEEK and weekly is not None:
            return weekly, DisplayPeriod.WEEK, "WEEK_VIEW"
        if day_signal is PageSignalState.BUY and daily is not None:
            return daily, DisplayPeriod.DAY, "DAILY_BUY"
        if week_signal is PageSignalState.BUY and weekly is not None:
            return weekly, DisplayPeriod.WEEK, "WEEKLY_BUY"
        if daily is not None:
            return daily, DisplayPeriod.DAY, "BOTH_HOLD_DAILY"
        if allow_week and weekly is not None:
            return weekly, DisplayPeriod.WEEK, "BOTH_HOLD_WEEKLY_FALLBACK"
        return None, None, "NO_ABSORB"

    if day_positive:
        if daily is not None:
            return daily, DisplayPeriod.DAY, "DAILY_POSITIVE"
        if allow_week and weekly is not None:
            return weekly, DisplayPeriod.WEEK, "DAILY_POSITIVE_WEEK_FALLBACK"
        return None, None, "NO_ABSORB"

    if week_positive:
        if daily is not None:
            return daily, DisplayPeriod.DAY, "WEEKLY_POSITIVE_DAILY_ABSORB"
        if weekly is not None:
            return weekly, DisplayPeriod.WEEK, "WEEKLY_POSITIVE"
    else:
        if allow_week and weekly is not None:
            return weekly, DisplayPeriod.WEEK, "BOTH_NEGATIVE_WEEKLY"
        if daily is not None:
            return daily, DisplayPeriod.DAY, "BOTH_NEGATIVE_DAILY"
        return None, None, "NO_ABSORB"

    if facts.fallback_absorb is not None:
        return facts.fallback_absorb, None, "GENERIC_ABSORB_FALLBACK"
    return None, None, "NO_ABSORB"


def select_display_prices(
    facts: MultiPeriodPriceFacts,
    *,
    view_period: DisplayPeriod,
    current_price: Decimal,
    previous_close: Decimal | None,
) -> DisplayPriceSelection:
    """Select and guard page display values without returning page sentinel zeroes."""

    if not isinstance(facts, MultiPeriodPriceFacts) or not isinstance(
        view_period, DisplayPeriod
    ):
        raise ValueError("NEWOW_DISPLAY_PRICE_FACTS_INCOMPLETE")
    if (
        not isinstance(current_price, Decimal)
        or not current_price.is_finite()
        or current_price <= 0
        or (
            previous_close is not None
            and (
                not isinstance(previous_close, Decimal)
                or not previous_close.is_finite()
                or previous_close <= 0
            )
        )
    ):
        raise ValueError("NEWOW_DISPLAY_PRICE_FACTS_INCOMPLETE")

    raw_target, target_period, target_branch = _select_target(
        facts, view_period=view_period, current_price=current_price
    )
    raw_absorb, absorb_period, absorb_branch = _select_absorb(
        facts, view_period=view_period
    )
    return DisplayPriceSelection(
        target=_guard_price(raw_target, previous_close),
        absorb=_guard_price(raw_absorb, previous_close),
        raw_target=raw_target,
        raw_absorb=raw_absorb,
        target_period=target_period,
        absorb_period=absorb_period,
        target_branch_token=target_branch,
        absorb_branch_token=absorb_branch,
    )
