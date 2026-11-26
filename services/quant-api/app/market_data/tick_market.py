"""RQData Tick normalization and trading-session minute assembly."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from app.market_data.aggregation import SessionWindow, expected_intraday_ends
from app.market_data.domain import BarFrequency, CanonicalBar, sum_decimal_exact
from app.market_data.live_market import _raw_date, _raw_datetime

_MINUTE = timedelta(minutes=1)
_ZERO = Decimal(0)
Book = tuple[tuple[Decimal, Decimal], ...]


@dataclass(frozen=True, slots=True)
class MarketTick:
    contract: str
    trading_day: date
    observed_at: datetime
    received_at: datetime
    last: Decimal
    volume: Decimal
    turnover: Decimal | None
    open_interest: Decimal | None
    connection: int
    bid: Book = ()
    ask: Book = ()


def _number(value: Any) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite() or result < 0:
        raise ValueError("TICK_NUMBER_INVALID")
    # Match the magnitude bounds of the Canonical representation without
    # quantizing a cumulative counter before taking its difference.
    if result.adjusted() >= 20 or not -36 <= result.as_tuple().exponent <= 19:
        raise ValueError("TICK_NUMBER_INVALID")
    return result


def _optional_number(value: Any) -> Decimal | None:
    return None if value is None else _number(value)


def _book(prices: Any, volumes: Any) -> Book:
    if prices is None and volumes is None:
        return ()
    if (not isinstance(prices, (tuple, list)) or not isinstance(volumes, (tuple, list))
            or len(prices) != len(volumes) or len(prices) > 5):
        raise ValueError("TICK_BOOK_INVALID")
    levels = []
    for price, volume in zip(prices, volumes, strict=True):
        price, volume = _number(price), _number(volume)
        if price:
            levels.append((price, volume))
        elif volume:
            raise ValueError("TICK_BOOK_INVALID")
    return tuple(levels)


def _tick_datetime(value: Any) -> datetime:
    digits = str(value)
    if digits.isdigit():
        if not 14 <= len(digits) <= 20:
            raise ValueError("TICK_TIME_INVALID")
        return _raw_datetime(int(digits[:14])).replace(microsecond=int(digits[14:].ljust(6, "0")))
    return _raw_datetime(value)


def decode_rqdata_tick(
    payload: Mapping[str, Any], *, trading_day: date, received_at: datetime, connection: int,
) -> MarketTick | None:
    """The caller supplies the owner trading day from Calendar and Session."""
    contract = payload.get("order_book_id")
    if (payload.get("action") != "feed" or not isinstance(contract, str)
            or not contract or payload.get("channel") != f"tick_{contract}"):
        return None
    try:
        claimed_day = payload.get("trading_date")
        observed_at = _tick_datetime(payload["datetime"])
        last = _number(payload["last"])
        if (claimed_day is not None and _raw_date(claimed_day) != trading_day
                or received_at.utcoffset() is None or observed_at > received_at or last <= 0):
            return None
        return MarketTick(
            contract=contract.upper(), trading_day=trading_day,
            observed_at=observed_at, received_at=received_at, last=last,
            volume=_number(payload["volume"]),
            turnover=_optional_number(payload.get("total_turnover")),
            open_interest=_optional_number(payload.get("open_interest")),
            connection=connection,
            bid=_book(payload.get("bid"), payload.get("bid_vol")),
            ask=_book(payload.get("ask"), payload.get("ask_vol")),
        )
    except (KeyError, ArithmeticError, TypeError, ValueError):
        return None


def _difference(current: Decimal | None, previous: Decimal | None) -> Decimal | None:
    if current is None or previous is None:
        return None
    return sum_decimal_exact((current, previous.copy_negate()))


@dataclass(slots=True)
class _Minute:
    end: datetime
    volume_before: Decimal
    turnover_before: Decimal | None
    eligible: bool
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    close: Decimal | None = None

    def add(self, tick: MarketTick, *, traded: bool) -> None:
        if not traded:
            return
        self.open = tick.last if self.open is None else self.open
        self.high = tick.last if self.high is None else max(self.high, tick.last)
        self.low = tick.last if self.low is None else min(self.low, tick.last)
        self.close = tick.last

    def bar(self, latest: MarketTick) -> CanonicalBar:
        return CanonicalBar(
            bar_end=self.end, trading_day=latest.trading_day,
            open=self.open or latest.last, high=self.high or latest.last,
            low=self.low or latest.last, close=self.close or latest.last,
            volume=sum_decimal_exact((latest.volume, self.volume_before.copy_negate())),
            turnover=_difference(latest.turnover, self.turnover_before),
            open_interest=latest.open_interest,
        )


@dataclass(frozen=True, slots=True)
class TickMinuteUpdate:
    active: CanonicalBar | None = None
    completed: CanonicalBar | None = None
    issue: str | None = None
    accepted: bool = False


class TickMinuteBuilder:
    """One physical contract and trading day. A newer quote closes only a proved minute."""

    def __init__(self, sessions: tuple[SessionWindow, ...]) -> None:
        expected_intraday_ends(sessions, BarFrequency.M1)
        self.sessions = sessions
        self._latest: MarketTick | None = None
        self._minute: _Minute | None = None
        self._session_index: int | None = None
        self._finished_end: datetime | None = None

    def gap(self) -> None:
        """An unobserved transport interval invalidates an in-flight minute."""
        self._minute = None
        self._latest = None
        self._session_index = None

    def ingest(self, tick: MarketTick) -> TickMinuteUpdate:
        index = next((i for i, session in enumerate(self.sessions)
                      if session.start <= tick.observed_at <= session.end), None)
        if index is None:
            return TickMinuteUpdate(issue="TICK_OUTSIDE_SESSION")
        session = self.sessions[index]
        offset = (tick.observed_at - session.start) // _MINUTE
        end = min(session.start + (offset + 1) * _MINUTE, session.end)
        latest = self._latest
        if latest is not None and (latest.contract, latest.trading_day) != (tick.contract, tick.trading_day):
            raise ValueError("TICK_OWNER_CHANGED")
        if self._finished_end is not None and end <= self._finished_end:
            return TickMinuteUpdate(issue="TICK_LATE")
        if latest is not None and tick.observed_at < latest.observed_at:
            if self._minute is not None and end == self._minute.end:
                self._minute.eligible = False
            return TickMinuteUpdate(issue="TICK_LATE")
        continuous = latest is not None and latest.connection == tick.connection
        if continuous and tick.observed_at == latest.observed_at:
            if (tick.last, tick.volume, tick.turnover, tick.open_interest, tick.bid, tick.ask) == (
                latest.last, latest.volume, latest.turnover, latest.open_interest, latest.bid, latest.ask,
            ):
                return TickMinuteUpdate(issue="TICK_DUPLICATE")
            if self._minute is not None:
                self._minute.eligible = False
            return TickMinuteUpdate(issue="TICK_TIME_CONFLICT")

        new_session = index != self._session_index
        if continuous and (tick.volume < latest.volume or (
            tick.turnover is not None and latest.turnover is not None and tick.turnover < latest.turnover
        )):
            continuous = False
        current = self._minute if continuous and not new_session else None
        completed = None
        adjacent = (current is not None and end == current.end + _MINUTE
                    and tick.observed_at < end)
        if adjacent and current.eligible:
            completed = current.bar(latest)
            self._finished_end = current.end

        if current is None or current.end != end:
            first_open = index == 0 and latest is None and tick.observed_at == session.start
            proved_break = (
                continuous and new_session and self._session_index == index - 1
                and self._finished_end == self.sessions[index - 1].end
                and end == session.start + _MINUTE
            )
            covered = first_open or adjacent or proved_break
            volume_before = _ZERO if first_open else latest.volume if covered else tick.volume
            turnover_before = _ZERO if first_open else latest.turnover if covered else tick.turnover
            current = _Minute(end, volume_before, turnover_before, covered)

        traded = tick.volume > (latest.volume if continuous else current.volume_before)
        if continuous and not traded and tick.last != latest.last:
            current.eligible = False
        current.add(tick, traded=traded)
        self._latest = tick
        self._session_index = index
        self._minute = current

        # A real tick at the exact Session endpoint can confirm its own minute.
        # Reaching the end on the wall clock never manufactures a source event.
        if tick.observed_at == session.end:
            if current.eligible:
                completed = current.bar(tick)
                self._finished_end = current.end
            self._minute = None
        active = None if self._minute is None else current.bar(tick)
        issue = None if current.eligible else "TICK_MINUTE_UNPROVED"
        return TickMinuteUpdate(active=active, completed=completed, issue=issue, accepted=True)
