"""Resolve one current trading day from existing product market phases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Protocol

from app.market_data.market_phase import MarketPhase, ProductMarketPhase


class CurrentTradingDayStatus(StrEnum):
    READY = "ready"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class CurrentTradingDayResult:
    status: CurrentTradingDayStatus
    trading_day: date | None


class ProductPhaseResolver(Protocol):
    def resolve(self, symbol: str, now: datetime) -> ProductMarketPhase: ...


def resolve_current_trading_day(
    phase_resolver: ProductPhaseResolver,
    *,
    products: tuple[str, ...],
    now: datetime,
) -> CurrentTradingDayResult:
    """Return the unique active day, or the unique closed day as fallback."""

    phases = tuple(phase_resolver.resolve(product, now) for product in products)
    if any(item.phase is MarketPhase.UNKNOWN for item in phases):
        return CurrentTradingDayResult(CurrentTradingDayStatus.UNAVAILABLE, None)
    active_phases = tuple(
        item
        for item in phases
        if item.phase in {MarketPhase.TRADING, MarketPhase.BREAK}
    )
    active_days = {
        item.trading_day for item in active_phases if item.trading_day is not None
    }
    if active_phases:
        if any(item.trading_day is None for item in active_phases):
            return CurrentTradingDayResult(CurrentTradingDayStatus.UNAVAILABLE, None)
        return _unique_day_result(active_days)

    closed_days = {
        item.trading_day
        for item in phases
        if item.phase is MarketPhase.CLOSED and item.trading_day is not None
    }
    return _unique_day_result(closed_days)


def _unique_day_result(days: set[date]) -> CurrentTradingDayResult:
    if len(days) == 1:
        return CurrentTradingDayResult(CurrentTradingDayStatus.READY, days.pop())
    return CurrentTradingDayResult(CurrentTradingDayStatus.UNAVAILABLE, None)
