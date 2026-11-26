"""Display-only Tick facts crossing the Market read boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

from app.market_data.domain import BarFrequency, CanonicalBar


@dataclass(frozen=True, slots=True)
class MarketQuote:
    trading_day: date
    contract: str
    generation: str
    observed_at: datetime
    received_at: datetime
    last_price: Decimal
    bids: tuple[tuple[Decimal, Decimal], ...] = ()
    asks: tuple[tuple[Decimal, Decimal], ...] = ()
    stale: bool = False


@dataclass(frozen=True, slots=True)
class MarketActivity:
    contract: str
    generation: str
    bar: CanonicalBar
    observed_at: datetime
    received_at: datetime


@dataclass(frozen=True, slots=True)
class MarketPreview:
    quote: MarketQuote | None = None
    activity: MarketActivity | None = None


class MarketPreviewReader(Protocol):
    """Read one coherent preview without advancing completed data or a consumer cursor."""

    def snapshot(
        self, *, trading_day: date, symbol: str, contract: str, frequency: BarFrequency,
    ) -> MarketPreview: ...
