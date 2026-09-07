"""交易日到实际历史 SessionWindow 的唯一转换逻辑。"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.market_data.aggregation import SessionWindow
from app.models import TradingCalendar, TradingSession


SHANGHAI = ZoneInfo("Asia/Shanghai")


class SessionClockError(RuntimeError):
    """历史 Session 事实无法构成有效窗口。"""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ResolvedSessionWindow:
    """带原始 Session 元数据的实际交易窗口。"""

    name: str
    window: SessionWindow
    is_night: bool


def resolved_session_windows_for_trading_day(
    session: Session,
    *,
    exchange: str,
    symbol: str,
    trading_day: date,
) -> tuple[ResolvedSessionWindow, ...]:
    """以交易日为身份解析日盘与锚定前一交易日的带元数据窗口。"""
    templates = tuple(
        session.scalars(
            select(TradingSession)
            .where(
                TradingSession.exchange_code == exchange,
                TradingSession.instrument_symbol == symbol.strip().lower(),
                TradingSession.is_active.is_(True),
                TradingSession.effective_from <= trading_day,
                (
                    TradingSession.effective_to.is_(None)
                    | (TradingSession.effective_to >= trading_day)
                ),
            )
            .order_by(TradingSession.start_time)
        )
    )
    if not templates:
        raise SessionClockError("TRADING_SESSION_MISSING")
    prior = session.scalar(
        select(func.max(TradingCalendar.trade_date)).where(
            TradingCalendar.exchange_code == exchange,
            TradingCalendar.trade_date < trading_day,
            TradingCalendar.is_trading_day.is_(True),
        )
    )
    return _resolve_templates(templates, trading_day, prior)


def _resolve_templates(
    templates: Sequence[TradingSession], trading_day: date, prior: date | None
) -> tuple[ResolvedSessionWindow, ...]:
    if not templates:
        raise SessionClockError("TRADING_SESSION_MISSING")
    windows: list[ResolvedSessionWindow] = []
    for template in templates:
        is_night = template.start_time >= time(18)
        if is_night and prior is None:
            raise SessionClockError("PREVIOUS_TRADING_DAY_MISSING")
        base = prior if is_night else trading_day
        assert base is not None
        local_start = datetime.combine(base, template.start_time, tzinfo=SHANGHAI)
        end_day = base
        if template.crosses_midnight or template.end_time <= template.start_time:
            end_day += timedelta(days=1)
        local_end = datetime.combine(end_day, template.end_time, tzinfo=SHANGHAI)
        windows.append(
            ResolvedSessionWindow(
                name=template.session_name,
                window=SessionWindow(local_start, local_end),
                is_night=is_night,
            )
        )
    windows.sort(key=lambda item: item.window.start)
    return tuple(windows)


def session_windows_for_trading_day(
    session: Session,
    *,
    exchange: str,
    symbol: str,
    trading_day: date,
) -> tuple[SessionWindow, ...]:
    """兼容投影：仅返回实际窗口，保持既有调用方行为。"""
    return tuple(
        item.window
        for item in resolved_session_windows_for_trading_day(
            session,
            exchange=exchange,
            symbol=symbol,
            trading_day=trading_day,
        )
    )


class SessionWindowBatch:
    """Request-local authoritative facts; resolving each day performs no SQL."""

    def __init__(
        self,
        session: Session,
        *,
        exchange: str,
        symbol: str,
        trading_days: tuple[date, ...],
    ) -> None:
        self.templates: tuple[TradingSession, ...] = ()
        self.calendar: tuple[date, ...] = ()
        if not trading_days:
            return
        first, last = min(trading_days), max(trading_days)
        self.templates = tuple(
            session.scalars(
                select(TradingSession)
                .where(
                    TradingSession.exchange_code == exchange,
                    TradingSession.instrument_symbol == symbol.strip().lower(),
                    TradingSession.is_active.is_(True),
                    TradingSession.effective_from <= last,
                    TradingSession.effective_to.is_(None)
                    | (TradingSession.effective_to >= first),
                )
                .order_by(TradingSession.start_time)
            )
        )
        prior = (
            select(func.max(TradingCalendar.trade_date))
            .where(
                TradingCalendar.exchange_code == exchange,
                TradingCalendar.trade_date < first,
                TradingCalendar.is_trading_day.is_(True),
            )
            .scalar_subquery()
        )
        self.calendar = tuple(
            session.scalars(
                select(TradingCalendar.trade_date)
                .where(
                    TradingCalendar.exchange_code == exchange,
                    TradingCalendar.is_trading_day.is_(True),
                    TradingCalendar.trade_date <= last,
                    (TradingCalendar.trade_date >= first)
                    | (TradingCalendar.trade_date == prior),
                )
                .order_by(TradingCalendar.trade_date)
            )
        )

    def windows(self, trading_day: date) -> tuple[SessionWindow, ...]:
        templates = tuple(
            t
            for t in self.templates
            if t.effective_from <= trading_day
            and (t.effective_to is None or t.effective_to >= trading_day)
        )
        index = bisect_left(self.calendar, trading_day)
        prior = self.calendar[index - 1] if index else None
        return tuple(
            item.window for item in _resolve_templates(templates, trading_day, prior)
        )
