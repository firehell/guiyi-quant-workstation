from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from bisect import bisect_left
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.data_center import TradingCalendar, TradingSession
from app.services.jm_session_contract import (
    JM_HISTORICAL_CALENDAR_FLAG_START,
    jm_historical_night_bounds,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
NIGHT_SESSION_CUTOFF = time(18, 0)


@dataclass(frozen=True)
class SessionWindow:
    trading_day: date
    name: str
    start: datetime
    end: datetime


@dataclass(frozen=True)
class TradingSessionDecision:
    product: str
    exchange: str
    now: datetime
    phase: str
    should_poll: bool
    is_trading_time: bool
    trading_day: date | None
    session_name: str | None
    session_start: datetime | None
    session_end: datetime | None
    final_close_at: datetime | None
    next_open_at: datetime | None
    reason: str


class TradingSessionClock:
    def __init__(self, session: Session, *, close_grace_seconds: int = 90) -> None:
        self.session = session
        self.close_grace_seconds = max(0, int(close_grace_seconds))
        self._trading_day_cache: dict[tuple[str, date], tuple[tuple[date, bool], ...]] = {}

    def decision(self, *, product: str, exchange: str, now: datetime | None = None) -> TradingSessionDecision:
        current = _local_naive(now or datetime.now(UTC))
        normalized_product = str(product).strip().lower()
        normalized_exchange = str(exchange).strip().upper()
        calendars = self._calendar_rows(normalized_exchange, current.date() - timedelta(days=10), current.date() + timedelta(days=10))
        trading_days = sorted(row.trade_date for row in calendars if row.is_trading_day)
        sessions = self._session_rows(normalized_product, normalized_exchange)
        if not calendars:
            return _decision(normalized_product, normalized_exchange, current, reason="trading_calendar_missing")
        if not sessions:
            return _decision(normalized_product, normalized_exchange, current, reason="trading_sessions_missing")

        windows: list[SessionWindow] = []
        for trading_day in trading_days:
            windows.extend(self.windows_for_trading_day(trading_day, product=normalized_product, exchange=normalized_exchange))
        windows.sort(key=lambda item: item.start)

        for window in windows:
            if window.start <= current <= window.end:
                final_close = self.final_close_at(window.trading_day, product=normalized_product, exchange=normalized_exchange)
                return TradingSessionDecision(
                    product=normalized_product,
                    exchange=normalized_exchange,
                    now=current,
                    phase="open",
                    should_poll=True,
                    is_trading_time=True,
                    trading_day=window.trading_day,
                    session_name=window.name,
                    session_start=window.start,
                    session_end=window.end,
                    final_close_at=final_close,
                    next_open_at=_next_open(windows, current),
                    reason="inside_trading_session",
                )
            grace_end = window.end + timedelta(seconds=self.close_grace_seconds)
            if window.end < current <= grace_end:
                final_close = self.final_close_at(window.trading_day, product=normalized_product, exchange=normalized_exchange)
                return TradingSessionDecision(
                    product=normalized_product,
                    exchange=normalized_exchange,
                    now=current,
                    phase="close_grace",
                    should_poll=True,
                    is_trading_time=False,
                    trading_day=window.trading_day,
                    session_name=window.name,
                    session_start=window.start,
                    session_end=window.end,
                    final_close_at=final_close,
                    next_open_at=_next_open(windows, current),
                    reason="inside_close_grace",
                )

        return TradingSessionDecision(
            product=normalized_product,
            exchange=normalized_exchange,
            now=current,
            phase="closed",
            should_poll=False,
            is_trading_time=False,
            trading_day=None,
            session_name=None,
            session_start=None,
            session_end=None,
            final_close_at=None,
            next_open_at=_next_open(windows, current),
            reason="outside_trading_sessions",
        )

    def windows_for_trading_day(self, trading_day: date, *, product: str, exchange: str) -> list[SessionWindow]:
        normalized_exchange = str(exchange).upper()
        sessions = self._session_rows(str(product).lower(), normalized_exchange)
        previous_trading_day = self._previous_trading_day(trading_day, normalized_exchange)
        calendar_rows = self._calendar_rows(normalized_exchange, trading_day, trading_day)
        has_night_session = bool(calendar_rows and calendar_rows[0].has_night_session)
        windows: list[SessionWindow] = []
        for item in sessions:
            is_night = item.start_time >= NIGHT_SESSION_CUTOFF or item.crosses_midnight
            start_time = item.start_time
            end_time = item.end_time
            crosses_midnight = item.crosses_midnight
            if is_night:
                historical_bounds = _historical_jm_night_bounds(
                    product=str(product).lower(),
                    exchange=normalized_exchange,
                    trading_day=trading_day,
                    previous_trading_day=previous_trading_day,
                )
                if historical_bounds is not None:
                    start_time, end_time = historical_bounds
                    crosses_midnight = end_time <= start_time
                elif _uses_historical_jm_policy(
                    str(product).lower(), normalized_exchange, trading_day
                ) or not has_night_session:
                    continue
            anchor = previous_trading_day if is_night else trading_day
            if anchor is None:
                continue
            start = datetime.combine(anchor, start_time)
            end_day = anchor
            if crosses_midnight or end_time <= start_time:
                end_day += timedelta(days=1)
            end = datetime.combine(end_day, end_time)
            windows.append(SessionWindow(trading_day=trading_day, name=item.session_name, start=start, end=end))
        return sorted(windows, key=lambda item: item.start)

    def windows_for_trading_days(
        self,
        trading_days: list[date] | tuple[date, ...],
        *,
        product: str,
        exchange: str,
    ) -> list[SessionWindow]:
        """Build many day windows with one session and one calendar snapshot."""
        requested = sorted(set(trading_days))
        if not requested:
            return []
        normalized_product = str(product).lower()
        normalized_exchange = str(exchange).upper()
        sessions = self._session_rows(normalized_product, normalized_exchange)
        cache_key = (normalized_exchange, requested[-1])
        calendar_entries = self._trading_day_cache.get(cache_key)
        if calendar_entries is None:
            calendar_entries = tuple(
                (row.trade_date, row.has_night_session)
                for row in self._calendar_rows(
                    normalized_exchange,
                    date(1990, 1, 1),
                    requested[-1],
                )
                if row.is_trading_day
            )
            self._trading_day_cache[cache_key] = calendar_entries
        calendar_days = tuple(item[0] for item in calendar_entries)
        has_night_session = dict(calendar_entries)

        windows: list[SessionWindow] = []
        for trading_day in requested:
            position = bisect_left(calendar_days, trading_day)
            previous_trading_day = calendar_days[position - 1] if position else None
            for item in sessions:
                is_night = item.start_time >= NIGHT_SESSION_CUTOFF or item.crosses_midnight
                start_time = item.start_time
                end_time = item.end_time
                crosses_midnight = item.crosses_midnight
                if is_night:
                    historical_bounds = _historical_jm_night_bounds(
                        product=normalized_product,
                        exchange=normalized_exchange,
                        trading_day=trading_day,
                        previous_trading_day=previous_trading_day,
                    )
                    if historical_bounds is not None:
                        start_time, end_time = historical_bounds
                        crosses_midnight = end_time <= start_time
                    elif _uses_historical_jm_policy(
                        normalized_product, normalized_exchange, trading_day
                    ) or not has_night_session.get(trading_day, False):
                        continue
                anchor = previous_trading_day if is_night else trading_day
                if anchor is None:
                    continue
                start = datetime.combine(anchor, start_time)
                end_day = anchor
                if crosses_midnight or end_time <= start_time:
                    end_day += timedelta(days=1)
                windows.append(
                    SessionWindow(
                        trading_day=trading_day,
                        name=item.session_name,
                        start=start,
                        end=datetime.combine(end_day, end_time),
                    )
                )
        return sorted(windows, key=lambda item: item.start)

    def trading_days_between(self, start: date, end: date, *, exchange: str) -> tuple[list[date], bool]:
        rows = self._calendar_rows(str(exchange).upper(), start, end)
        covered_dates = {row.trade_date for row in rows}
        expected_natural_days = (end - start).days + 1
        complete = len(covered_dates) == expected_natural_days
        return [row.trade_date for row in rows if row.is_trading_day], complete

    def final_close_at(self, trading_day: date, *, product: str, exchange: str) -> datetime | None:
        windows = self.windows_for_trading_day(trading_day, product=product, exchange=exchange)
        return max((window.end for window in windows), default=None)

    def expected_minute_count(self, trading_day: date, *, product: str, exchange: str) -> int:
        return sum(max(0, int((window.end - window.start).total_seconds() // 60)) for window in self.windows_for_trading_day(trading_day, product=product, exchange=exchange))

    def latest_completed_trading_day(self, *, product: str, exchange: str, now: datetime) -> date:
        current = _local_naive(now)
        normalized_exchange = str(exchange).strip().upper()
        calendar = self._calendar_rows(normalized_exchange, current.date() - timedelta(days=14), current.date())
        covered = {row.trade_date for row in calendar}
        if current.date() not in covered:
            raise RuntimeError("trading_calendar_stale")
        candidates = sorted((row.trade_date for row in calendar if row.is_trading_day), reverse=True)
        for trading_day in candidates:
            final_close = self.final_close_at(trading_day, product=product, exchange=normalized_exchange)
            if final_close is None:
                raise RuntimeError(f"trading_session_close_missing:{trading_day.isoformat()}")
            if current > final_close + timedelta(seconds=self.close_grace_seconds):
                return trading_day
        raise RuntimeError("completed_trading_day_missing")

    def trading_day_closed(self, trading_day: date, *, product: str, exchange: str, now: datetime) -> bool:
        final_close = self.final_close_at(trading_day, product=product, exchange=exchange)
        if final_close is None:
            return False
        return _local_naive(now) > final_close + timedelta(seconds=self.close_grace_seconds)

    def week_trading_days(self, value: date, *, exchange: str) -> tuple[list[date], bool]:
        monday = value - timedelta(days=value.weekday())
        sunday = monday + timedelta(days=6)
        rows = self._calendar_rows(str(exchange).upper(), monday, sunday)
        covered_dates = {row.trade_date for row in rows}
        complete_calendar = len(covered_dates) == 7
        return sorted(row.trade_date for row in rows if row.is_trading_day), complete_calendar

    def has_session_templates(self, *, product: str, exchange: str) -> bool:
        return bool(self._session_rows(str(product).lower(), str(exchange).upper()))

    def _calendar_rows(self, exchange: str, start: date, end: date) -> list[TradingCalendar]:
        return list(
            self.session.scalars(
                select(TradingCalendar)
                .where(
                    TradingCalendar.exchange_code == exchange,
                    TradingCalendar.trade_date >= start,
                    TradingCalendar.trade_date <= end,
                )
                .order_by(TradingCalendar.trade_date)
            )
        )

    def _session_rows(self, product: str, exchange: str) -> list[TradingSession]:
        rows = list(
            self.session.scalars(
                select(TradingSession)
                .where(
                    TradingSession.exchange_code == exchange,
                    TradingSession.is_active.is_(True),
                    or_(TradingSession.instrument_symbol == product, TradingSession.instrument_symbol.is_(None)),
                )
                .order_by(TradingSession.instrument_symbol.desc(), TradingSession.start_time)
            )
        )
        specific = [
            row
            for row in rows
            if (row.instrument_symbol or "").lower() == product
        ]
        if specific:
            return specific
        return [row for row in rows if row.instrument_symbol is None]

    def _previous_trading_day(self, trading_day: date, exchange: str) -> date | None:
        return self.session.scalar(
            select(TradingCalendar.trade_date)
            .where(
                TradingCalendar.exchange_code == exchange,
                TradingCalendar.trade_date < trading_day,
                TradingCalendar.is_trading_day.is_(True),
            )
            .order_by(TradingCalendar.trade_date.desc())
            .limit(1)
        )


def _uses_historical_jm_policy(
    product: str,
    exchange: str,
    trading_day: date,
) -> bool:
    return (
        product == "jm"
        and exchange == "DCE"
        and trading_day < JM_HISTORICAL_CALENDAR_FLAG_START
    )


def _historical_jm_night_bounds(
    *,
    product: str,
    exchange: str,
    trading_day: date,
    previous_trading_day: date | None,
) -> tuple[time, time] | None:
    if not _uses_historical_jm_policy(product, exchange, trading_day):
        return None
    return jm_historical_night_bounds(
        trading_day=trading_day,
        previous_trading_day=previous_trading_day,
    )


def _decision(product: str, exchange: str, now: datetime, *, reason: str) -> TradingSessionDecision:
    return TradingSessionDecision(
        product=product,
        exchange=exchange,
        now=now,
        phase="blocked",
        should_poll=False,
        is_trading_time=False,
        trading_day=None,
        session_name=None,
        session_start=None,
        session_end=None,
        final_close_at=None,
        next_open_at=None,
        reason=reason,
    )


def _next_open(windows: list[SessionWindow], now: datetime) -> datetime | None:
    return next((window.start for window in windows if window.start > now), None)


def _local_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(SHANGHAI).replace(tzinfo=None)
