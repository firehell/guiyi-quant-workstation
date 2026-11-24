"""Frozen, single-contract day-session input for the RQAlpha P1 proof."""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from math import isfinite
from re import fullmatch
from zoneinfo import ZoneInfo

import numpy as np
from pandas import DatetimeIndex
from rqalpha.const import COMMISSION_TYPE, INSTRUMENT_TYPE, TRADING_CALENDAR_TYPE
from rqalpha.data.bar_dict_price_board import BarDictPriceBoard
from rqalpha.data.base_data_source.storages import FuturesTradingParameters
from rqalpha.interface import AbstractDataSource, AbstractMod
from rqalpha.model.instrument import Instrument

ASIA_SHANGHAI = ZoneInfo("Asia/Shanghai")
ONE_MINUTE = timedelta(minutes=1)


def local_naive(value: datetime) -> datetime:
    if value.utcoffset() is None:
        raise ValueError("TIMEZONE_REQUIRED")
    return value.astimezone(ASIA_SHANGHAI).replace(tzinfo=None)


def native_timestamp(value: datetime) -> int:
    return int(value.strftime("%Y%m%d%H%M%S"))


def valid_decimal(value, *, positive=False) -> bool:
    return (isinstance(value, Decimal) and value.is_finite()
            and isfinite(float(value))
            and (float(value) > 0 if positive else value >= 0))


@dataclass(frozen=True, slots=True)
class Session:
    day: date
    start: datetime
    end: datetime

    def __post_init__(self):
        start, end = local_naive(self.start), local_naive(self.end)
        day_session = (start.date() == end.date() == self.day
                       and time(8, 30) <= start.time() < end.time() <= time(15))
        night_session = (start.date() < self.day and start.time() >= time(20)
                         and start < end <= datetime.combine(start.date() + timedelta(days=1), time(3))
                         and end.date() <= self.day)
        if not (day_session or night_session) or any(dt.second or dt.microsecond for dt in (start, end)):
            raise ValueError("INVALID_DAY_SESSION")

    def minute_ends(self):
        current = self.start + ONE_MINUTE
        while current <= self.end:
            yield current
            current += ONE_MINUTE


@dataclass(frozen=True, slots=True)
class Minute:
    day: date
    end: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    def __post_init__(self):
        if (not all(valid_decimal(value, positive=True) for value in (self.open, self.high, self.low, self.close))
                or not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high
                or not valid_decimal(self.volume) or self.volume != self.volume.to_integral_value()):
            raise ValueError("INVALID_FROZEN_MINUTE")


@dataclass(frozen=True, slots=True)
class DailyFacts:
    day: date
    prev_settlement: Decimal
    settlement: Decimal
    limit_down: Decimal
    limit_up: Decimal
    fee_type: str
    open_fee: Decimal
    close_fee: Decimal
    close_today_fee: Decimal
    long_margin: Decimal
    short_margin: Decimal

    def __post_init__(self):
        if (not all(valid_decimal(value, positive=True) for value in
                    (self.prev_settlement, self.settlement, self.limit_down, self.limit_up,
                     self.long_margin, self.short_margin))
                or not self.limit_down < self.limit_up
                or not self.limit_down <= self.settlement <= self.limit_up
                or self.long_margin > 1 or self.short_margin > 1
                or self.fee_type not in ("by_money", "by_volume")
                or not all(valid_decimal(value) for value in (self.open_fee, self.close_fee, self.close_today_fee))):
            raise ValueError("INVALID_DAILY_FACTS")


@dataclass(frozen=True, slots=True)
class FrozenMarket:
    contract: str
    exchange: str
    window_start: date
    window_end: date
    tick: Decimal
    multiplier: int
    sessions: tuple[Session, ...]
    minutes: tuple[Minute, ...]
    daily: tuple[DailyFacts, ...]
    listed_date: date | None = None
    expired_date: date | None = None

    def __post_init__(self):
        if (not fullmatch(r"[A-Z]+[0-9]{3,4}", self.contract)
                or not 1 <= int(self.contract[-2:]) <= 12
                or Instrument.is_future_continuous_contract(self.contract)
                or self.exchange not in {"SHFE", "DCE", "CZCE", "CFFEX", "INE", "GFEX"}
                or not valid_decimal(self.tick, positive=True)
                or type(self.multiplier) is not int or self.multiplier <= 0):
            raise ValueError("INVALID_PHYSICAL_CONTRACT")
        if not self.sessions or any(
            a.end >= b.start or a.day > b.day for a, b in zip(self.sessions, self.sessions[1:])
        ):
            raise ValueError("INVALID_SESSION_ORDER")
        days = tuple(dict.fromkeys(session.day for session in self.sessions))
        if not self.window_start <= days[0] <= days[-1] <= self.window_end:
            raise ValueError("CONTRACT_WINDOW_MISMATCH")
        if (self.listed_date is None) != (self.expired_date is None):
            raise ValueError("CONTRACT_LIFECYCLE_MISSING")
        if self.listed_date is not None and not self.listed_date <= days[0] <= days[-1] < self.expired_date:
            raise ValueError("CONTRACT_LIFECYCLE_MISMATCH")
        if tuple(facts.day for facts in self.daily) != days:
            raise ValueError("DAILY_FACTS_MISSING")
        if any(old.settlement != new.prev_settlement for old, new in zip(self.daily, self.daily[1:])):
            raise ValueError("PREVIOUS_SETTLEMENT_MISMATCH")
        expected = tuple((session.day, end) for session in self.sessions for end in session.minute_ends())
        actual = tuple((row.day, row.end) for row in self.minutes)
        if any(row.end.utcoffset() is None for row in self.minutes) or expected != actual:
            raise ValueError("M1_COVERAGE_MISMATCH")
        facts_by_day = {facts.day: facts for facts in self.daily}
        for bar in self.minutes:
            facts = facts_by_day[bar.day]
            if (not facts.limit_down <= bar.low <= bar.high <= facts.limit_up
                    or any(value % self.tick for value in (bar.open, bar.high, bar.low, bar.close))):
                raise ValueError("FROZEN_MINUTE_PRICE_OUT_OF_RANGE")


