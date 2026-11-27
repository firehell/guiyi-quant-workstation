"""Validated input values for the shared SuBing Paper model."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from guiyi_quant.paper import FeeSchedule


def _decimal(value: Decimal, name: str, *, positive: bool = False, nonnegative: bool = False) -> None:
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError(f'{name} must be a finite Decimal')
    if positive and value <= 0 or nonnegative and value < 0:
        raise ValueError(f'{name} out of range')


def _time(value: datetime, name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f'{name} must be timezone-aware')


@dataclass(frozen=True)
class StrategyBar:
    product: str
    physical_contract: str
    frequency: str
    bar_end: datetime
    trading_day: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    open_interest: Decimal | None
    source_identity: str
    confirmed_at: datetime
    observation_eligible: bool = True
    session_open_at: datetime | None = None
    session_close_at: datetime | None = None

    def __post_init__(self) -> None:
        if not all(type(x) is str and x.strip() for x in (self.product, self.physical_contract, self.frequency, self.source_identity)):
            raise ValueError('bar identity required')
        if self.frequency not in ('1m', '5m', '15m', '1d', '1w'):
            raise ValueError('unsupported research frequency')
        if type(self.trading_day) is not date or type(self.observation_eligible) is not bool:
            raise ValueError('invalid trading day or observation flag')
        _time(self.bar_end, 'bar_end')
        _time(self.confirmed_at, 'confirmed_at')
        if self.confirmed_at < self.bar_end:
            raise ValueError('confirmation before bar end')
        for name in ('session_open_at', 'session_close_at'):
            value = getattr(self, name)
            if value is not None:
                _time(value, name)
        for name in ('open', 'high', 'low', 'close'):
            _decimal(getattr(self, name), name, positive=True)
        _decimal(self.volume, 'volume', nonnegative=True)
        if self.open_interest is not None:
            _decimal(self.open_interest, 'open_interest', nonnegative=True)
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError('invalid OHLC range')
        if self.session_open_at is not None and self.session_open_at >= self.bar_end:
            raise ValueError('session open must precede bar end')
        if self.session_close_at is not None and self.session_close_at < self.bar_end:
            raise ValueError('session close before bar end')


@dataclass(frozen=True)
class ExecutionFacts:
    physical_contract: str
    trading_day: date
    tick_size: Decimal
    multiplier: Decimal
    prev_settlement: Decimal
    long_margin_ratio: Decimal
    short_margin_ratio: Decimal
    limit_up: Decimal
    limit_down: Decimal
    fees: FeeSchedule
    source_id: str

    def __post_init__(self) -> None:
        if not self.physical_contract or not self.source_id or type(self.trading_day) is not date:
            raise ValueError('execution fact identity required')
        for name in ('tick_size', 'multiplier', 'prev_settlement', 'long_margin_ratio',
                     'short_margin_ratio', 'limit_up', 'limit_down'):
            _decimal(getattr(self, name), name, positive=True)
        if self.limit_down >= self.limit_up or not self.limit_down < self.prev_settlement < self.limit_up:
            raise ValueError('invalid exchange limits')
        if type(self.fees) is not FeeSchedule:
            raise ValueError('FeeSchedule required')


@dataclass(frozen=True)
class ExecutionBar:
    bar: StrategyBar
    facts: ExecutionFacts

    def __post_init__(self) -> None:
        if self.bar.frequency != '1m' or self.bar.physical_contract != self.facts.physical_contract or self.bar.trading_day != self.facts.trading_day:
            raise ValueError('1m bar and physical execution facts must align')
