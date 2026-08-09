"""由历史交易日历与 Session 事实解析市场观察阶段。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.market_data.aggregation import SessionWindow
from app.market_data.session_clock import (
    SHANGHAI,
    ResolvedSessionWindow,
    SessionClockError,
    resolved_session_windows_for_trading_day,
)
from app.models import Instrument, TradingCalendar


class MarketPhase(StrEnum):
    TRADING = "TRADING"
    BREAK = "BREAK"
    CLOSED = "CLOSED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ProductMarketPhase:
    symbol: str
    phase: MarketPhase
    trading_day: date | None
    current_session: SessionWindow | None
    next_session_start: datetime | None


class MarketPhaseResolver:
    """只使用 TradingCalendar 与 TradingSession 已有事实的阶段解析器。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def resolve(self, symbol: str, now: datetime) -> ProductMarketPhase:
        normalized = symbol.strip().lower()
        if now.tzinfo is None or now.utcoffset() is None:
            return self._unknown(normalized)
        local_now = now.astimezone(SHANGHAI)
        exchange = self._session.scalar(
            select(Instrument.exchange_code).where(
                Instrument.symbol == normalized,
                Instrument.is_active.is_(True),
            )
        )
        if exchange is None:
            return self._unknown(normalized)

        calendar_rows = self._nearby_calendar_rows(exchange, local_now.date())
        if calendar_rows is None:
            return self._unknown(normalized)
        current_calendar = calendar_rows.get(local_now.date())
        if current_calendar is None:
            return self._unknown(normalized)

        resolved: list[tuple[date, ResolvedSessionWindow]] = []
        has_missing_session = False
        for trading_day, calendar in calendar_rows.items():
            if not calendar.is_trading_day:
                continue
            try:
                windows = resolved_session_windows_for_trading_day(
                    self._session,
                    exchange=exchange,
                    symbol=normalized,
                    trading_day=trading_day,
                )
            except SessionClockError:
                has_missing_session = True
                continue
            resolved.extend(
                (trading_day, item)
                for item in windows
                if not item.is_night or calendar.has_night_session
            )

        if has_missing_session:
            return self._unknown(normalized)
        resolved.sort(key=lambda item: item[1].window.start)
        for trading_day, item in resolved:
            window = item.window
            if window.start <= local_now < window.end:
                return ProductMarketPhase(
                    normalized,
                    MarketPhase.TRADING,
                    trading_day,
                    window,
                    self._next_session_start(resolved, local_now),
                )

        for trading_day in tuple(dict.fromkeys(day for day, _ in resolved)):
            day_windows = tuple(
                item.window
                for candidate_day, item in resolved
                if candidate_day == trading_day and not item.is_night
            )
            for previous, following in zip(day_windows, day_windows[1:]):
                if previous.end <= local_now < following.start:
                    return ProductMarketPhase(
                        normalized,
                        MarketPhase.BREAK,
                        trading_day,
                        None,
                        following.start,
                    )

        current_trading_day = (
            current_calendar.trade_date if current_calendar.is_trading_day else None
        )
        return ProductMarketPhase(
            normalized,
            MarketPhase.CLOSED,
            current_trading_day,
            None,
            self._next_session_start(resolved, local_now),
        )

    def _nearby_calendar_rows(
        self,
        exchange: str,
        current_day: date,
    ) -> dict[date, TradingCalendar] | None:
        rows: dict[date, TradingCalendar] = {}
        current = self._session.scalar(
            select(TradingCalendar).where(
                TradingCalendar.exchange_code == exchange,
                TradingCalendar.trade_date == current_day,
            )
        )
        if current is not None:
            rows[current.trade_date] = current
        next_trading_day = self._session.scalar(
            select(TradingCalendar)
            .where(
                TradingCalendar.exchange_code == exchange,
                TradingCalendar.trade_date > current_day,
                TradingCalendar.is_trading_day.is_(True),
            )
            .order_by(TradingCalendar.trade_date)
            .limit(1)
        )
        if next_trading_day is not None:
            expected_calendar_days = (next_trading_day.trade_date - current_day).days + 1
            actual_calendar_days = int(
                self._session.scalar(
                    select(func.count())
                    .select_from(TradingCalendar)
                    .where(
                        TradingCalendar.exchange_code == exchange,
                        TradingCalendar.trade_date >= current_day,
                        TradingCalendar.trade_date <= next_trading_day.trade_date,
                    )
                )
                or 0
            )
            if actual_calendar_days != expected_calendar_days:
                return None
            rows[next_trading_day.trade_date] = next_trading_day
        return rows

    @staticmethod
    def _next_session_start(
        resolved: list[tuple[date, ResolvedSessionWindow]],
        now: datetime,
    ) -> datetime | None:
        return next(
            (item.window.start for _, item in resolved if item.window.start > now),
            None,
        )

    @staticmethod
    def _unknown(symbol: str) -> ProductMarketPhase:
        return ProductMarketPhase(symbol, MarketPhase.UNKNOWN, None, None, None)