class FrozenDataSource(AbstractDataSource):
    """Only the endpoints needed by the native futures backtest are available."""

    def __init__(self, market: FrozenMarket):
        self.market = market
        self.days = {facts.day: facts for facts in market.daily}
        self.bars = {local_naive(row.end): row for row in market.minutes}
        self.minute_times = {day: [] for day in self.days}
        for dt, row in self.bars.items():
            self.minute_times[row.day].append(native_timestamp(dt))
        self.instrument = Instrument({
            "order_book_id": market.contract,
            "symbol": market.contract,
            "type": INSTRUMENT_TYPE.FUTURE,
            "exchange": market.exchange,
            "contract_multiplier": market.multiplier,
            "round_lot": 1,
            "listed_date": (market.listed_date or market.window_start).isoformat(),
            "de_listed_date": (market.expired_date or market.window_end).isoformat(),
        }, futures_tick_size_getter=lambda _: float(market.tick))

    def get_instruments(self, id_or_syms=None, types=None):
        instrument = self.instrument
        if id_or_syms is not None:
            return (instrument,) if instrument.order_book_id in id_or_syms else ()
        return (instrument,) if types is None or instrument.type in types else ()

    def get_trading_calendars(self):
        return {TRADING_CALENDAR_TYPE.CN_STOCK: DatetimeIndex(list(self.days))}

    def available_data_range(self, frequency):
        if frequency != "1m":
            raise ValueError("FROZEN_SOURCE_REQUIRES_1M")
        return next(iter(self.days)), next(reversed(self.days))

    def get_trading_minutes_for(self, instrument, trading_dt):
        self._check_contract(instrument)
        return self.minute_times[trading_dt.date()]

    def get_bar(self, instrument, dt, frequency):
        self._check_contract(instrument)
        if frequency != "1m" or dt not in self.bars:
            raise ValueError("UNAVAILABLE_FROZEN_BAR")
        bar = self.bars[dt]
        day = self.days[bar.day]
        return {"datetime": native_timestamp(dt), "open": float(bar.open), "high": float(bar.high),
                "low": float(bar.low), "close": float(bar.close), "volume": float(bar.volume),
                "limit_up": float(day.limit_up), "limit_down": float(day.limit_down),
                "prev_settlement": float(day.prev_settlement)}

    def get_settle_price(self, instrument, dt):
        self._check_contract(instrument)
        if dt.time() < time(15, 30):
            raise ValueError("SETTLEMENT_NOT_YET_AVAILABLE")
        return float(self.days[dt.date()].settlement)

    def history_bars(self, instrument, bar_count, frequency, fields, dt, **_):
        self._check_contract(instrument)
        if (bar_count, frequency, fields) != (1, "1d", "prev_settlement"):
            raise ValueError("UNAVAILABLE_FROZEN_HISTORY")
        return np.array([float(self.days[dt.date()].prev_settlement)])

    def get_futures_trading_parameters(self, instrument, dt):
        self._check_contract(instrument)
        day = self.days[dt.date() if isinstance(dt, datetime) else dt]
        return FuturesTradingParameters(
            close_commission_ratio=float(day.close_fee),
            close_commission_today_ratio=float(day.close_today_fee),
            commission_type=COMMISSION_TYPE[day.fee_type.upper()],
            open_commission_ratio=float(day.open_fee),
            long_margin_ratio=float(day.long_margin),
            short_margin_ratio=float(day.short_margin),
        )

    def _check_contract(self, instrument):
        if instrument is not self.instrument:
            raise ValueError("OUT_OF_SCOPE_CONTRACT")


class SignalPriceBoard(BarDictPriceBoard):
    """Freeze native submission checks at the last price known to the signal."""

    _submission = None

    @contextmanager
    def submitting(self, contract, price):
        self._submission = (contract, float(price))
        try:
            yield
        finally:
            self._submission = None

    def get_last_price(self, order_book_id):
        if self._submission is not None:
            contract, price = self._submission
            if order_book_id != contract:
                raise ValueError("OUT_OF_SCOPE_CONTRACT")
            return price
        return super().get_last_price(order_book_id)


class FrozenMarketMod(AbstractMod):
    def start_up(self, env, mod_config):
        env.set_data_source(FrozenDataSource(mod_config.market))
        env.set_price_board(SignalPriceBoard())

    def tear_down(self, code, exception=None):
        return None


def load_mod():
    return FrozenMarketMod()
